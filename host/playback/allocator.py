"""Auto Arranger / Voice Allocator: MIDI + orkiestra -> PerformancePlan.

To jest serce nowej architektury. Urzadzenie NIE jest przywiazane do pitchu:
kazda nuta dostaje najpierw *preferowane* urzadzenie (rola muzyczna, reczna
regula, ciaglosc glosu), ale gdy jest zajete, allocator siega po KAZDE inne
kompatybilne i wolne.

Podstawowy invariant v1:

    Nuta nie moze dostac DROP tylko dlatego, ze jej preferowane urzadzenie
    jest zajete, jesli istnieje inne kompatybilne, wolne i zdolne ja zagrac
    urzadzenie.

Kolejnosc ratowania nuty:
    1. wolne preferowane urzadzenie            -> ACCEPTED
    2. wolne inne kompatybilne urzadzenie      -> REASSIGNED
    3. urzadzenie zwalnia sie w oknie delayu   -> DELAYED
    4. j.w., ale poza oknem (rozlozenie)       -> ARPEGGIATED
    5. odebranie glosu slabszej nucie          -> STOLEN / SHORTENED
    6. dopiero teraz                           -> DROPPED

Algorytm jest w pelni deterministyczny: ten sam plik + ta sama orkiestra +
ta sama polityka zawsze daja identyczny plan (brak zbiorow nieuporzadkowanych,
brak czasu biezacego, brak losowosci).
"""
from __future__ import annotations

import dataclasses

from midi_source import MidiSource, NoteSpan
from pitch import fold_note, midi_to_hz
from . import analysis as analysis_module
from .analysis import BASS, HARMONY, LEAD, PERCUSSION, MidiAnalysis
from .articulation import apply as apply_articulation
from .articulation import params_from_policy, apply_source_continuity
from .capabilities import DeviceCapability, capabilities_for
from .orchestra import OrchestraConfig, parse_policy
from .performance import PerformanceEvent, PerformancePlan
from .device_models import VirtualDeviceInstance
from .reinforcement import apply_reinforcement

# Compatibility exports for existing CLI/tests. Implementations live in neutral
# modules; hardware allocation and refinements import those modules directly.
from .allocation_models import ManualPin, AllocationSlot as _Slot, AllocationCandidate as _Candidate
from .allocation_operations import (note_priority as _priority, clip_duration as _clip,
    adaptive_cap as _adaptive_cap, dropped_event as _dropped, commit_event as _commit,
    place_event as _place)
from .allocation_input import (source_notes as _source_notes,
    partition_effects as _partition_effects, duplicate_kpis as _duplicate_kpis)

EPS = 1e-9

# Odstep miedzy powtorzona ta sama wysokoscia na tym samym urzadzeniu
# (mechanika musi zdazyc sie zatrzymac - patrz timeline.ARTICULATION_S).
ARTICULATION_S = 0.012

# Klasy brzmien perkusyjnych -> indeks preferowanego HDD.
_PERCUSSION_CLASS = {
    35: 0, 36: 0,                                        # stopa
    38: 1, 39: 1, 40: 1,                                 # werbel / clap
    41: 1, 43: 1, 45: 1, 47: 1, 48: 1, 50: 1,            # tomy
    42: 2, 44: 2, 46: 2,                                 # hi-hat
    49: 2, 51: 2, 52: 2, 53: 2, 55: 2, 57: 2, 59: 2,     # czary / ride
}

# Nominalna dlugosc uderzenia, gdy profil nie podaje cyklu.
_MIN_HIT_S = 0.05


def _fold(note: int, capability: DeviceCapability, transpose: int,
          mode: str, allow_fold: bool = True):
    """(played_note, hz, folded, in_range) dla danego urzadzenia."""
    if not capability.has_range:
        return note + transpose, midi_to_hz(note + transpose), False, True

    if allow_fold:
        folded = fold_note(note + transpose, capability.min_hz, capability.max_hz, mode)

        return (folded.midi_note + 12 * folded.octave_shift, folded.hz,
                bool(folded.octave_shift), bool(folded.in_range))

    shifted = note + transpose
    hz = midi_to_hz(shifted)

    return shifted, hz, False, capability.min_hz <= hz <= capability.max_hz


def _classify_slots(devices: list[VirtualDeviceInstance]):
    """Dzieli urzadzenia na TRZY rozlaczne pule.

    ``lead`` i ``accompaniment`` nie maja czesci wspolnej - urzadzenie
    ``lead-only`` (VHS) nie wystepuje na liscie kandydatow akompaniamentu,
    wiec nie da sie go wybrac, ukrasc ani uzyc jako fallbacku.
    """
    caps = capabilities_for(devices)
    lead: list[_Slot] = []
    accompaniment: list[_Slot] = []
    percussion: list[_Slot] = []

    for device in devices:
        slot = _Slot(device=device, capability=caps[device.id])
        if slot.capability.role_policy == 'reinforcement-only':
            continue

        if not slot.capability.tonal:
            percussion.append(slot)
        elif slot.capability.lead_only:
            lead.append(slot)
        else:
            accompaniment.append(slot)

    return lead, accompaniment, percussion


def _choose_preferred(candidates: list[_Candidate], role: str) -> _Candidate:
    """Ktore urzadzenie *chcialoby* dostac te nute (zanim sprawdzimy zajetosc).

    Lista kandydatow jest juz zawezona do wlasciwej puli, wiec nie ma tu
    zadnego odsiewania VHS - on po prostu nie moze sie tu znalezc.
    """
    # FDD jest glownym instrumentem akompaniamentu; DVD to dodatkowy glos.
    # W obrebie typu zachowujemy dotychczasowe prowadzenie glosow.
    return min(candidates, key=lambda c: (
        0 if role != LEAD and c.slot.device.type == 'FDD' else 1,
        abs(c.slot.headroom - c.played), c.slot.device.id))


def _allocate_lead(note: dict, slots: list[_Slot], events: list[PerformanceEvent],
                   policy: dict, pin: ManualPin | None) -> None:
    """VHS: dedykowana linia melodyczna. Twarde reguly, nie preferencje.

    * brak arpeggio - melodia nie moze sie rozjechac rytmicznie,
    * brak reassignmentu do puli akompaniamentu (VHS albo nic),
    * brak voice stealu przez akompaniament (VHS nie ma na jego liscie),
    * gdy poprzednia nuta leadu jeszcze brzmi, wolimy ja SKROCIC albo
      przesunac nowa o kilka ms - nigdy nie oddajemy melodii na FDD.
    """
    role = LEAD
    span: NoteSpan = note['span']
    start = span.start
    transpose = pin.transpose if pin else 0
    allow_fold = pin.octave_fold if pin else True
    compatible: list[_Candidate] = []

    for slot in slots:
        played, hz, folded, in_range = _fold(span.note, slot.capability,
                                             transpose, policy['foldMode'], allow_fold)

        if in_range:
            compatible.append(_Candidate(slot=slot, played=played, hz=hz, folded=folded))

    if not compatible:
        events.append(_dropped(note, 'NO_COMPATIBLE_LEAD_DEVICE', role,
                               pin.device_id if pin else None, pin))

        return

    preferred = _choose_preferred(compatible, role)

    if pin is not None and pin.device_id is not None:
        for candidate in compatible:
            if candidate.slot.device.id == pin.device_id:
                preferred = candidate
                break

    def ready_at(candidate: _Candidate) -> float:
        gap = (ARTICULATION_S if policy.get('softenRepeats', True)
               and candidate.slot.last_played == candidate.played else 0.0)

        return candidate.slot.busy_until + gap

    gate = pin.gate if pin else 1.0
    duration = _clip(span.duration * gate, preferred.slot.capability.min_note_s,
                     policy, 'leadMaxNoteSeconds')
    preferred_id = preferred.slot.device.id
    free = [candidate for candidate in compatible if ready_at(candidate) <= start + EPS]

    if free:
        if any(candidate is preferred for candidate in free):
            chosen, outcome = preferred, 'ACCEPTED'
        else:
            chosen = min(free, key=lambda c: (abs(c.slot.headroom - c.played),
                                              c.slot.device.id))
            outcome = 'REASSIGNED'

        _place(chosen.slot, chosen, note, outcome, start, duration, role, pin,
               preferred_id, events)

        return

    options = sorted(compatible, key=lambda c: (ready_at(c), c.slot.device.id))
    chosen = options[0]
    arrival = ready_at(chosen)
    wait = arrival - start
    lead_window = float(policy.get('leadMaxMicroDelayMs', 12.0)) / 1000.0

    if wait <= lead_window + EPS:
        _place(chosen.slot, chosen, note, 'DELAYED', arrival, duration, role, pin,
               preferred_id, events)

        return

    # Wlasna nuta leadu blokuje linie melodii. Nie ma tu porownywania
    # priorytetow (obie nuty sa leadem) - po prostu skracamy poprzednia,
    # zeby melodia szla dalej bez oddawania jej na FDD.
    slot = chosen.slot
    previous = events[slot.event_index] if slot.event_index is not None else None

    if (previous is not None and previous.outcome not in ('DROPPED', 'SHORTENED')
            and start - previous.actual_start >= slot.capability.min_note_s - EPS):
        cut = start - previous.actual_start
        events[slot.event_index] = dataclasses.replace(
            previous, actual_duration=cut, outcome='SHORTENED',
            reason=f'STOLEN_BY:{note["id"]}')
        slot.busy_until = start
        played, hz, folded, _ = _fold(span.note, slot.capability, transpose,
                                      policy['foldMode'], allow_fold)
        event = _place(slot, _Candidate(slot, played, hz, folded), note, 'STOLEN',
                       start, _clip(span.duration * gate, slot.capability.min_note_s,
                                    policy, 'leadMaxNoteSeconds'),
                       role, pin, preferred_id, events)
        events[-1] = dataclasses.replace(event, stolen_from=previous.id)

        return

    events.append(_dropped(note, 'LEAD_DEVICE_BLOCKED', role, preferred_id, pin))


def _allocate_tonal(note: dict, slots: list[_Slot], events: list[PerformanceEvent],
                    policy: dict, pin: ManualPin | None) -> None:
    role = note['role']
    span: NoteSpan = note['span']
    start = span.start
    transpose = pin.transpose if pin else 0
    allow_fold = pin.octave_fold if pin else True
    compatible: list[_Candidate] = []

    for slot in slots:
        played, hz, folded, in_range = _fold(span.note, slot.capability,
                                             transpose, policy['foldMode'], allow_fold)

        if in_range:
            compatible.append(_Candidate(slot=slot, played=played, hz=hz, folded=folded))

    if not compatible:
        events.append(_dropped(note, 'NO_COMPATIBLE_DEVICE', role,
                               pin.device_id if pin else None, pin))

        return

    preferred = _choose_preferred(compatible, role)

    if pin is not None and pin.device_id is not None:
        for candidate in compatible:
            if candidate.slot.device.id == pin.device_id:
                preferred = candidate
                break

    def ready_at(candidate: _Candidate) -> float:
        gap = (ARTICULATION_S if policy.get('softenRepeats', True)
               and candidate.slot.last_played == candidate.played else 0.0)

        return candidate.slot.busy_until + gap

    def free_now(candidate: _Candidate) -> bool:
        return ready_at(candidate) <= start + EPS

    free = [candidate for candidate in compatible if free_now(candidate)]
    gate = pin.gate if pin else 1.0
    minimum = preferred.slot.capability.min_note_s
    duration = _clip(span.duration * gate, minimum, policy)
    preferred_id = preferred.slot.device.id

    if free:
        if any(candidate is preferred for candidate in free):
            chosen, outcome = preferred, 'ACCEPTED'
        else:
            # Preferowane zajete - bierzemy wolne, najblizsze poprzedniej
            # wysokosci na tym urzadzeniu (mniej mechanicznego travelu).
            chosen = min(free, key=lambda c: (
                0 if c.slot.device.type == 'FDD' else 1,
                abs(c.slot.headroom - c.played), c.slot.device.id))
            outcome = 'REASSIGNED'

        _place(chosen.slot, chosen, note, outcome, start, duration, role, pin,
               preferred_id, events)

        return

    options = sorted(compatible, key=lambda c: (ready_at(c), c.slot.device.id))
    chosen = options[0]
    arrival = ready_at(chosen)
    wait = arrival - start

    if wait <= policy['maxMicroDelayMs'] / 1000.0 + EPS:
        _place(chosen.slot, chosen, note, 'DELAYED', arrival, duration, role, pin,
               preferred_id, events)

        return

    if role != LEAD and wait <= policy['maxArpeggioMs'] / 1000.0 + EPS:
        _place(chosen.slot, chosen, note, 'ARPEGGIATED', arrival, duration, role, pin,
               preferred_id, events)

        return

    if policy.get('allowVoiceSteal', True):
        # Najpierw naprawde slabsza nuta (z marginesem). Jesli takiej nie ma,
        # a alternatywa jest DROP, skracamy najmniej wazna aktywna nute:
        # krotsza nuta wciaz brzmi, dropnieta nie brzmi wcale.
        victim = (_pick_victim(compatible, events, note, policy,
                               margin=float(policy.get('stealMargin', 12.0)))
                  or _pick_victim(compatible, events, note, policy, margin=0.0))

        if victim is not None:
            slot, previous = victim
            cut = max(slot.capability.min_note_s, start - previous.actual_start)
            events[slot.event_index] = dataclasses.replace(
                previous, actual_duration=cut, outcome='SHORTENED',
                reason=f'STOLEN_BY:{note["id"]}')
            slot.busy_until = start
            played, hz, folded, _ = _fold(span.note, slot.capability, transpose,
                                          policy['foldMode'], allow_fold)
            event = _place(slot, _Candidate(slot, played, hz, folded), note, 'STOLEN',
                           start, _clip(span.duration * gate,
                                        slot.capability.min_note_s, policy),
                           role, pin, preferred_id, events)
            events[-1] = dataclasses.replace(event, stolen_from=previous.id)

            return

    events.append(_dropped(note, 'ALL_DEVICES_BUSY_AND_NO_DELAY', role,
                           preferred_id, pin))


def _pick_victim(compatible: list[_Candidate], events: list[PerformanceEvent],
                 note: dict, policy: dict, *, margin: float):
    """Najslabsza aktywna nuta, ktora warto poswiecic.

    ``margin`` > 0 chroni aktywne glosy (bierzemy tylko wyraznie slabsza nute);
    ``margin`` = 0 to ostatnia deska ratunku przed DROP-em.
    """
    new_priority = _priority(note['role'], note['span'].velocity, note['span'].duration, policy)
    best = None

    for candidate in compatible:
        slot = candidate.slot

        if slot.event_index is None:
            continue

        previous = events[slot.event_index]

        if previous.outcome in ('DROPPED', 'SHORTENED'):
            continue

        # Urzadzenie gra od tak dawna, ze da sie je zwolnic bez nakladania?
        # Nuta-ofiara nie moze byc krotsza niz mechaniczne minimum, wiec
        # "swiezy" glos jest de facto niedostepny.
        if note['span'].start - previous.actual_start < slot.capability.min_note_s - EPS:
            continue

        victim_priority = _priority(previous.role, previous.velocity,
                                    previous.duration, policy)

        if victim_priority + margin > new_priority:
            continue

        key = (victim_priority, slot.device.id)

        if best is None or key < best[0]:
            best = (key, slot, previous)

    return None if best is None else (best[1], best[2])


def _allocate_percussion(note: dict, slots: list[_Slot], events: list[PerformanceEvent],
                         policy: dict, pin: ManualPin | None) -> None:
    span = note['span']

    if not slots:
        events.append(_dropped(note, 'NO_PERCUSSION_DEVICE', PERCUSSION,
                               pin.device_id if pin else None, pin))

        return

    start = span.start
    order = sorted(slots, key=lambda slot: slot.device.id)
    claimed = _PERCUSSION_CLASS.get(span.note, 0) % len(order)
    preferred = order[claimed]

    if pin is not None and pin.device_id is not None:
        for slot in order:
            if slot.device.id == pin.device_id:
                preferred = slot
                break

    free = [slot for slot in order if slot.busy_until <= start + EPS]

    def hit(slot: _Slot, at: float, outcome: str) -> None:
        duration = max(slot.capability.retrigger_s, _MIN_HIT_S)
        _place(slot, _Candidate(slot, None, None, False), note, outcome, at,
               duration, PERCUSSION, pin, preferred.device.id, events)

    if preferred in free:
        hit(preferred, start, 'ACCEPTED')

        return

    if free:
        hit(free[0], start, 'REASSIGNED')

        return

    earliest = min(order, key=lambda slot: (slot.busy_until, slot.device.id))

    if earliest.busy_until - start <= policy['maxMicroDelayMs'] / 1000.0 + EPS:
        hit(earliest, earliest.busy_until, 'DELAYED')

        return

    events.append(_dropped(note, 'ALL_HAMMERS_BUSY', PERCUSSION,
                           preferred.device.id, pin))


def manual_pins(arrangement, source: MidiSource) -> dict[str, ManualPin]:
    """Zamienia reczne reguly Arrangement na preferencje allokatora.

    Regula nie jest juz przybiciem na stale: jesli wskazane urzadzenie jest
    zajete, a inne wolne - allocator i tak uratuje nute (REASSIGNED).
    """
    by_device, notes = arrangement.route(source)
    pins: dict[str, ManualPin] = {}

    for device_id, routed in by_device.items():
        for item in routed:
            pins.setdefault(item.note_id, ManualPin(
                device_id=device_id, rule_id=item.rule_id,
                articulation=item.articulation, transpose=item.transpose,
                gate=item.gate, octave_fold=item.octave_fold))

    for note in notes:
        for route in note.get('routes', []):
            if route.get('deviceId') is None:
                pins.setdefault(note['id'], ManualPin(
                    device_id=None, rule_id=route.get('ruleId') or 'manual-drop'))

    return pins


def allocate(source: MidiSource, config: OrchestraConfig, *,
             midi_analysis: MidiAnalysis | None = None,
             pins: dict[str, ManualPin] | None = None,
             name: str | None = None,
             origin: str = 'auto', hardware_context=None) -> PerformancePlan:
    """Buduje plan wykonania. To samo wejscie zawsze daje ten sam plan."""
    if hardware_context is not None:
        from .hardware_arranger import allocate_hardware
        return allocate_hardware(source, config, hardware_context, midi_analysis=midi_analysis,
                                 pins=pins, name=name, origin=origin)
    policy = parse_policy(config.policy)
    devices, _ = config.allocation_devices()
    midi_analysis = midi_analysis or analysis_module.analyze(source)
    pins = pins or {}
    lead_slots, accompaniment_slots, percussion = _classify_slots(devices)
    notes, events = _partition_effects(_source_notes(source, midi_analysis, policy), pins)
    from .percussion_routing import source_drops, limit_plan, RATE_LIMIT_REASON
    hdd_rate_drops = source_drops(notes,pins,
        {slot.device.id for slot in percussion if slot.device.type=='HDD_VCM'})

    # Kazda pula ma wlasny budzet dlugosci nut. Akompaniament nie zjada
    # pojemnosci zarezerwowanej dla melodii i odwrotnie.
    if policy.get('tonalOverflow') == 'adaptive':
        if not policy.get('maxNoteSeconds'):
            policy['maxNoteSeconds'] = _adaptive_cap(
                notes, accompaniment_slots, policy, frozenset({BASS, HARMONY}))

        if not policy.get('leadMaxNoteSeconds'):
            policy['leadMaxNoteSeconds'] = _adaptive_cap(
                notes, lead_slots or accompaniment_slots, policy, frozenset({LEAD}))

    lead_ids = {slot.device.id for slot in lead_slots}
    percussion_ids = {slot.device.id for slot in percussion}

    def eligible_pin(pin: ManualPin | None, role: str) -> ManualPin | None:
        """Reczna regula nie moze zlamac twardego rozdzialu rol.

        Wskazanie VHS dla basu/harmonii jest ignorowane - inaczej invariant
        "kazde zdarzenie na VHS ma role lead" przestalby byc prawdziwy.
        """
        if pin is None or pin.device_id is None:
            return pin

        if pin.device_id in lead_ids and role != LEAD:
            return None

        return pin

    for note in notes:
        pin = eligible_pin(pins.get(note['id']), note['role'])

        if pin is not None and pin.device_id is None:
            events.append(_dropped(note, 'MANUAL_DROP', note['role'], None, pin))

            continue

        if note['id'] in hdd_rate_drops:
            events.append(_dropped(note,RATE_LIMIT_REASON,note['role'],None,pin))
            continue

        kind = None

        if pin is not None and pin.device_id:
            kind = 'percussion' if pin.device_id in percussion_ids else 'tonal'

        if kind is None:
            kind = 'percussion' if note['role'] == PERCUSSION else 'tonal'

        if kind == 'percussion':
            _allocate_percussion(note, percussion, events, policy, pin)
        elif note['role'] == LEAD and lead_slots:
            # VHS jest zarezerwowany WYLACZNIE dla wykrytego leadu.
            _allocate_lead(note, lead_slots, events, policy, pin)
        else:
            # Bas, gitara i harmonia: FDD oraz dodatkowe tonalne DVD/steppery.
            # VHS pozostaje poza ta pula, o ile istnieje dedykowany lead.
            _allocate_tonal(note, accompaniment_slots or (lead_slots if note['role'] == LEAD else []),
                            events, policy, pin)

    duplicate_report = getattr(source, 'duplicate_report', None)
    duplicates = (_duplicate_kpis(source, notes, accompaniment_slots, duplicate_report)
                  if duplicate_report is not None else {})

    events.sort(key=lambda event: (event.actual_start, event.track, event.id))

    plan = PerformancePlan(
        name=name or source.path.stem,
        events=events,
        devices=[dataclasses.asdict(device) for device in devices],
        policy=policy,
        analysis=midi_analysis.as_dict(),
        origin=origin,
        lead_devices=tuple(slot.device.id for slot in lead_slots),
        duplicates=duplicates,
        dvd_mode=config.dvd_mode,
        idle_reinforcement=dict(config.idle_reinforcement),
    )

    # Warstwa wykonawcza: sourceDuration -> performedDuration. Wirtualizacja
    # i sprzet czytaja pozniej dokladnie ten sam plan, wiec musza dostac
    # identyczna dlugosc wykonawcza.
    plan.articulation = apply_articulation(plan, capabilities_for(devices),
                                           params_from_policy(policy))

    if policy.get('sourceContinuity'):
        plan.articulation['sourceContinuity'] = apply_source_continuity(plan, capabilities_for(devices), policy['sourceContinuityAmount'])

    raw_source = getattr(source, 'source', source)
    plan.analysis['trackPrograms'] = {str(t.index): [program
        for index in getattr(t, 'source_tracks', (t.index,))
        for program in raw_source.programs(index)] for t in source.tracks}
    from .tonal_articulation import capture
    plan.expression = capture(source)
    apply_reinforcement(plan, lambda e: _priority(e.role, e.velocity, e.duration, plan.policy))
    limit_plan(plan)

    return plan
