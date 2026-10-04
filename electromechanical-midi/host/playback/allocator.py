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
import statistics

from midi_source import MidiSource, NoteSpan, drum_name
from pitch import fold_note, midi_to_hz, note_name
from . import analysis as analysis_module
from .analysis import BASS, HARMONY, LEAD, PERCUSSION, MidiAnalysis
from .articulation import apply as apply_articulation
from .articulation import params_from_policy
from .capabilities import MIN_NOTE_S, DeviceCapability, capabilities_for
from .orchestra import OrchestraConfig, parse_policy
from .performance import PerformanceEvent, PerformancePlan, ReinforcementEvent
from .virtual import VirtualDeviceInstance
from .tray import add_reinforcement as add_tray_reinforcement

EPS = 1e-9

# Priorytety chronienia rol. Lead > bas > perkusja > harmonia.
_BASE_PRIORITY = {LEAD: 100.0, BASS: 80.0, PERCUSSION: 60.0, HARMONY: 40.0}

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

# Kolejnosc obslugi nut o tym samym czasie startu. Lead i bas dostaja glosy
# przed harmonia; harmonia wewnatrz sortowana po dlugosci (najkrotsze pierwsze).
_BAND = {LEAD: 0, BASS: 1, PERCUSSION: 1, HARMONY: 2}


@dataclasses.dataclass(frozen=True)
class ManualPin:
    """Reczna decyzja uzytkownika (z Arrangement JSON) - tylko preferencja."""

    device_id: str | None
    rule_id: str
    articulation: str | None = None
    transpose: int = 0
    gate: float = 1.0
    octave_fold: bool = True


@dataclasses.dataclass
class _Slot:
    """Stan jednego urzadzenia w trakcie allokacji."""

    device: VirtualDeviceInstance
    capability: DeviceCapability
    busy_until: float = 0.0
    last_played: int | None = None
    event_index: int | None = None      # indeks aktywnego zdarzenia (do voice steal)

    @property
    def headroom(self) -> int:
        """Wysokosc ostatnio granej nuty - do prowadzenia glosow i travelu."""
        return self.last_played if self.last_played is not None else 60


@dataclasses.dataclass(frozen=True)
class _Candidate:
    slot: _Slot
    played: int
    hz: float
    folded: bool


def _priority(role: str, velocity: int, duration: float, policy: dict) -> float:
    base = _BASE_PRIORITY.get(role, _BASE_PRIORITY[HARMONY])

    if role == LEAD and not policy.get('preserveLead', True):
        base = _BASE_PRIORITY[HARMONY]
    elif role == BASS and not policy.get('preserveBass', True):
        base = _BASE_PRIORITY[HARMONY]

    if role == PERCUSSION:
        return base + velocity / 127.0 * 20.0

    return base + velocity / 127.0 * 10.0 + min(duration, 0.6) * 12.0


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


def _clip(duration: float, minimum: float, policy: dict,
          key: str = 'maxNoteSeconds') -> float:
    """Dlugosc nuty w planie: nie krotsza niz mechanika i nie dluzsza niz budzet.

    Monofoniczna orkiestra gra raczej krotkim gate'em niz sustainem: bez
    limitu dlugie nuty blokuja glosy i wypychaja z planu cala reszte.
    """
    duration = max(duration, minimum)
    cap = float(policy.get(key) or 0.0)

    return min(duration, cap) if cap > 0 else duration


def _solve_cap(durations: list[float], budget: float) -> float:
    """Najwieksza dlugosc nuty, przy ktorej suma dlugosci <= budzet."""
    low, high = MIN_NOTE_S, max(durations)

    for _ in range(40):
        middle = (low + high) / 2.0

        if sum(min(duration, middle) for duration in durations) <= budget:
            low = middle
        else:
            high = middle

    return round(low, 4)


def _adaptive_cap(notes: list[dict], slots: list[_Slot], policy: dict,
                  roles: frozenset[str]) -> float:
    """Budzet dlugosci nuty dla monofonicznej orkiestry.

    N glosow x dlugosc utworu to twarda pojemnosc. Gdy suma dlugosci nut ja
    przekracza, czesc materialu MUSI wypasc - chyba ze skrocimy nuty, tak jak
    robi to kazdy instrument monofoniczny grajacy akordy.

    Punktem odniesienia jest MEDIANA dlugosci nuty w tym utworze: nuta dluzsza
    od typowej blokuje glos bez muzycznego uzasadnienia. Solver pojemności
    dziala tylko jako bezpiecznik, gdyby mediana wciaz nie wystarczala.
    """
    # Budzet liczymy OSOBNO dla kazdej puli: akompaniament nie moze zjadac
    # pojemnosci zarezerwowanej dla leadu i odwrotnie.
    tonal = [note for note in notes if note['role'] in roles]

    if not tonal or not slots:
        return 0.0

    durations = [note['span'].duration for note in tonal]
    start = min(note['span'].start for note in tonal)
    end = max(note['span'].end for note in tonal)
    capacity = max(1e-6, end - start) * len(slots)

    if roles == frozenset({LEAD}) and sum(durations) <= capacity:
        return 0.0                       # nie skracamy rzadkiej linii leadu

    # Doswiadczalny zapas: glosy nigdy nie wypelniaja 100% czasu (artykulacja,
    # fragmentacja, nuty krotsze od limitu).
    budget = capacity * float(policy.get('capacitySafety', 1.6))
    cap = max(statistics.median(durations), MIN_NOTE_S)

    if sum(min(duration, cap) for duration in durations) > budget:
        cap = _solve_cap(durations, budget)

    return round(min(cap, max(durations)), 4)


def _source_notes(source: MidiSource, midi_analysis: MidiAnalysis, policy: dict) -> list[dict]:
    """Wszystkie nuty pliku z rola, w deterministycznej kolejnosci.

    W obrebie jednego uderzenia (ten sam start) najpierw dostaja urzadzenia
    nuty WAZNIEJSZE. Inaczej o tym, ktora z 8 rownoczesnych nut przezyje
    na 4 glosach, decydowalaby przypadkowa kolejnosc trackow.
    """
    result = []

    for track in source.tracks:
        for span in source.notes(track.index):
            note_id = f'{track.index}:{span.order}'
            role = midi_analysis.roles.get(note_id, HARMONY)
            result.append({
                'id': note_id, 'span': span, 'track': track.index,
                'track_name': track.name, 'role': role, 'order': span.order,
                'priority': _priority(role, span.velocity, span.duration, policy),
                'name': drum_name(span.note) if track.is_drums else note_name(span.note),
                'source_tracks': tuple(getattr(track, 'source_tracks', (track.index,))),
                'group_id': getattr(track, 'group_id', None),
                'duplicate_confidence': getattr(track, 'duplicate_confidence', None),
            })

    # W obrebie jednego uderzenia: najpierw wazniejsze role (lead, bas, perkusja),
    # a w tej samej roli NAJKROTSZE nuty pierwsze. To klasyczne SPT - maksymalizuje
    # liczbe zagranych nut, nie wypychajac przy tym melodii ani basu.
    result.sort(key=lambda item: (item['span'].start, _BAND[item['role']],
                                  item['span'].duration, item['track'], item['order']))

    return result


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


def _dropped(note: dict, outcome_reason: str, role: str,
             preferred: str | None, pin: ManualPin | None) -> PerformanceEvent:
    span: NoteSpan = note['span']

    return PerformanceEvent(
        id=note['id'], track=note['track'], track_name=note['track_name'],
        note=span.note, name=note['name'], velocity=span.velocity,
        channel=span.channel, start=span.start, duration=span.duration,
        device_id=None, device_type=None, played_note=None, played_hz=None,
        actual_start=span.start, actual_duration=0.0, outcome='DROPPED',
        role=role, preferred_device=preferred,
        rule_id=pin.rule_id if pin else None, reason=outcome_reason,
        source_tracks=note.get('source_tracks', ()),
        duplicate_group_id=note.get('group_id'),
        duplicate_confidence=note.get('duplicate_confidence'))


def _commit(slot: _Slot, events: list[PerformanceEvent], event: PerformanceEvent,
            start: float, duration: float) -> None:
    events.append(event)
    slot.event_index = len(events) - 1
    slot.busy_until = start + duration + slot.capability.retrigger_s
    slot.last_played = event.played_note


def _place(slot: _Slot, candidate: _Candidate, note: dict, outcome: str,
           actual_start: float, duration: float, role: str, pin: ManualPin | None,
           preferred: str, events: list[PerformanceEvent]) -> PerformanceEvent:
    span: NoteSpan = note['span']
    final = outcome

    if candidate.folded and outcome == 'ACCEPTED':
        final = 'FOLDED'

    event = PerformanceEvent(
        id=note['id'], track=note['track'], track_name=note['track_name'],
        note=span.note, name=note['name'], velocity=span.velocity,
        channel=span.channel, start=span.start, duration=span.duration,
        device_id=slot.device.id, device_type=slot.device.type,
        played_note=candidate.played, played_hz=candidate.hz,
        actual_start=actual_start, actual_duration=duration,
        outcome=final, role=role, preferred_device=preferred,
        articulation=pin.articulation if pin else None,
        rule_id=pin.rule_id if pin else None,
        source_tracks=note.get('source_tracks', ()),
        duplicate_group_id=note.get('group_id'),
        duplicate_confidence=note.get('duplicate_confidence'))
    _commit(slot, events, event, actual_start, duration)

    return event


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


def _duplicate_kpis(source, notes: list[dict], accompaniment_slots: list[_Slot],
                    report) -> dict:
    """Ile falszywej polifonii zniknelo i jak bardzo odciazylo to FDD."""
    tonal = [note for note in notes if note['role'] != PERCUSSION]

    if not tonal:
        return {}

    start = min(note['span'].start for note in tonal)
    end = max(note['span'].end for note in tonal)
    span = max(1e-6, end - start)
    capacity = span * max(1, len(accompaniment_slots))
    lead_tracks = {note['track'] for note in tonal if note['role'] == LEAD}
    logical_accompaniment = sum(note['span'].duration for note in tonal
                                if note['role'] != LEAD)
    lead_group: set[int] = set()

    for track in lead_tracks:
        group = report.group_of(track)
        lead_group |= set(group.tracks) if group is not None else {track}

    raw = getattr(source, 'source', None)
    raw_accompaniment = logical_accompaniment

    if raw is not None:
        raw_accompaniment = sum(
            span_.duration
            for track in raw.tracks
            if not track.is_drums and track.index not in lead_group
            for span_ in raw.notes(track.index))

    def clamp_demand(value: float) -> float:
        return value / capacity if capacity > 0 else 0.0

    return {
        'groupsFound': len(report.groups),
        'tracksCollapsed': report.collapsed_tracks,
        'rawTonalEvents': report.raw_tonal_events,
        'logicalTonalEvents': report.logical_tonal_events,
        'duplicateEventsCollapsed': report.events_removed,
        'accompanimentDemandSecondsBefore': round(raw_accompaniment, 1),
        'accompanimentDemandSecondsAfter': round(logical_accompaniment, 1),
        'demandCapacityBefore': round(clamp_demand(raw_accompaniment), 3),
        'demandCapacityAfter': round(clamp_demand(logical_accompaniment), 3),
        'capacitySeconds': round(capacity, 1),
        'groups': [group.as_dict() for group in report.groups],
        'pairs': [pair.as_dict() for pair in report.pairs],
    }


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


def _dvd_reinforcements(plan: PerformancePlan) -> list[ReinforcementEvent]:
    """Fill idle DVD intervals after normal allocation and articulation finish."""
    dvd = [device for device in plan.devices if device['type'] == 'DVD_SLED'
           and device.get('mode', 'virtual') in ('virtual', 'hybrid')
           and not device.get('mute', False)]
    if any(device.get('solo') and not device.get('mute') for device in plan.devices):
        dvd = [device for device in dvd if device.get('solo')]
    ids = {device['id'] for device in dvd}
    if len(ids) < 2:
        return []
    capabilities = capabilities_for([VirtualDeviceInstance.parse(device) for device in dvd])

    boundaries = []
    for event in plan.events:
        if event.played and event.device_id in ids and event.actual_duration > EPS:
            boundaries.append((event.actual_start, 1, event))
            boundaries.append((event.end, 0, event))
    boundaries.sort(key=lambda item: (item[0], item[1], item[2].id))
    active: dict[str, dict[str, PerformanceEvent]] = {device_id: {} for device_id in ids}
    result: list[ReinforcementEvent] = []
    previous: dict[tuple[str, str], int] = {}
    index = 0
    while index < len(boundaries):
        time = boundaries[index][0]
        while index < len(boundaries) and boundaries[index][0] == time:
            _, kind, event = boundaries[index]
            if kind == 0:
                active[event.device_id].pop(event.id, None)
            else:
                active[event.device_id][event.id] = event
            index += 1
        if index == len(boundaries):
            break
        end = boundaries[index][0]
        if end - time <= EPS:
            continue
        sources = [event for playing in active.values() for event in playing.values()]
        sources.sort(key=lambda event: (-_priority(event.role, event.velocity,
                                                   event.duration, plan.policy),
                                        -event.actual_duration, event.id))
        free = sorted(device_id for device_id in ids if not active[device_id])
        current: dict[tuple[str, str], int] = {}
        remaining = free[:]
        for source in sources:
            target = next((device_id for device_id in remaining
                           if source.played_hz is not None
                           and (capabilities[device_id].min_hz is None
                                or source.played_hz >= capabilities[device_id].min_hz)
                           and (capabilities[device_id].max_hz is None
                                or source.played_hz <= capabilities[device_id].max_hz)), None)
            if target is None:
                continue
            remaining.remove(target)
            key = (source.id, target)
            old = previous.get(key)
            if old is not None and abs(result[old].start + result[old].duration - time) <= EPS:
                result[old] = dataclasses.replace(result[old], duration=end - result[old].start)
                current[key] = old
            else:
                current[key] = len(result)
                result.append(ReinforcementEvent(source.id, target, time, end - time,
                                                 source.played_hz or 0.0, source.velocity))
        previous = current
    return result


def allocate(source: MidiSource, config: OrchestraConfig, *,
             midi_analysis: MidiAnalysis | None = None,
             pins: dict[str, ManualPin] | None = None,
             name: str | None = None,
             origin: str = 'auto') -> PerformancePlan:
    """Buduje plan wykonania. To samo wejscie zawsze daje ten sam plan."""
    policy = parse_policy(config.policy)
    devices, _ = config.allocation_devices()
    midi_analysis = midi_analysis or analysis_module.analyze(source)
    pins = pins or {}
    lead_slots, accompaniment_slots, percussion = _classify_slots(devices)
    events: list[PerformanceEvent] = []
    notes = _source_notes(source, midi_analysis, policy)

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
        tray_enabled=config.tray_enabled,
    )

    # Warstwa wykonawcza: sourceDuration -> performedDuration. Wirtualizacja
    # i sprzet czytaja pozniej dokladnie ten sam plan, wiec musza dostac
    # identyczna dlugosc wykonawcza.
    plan.articulation = apply_articulation(plan, capabilities_for(devices),
                                           params_from_policy(policy))

    if config.dvd_mode == 'reinforcement':
        plan.reinforcements = _dvd_reinforcements(plan)
    add_tray_reinforcement(plan)

    return plan
