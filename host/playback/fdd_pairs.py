"""Phrase-following FDD pairs, or two experimental four-drive unison groups.

Revoice the FDD pool after the Instrument Roles plan is complete.
Other actuators retain their allocated notes and reservations.
"""
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from itertools import permutations

from .capabilities import capabilities_for
from .hardware import bind_devices
from .hardware_profiles import HardwareDeviceState, HardwareNote, Verdict, evaluate, advance_state
from .instrument_roles import fdd_gate
from .mechanical_arrangement import _chronology
from .performance import ReinforcementEvent
from .tonal_articulation import resolve, retarget

PRESETS = ('instrument_roles_unison', 'instrument_roles_duet')
QUAD_PRESET = 'instrument_roles_unison4'
CHORD_WINDOW = .015  # Follow MIDI strums without moving either NOTE_ON.
PHRASE_LOOKAHEAD = .75
OWNER_PICKUP = .12


def enabled(policy):
    return policy.get('arrangementPreset') in PRESETS + (QUAD_PRESET,)


def arrange(plan, config, context, pins=None):
    from .allocator import _clip
    from .hardware_arranger import fold_for_profile

    pins = pins or {}
    quad = config.policy['arrangementPreset'] == QUAD_PRESET
    mode = 'unison4' if quad else 'unison' if config.policy['arrangementPreset'] == PRESETS[0] else 'duet'
    label = 'FDD 2×(4× unisono)' if quad else 'FDD pair '+mode
    plan.policy['arrangementPreset'] = config.policy['arrangementPreset']
    bound, _ = bind_devices(config.instances(), 2)
    available = plan.hardware['physicalLanes']
    if quad:
        # Stable physical groups: a missing drive never renumbers the remaining
        # lanes or moves FDD5-8 into the first voice.
        pairs = [tuple(bound[lane].id for lane in (f'fdd:{i}' for i in range(start, start+4))
                       if lane in bound and bound[lane].id in available) for start in (1, 5)]
    else:
        pairs = [tuple(bound[lane].id for lane in (f'fdd:{i}', f'fdd:{i+1}')
                       if lane in bound and bound[lane].id in available) for i in (1, 3)]
    devices = {d.id: d for d in bound.values()}
    profiles = {ident: context.profile_for(devices[ident], available[ident])
                for pair in pairs for ident in pair}
    caps = capabilities_for(config.instances())
    # A DVD/speaker copy can refer to an FDD source that this pass omits or
    # revoices. Preserve its already determined envelope/expression as well
    # as its physical reservation. The runtime retains these resolved keys.
    tonal, _ = resolve(plan)
    types = {d['id']: d['type'] for d in plan.devices}
    sources = {e.id: e for e in plan.events}
    plan.execution_articulation = {ident: asdict(art) for ident, art in tonal.items()
                                   if sources[ident].device_type != 'FDD'}
    retained = [e for e in plan.reinforcements if types[e.device_id] != 'FDD']
    for i, e in enumerate(retained):
        if e.source_id in tonal:
            plan.execution_articulation['extra:'+str(i)] = asdict(retarget(tonal[e.source_id],
                types[e.device_id], e.duration, e.velocity, e.start-sources[e.source_id].actual_start))
    candidates = [e for e in plan.events if e.id not in pins and not e.rule_id
                  and (e.role in ('bass', 'harmony') or quad and e.device_type == 'FDD')
                  and (e.device_type == 'FDD' or (not e.played and e.reason not in
                       ('MANUAL_DROP', 'UNPITCHED_EFFECT', 'NO_DEVICE')))]
    if quad and any(e.played and e.device_type == 'FDD' and (e.id in pins or e.rule_id) for e in plan.events):
        raise ValueError('4 FDD Unisono: usuń ręczne przypisania nut do FDD przed eksperymentem')
    candidate_ids = {e.id for e in candidates}
    # A static pitch/start index is equivalent to scanning every DVD event
    # for every candidate; prefix maxima also handle overlapping background.
    background = defaultdict(list)
    for event in plan.events:
        if event.played and event.device_type == 'DVD_SLED':
            background[event.note].append((event.actual_start, event.end))
    coverage = {}
    for pitch, intervals in background.items():
        intervals.sort()
        starts, ends = [], []
        for start, end in intervals:
            starts.append(start)
            ends.append(max(end, ends[-1] if ends else end))
        coverage[pitch] = starts, ends
    covered = {}
    for event in candidates:
        starts, ends = coverage.get(event.note, ([], []))
        index = bisect_right(starts, event.start+1e-9)-1
        covered[event.id] = index >= 0 and ends[index] >= event.start+event.duration-1e-9
    # Manual/lead notes retain their exact reservations, even inside a pair.
    fixed = {ident: [e for e in plan.events if e.played and e.device_id == ident
                     and e.id not in candidate_ids] for ident in profiles}
    accepted = {ident: [] for ident in profiles}
    # Quad candidates are chronological and have no fixed FDD reservations.
    # Preserve exactly the state a full chronology replay would produce.
    if quad:
        assert not any(fixed.values())
    accepted_states = {ident: HardwareDeviceState() for ident in profiles}
    pending_evaluations = {}
    extras = []
    replacements = {}
    owners = [None for _ in pairs]
    changes = Counter()
    last_pitch = {}
    attacks = defaultdict(list)
    for e in candidates:
        attacks[e.track, e.channel].append(e.start)
    for part in attacks:
        attacks[part] = sorted(set(attacks[part]))
    groups = []
    for e in sorted(candidates, key=lambda e: (e.start, e.track, e.channel, e.id)):
        if not groups or e.start > groups[-1][0].start+CHORD_WINDOW:
            groups.append([])
        groups[-1].append(e)

    def part(e):
        return e.track, e.channel

    def playable(event, ident):
        profile = profiles[ident]
        low, high = profile.get('musicalHz')
        low, high = max(low, caps[ident].min_hz), min(high, caps[ident].max_hz)
        step_us = profile.get('executionMinStepUs') or profile.get('datasheetMinStepMs')*1000
        high = min(high, 1e6/step_us)
        fold = fold_for_profile(event.note+devices[ident].transpose, low, high,
                                plan.policy['foldMode'], profile)
        if not fold.in_range:
            return None
        duration = fdd_gate(_clip(event.duration, caps[ident].min_note_s, plan.policy), covered[event.id])
        times = attacks[part(event)]
        following = bisect_right(times, event.start+CHORD_WINDOW)
        if following < len(times):
            # Overlapping source gates must not hide the next riff attack.
            # Keep a short physical release and the existing minimum gate.
            duration = min(duration, max(caps[ident].min_note_s,
                                        times[following]-event.start-.003))
        return replace(event, device_id=ident, device_type='FDD',
                       played_note=fold.midi_note+12*fold.octave_shift, played_hz=fold.hz,
                       actual_start=event.start, actual_duration=duration,
                       outcome='ACCEPTED', preferred_device=ident, sustain_added=0.,
                       reason=label)

    def feasible(notes):
        pending_evaluations.clear()
        for ident, note in notes.items():
            if quad:
                physical_note = HardwareNote(note.played_hz, note.actual_duration, note.actual_start)
                ev = evaluate(profiles[ident], physical_note, accepted_states[ident])
                if (not ev.authorized or Verdict.BLOCKED in (ev.timing, ev.quality, ev.physical_load)
                        or ev.ready_at > note.actual_start+1e-8):
                    return False
                pending_evaluations[ident] = ev
            elif _chronology(profiles[ident], fixed[ident]+accepted[ident]+[note], []) is None:
                return False
        return True

    def choose(pair_index, events):
        pair = pairs[pair_index]
        if not pair:
            return None
        # Prefer the previous melodic pitch, then velocity and source ID.
        previous = last_pitch.get(pair_index)
        ordered = sorted(events, key=lambda e: (
            abs(e.note-previous) if previous is not None else 0,
            -e.velocity, e.note, e.id))
        if mode == 'duet' and len(pair) == 2:
            options = []
            for a, b in permutations(ordered, 2):
                if a.note == b.note:
                    continue
                left, right = playable(a, pair[0]), playable(b, pair[1])
                if left and right and left.played_note != right.played_note:
                    # Voice leading first; a wide pair retains chord identity.
                    cost = (abs(a.note-previous) if previous is not None else 0,
                            -(a.velocity+b.velocity), -abs(a.note-b.note), a.id, b.id)
                    options.append((cost, {pair[0]: left, pair[1]: right}))
            for _, notes in sorted(options, key=lambda option: option[0]):
                if feasible(notes):
                    return notes
        # Single-line fallback is exact unison, never an invented chord tone.
        for e in ordered:
            notes = {ident: playable(e, ident) for ident in pair}
            if any(n is None for n in notes.values()):
                continue
            if len({n.played_hz for n in notes.values()}) != 1:
                continue
            if quad and len({(n.actual_start, n.actual_duration) for n in notes.values()}) != 1:
                continue
            if feasible(notes):
                return notes
        return None

    for group in groups:
        now = group[0].start
        by_part = defaultdict(list)
        for e in group:
            by_part[part(e)].append(e)
        # An occupied pair keeps its part until both physical reservations end.
        occupied = {i for i, pair in enumerate(pairs) if any(
            e.actual_start <= now+CHORD_WINDOW and e.end > now+1e-9
            for ident in pair for e in fixed[ident]+accepted[ident])}
        represented = {owners[i] for i in occupied if owners[i] is not None}
        # Existing owners get first refusal, avoiding swaps when both attack.
        order = sorted(range(len(pairs)), key=lambda i: (owners[i] not in by_part, i))
        for i in order:
            if i in occupied or not pairs[i]:
                continue
            owner = owners[i]
            times = attacks.get(owner, [])
            future = bisect_left(times, now)
            pickup = (owner not in by_part and future < len(times)
                      and times[future]-now <= OWNER_PICKUP)
            if pickup:
                # Preserve an imminent pickup rather than switching for a
                # single intervening attack from another instrument.
                continue
            def rank(key):
                times = attacks[key]
                activity = bisect_right(times, now+PHRASE_LOOKAHEAD)-bisect_left(times, now)
                return (key != owner, -activity,
                        -max(e.velocity for e in by_part[key]), key)
            for key in sorted((k for k in by_part if k not in represented), key=rank):
                notes = choose(i, by_part[key])
                if notes is None:
                    continue
                represented.add(key)
                changes[i] += int(owner is not None and owner != key)
                owners[i] = key
                last_pitch[i] = notes[pairs[i][0]].note
                primary_ids = set()
                for ident, note in notes.items():
                    ev = (pending_evaluations[ident] if quad else
                          _chronology(profiles[ident], fixed[ident]+accepted[ident]+[note], [])[note.id])
                    if quad:
                        advance_state(accepted_states[ident], profiles[ident],
                                      HardwareNote(note.played_hz, note.actual_duration, note.actual_start), ev)
                    note = replace(note, hardware={**ev.as_dict(), 'lane': available[ident],
                        'selection': {'reason': label, 'pair': i+1,
                                      'part': list(key), 'sourceMidiNote': note.note}})
                    accepted[ident].append(note)
                    if note.id not in primary_ids:
                        replacements[note.id] = note
                        primary_ids.add(note.id)
                    else:
                        primary = replacements[note.id]
                        extras.append(ReinforcementEvent(note.id, ident, note.actual_start,
                            note.actual_duration, note.played_hz, note.velocity,
                            kind='FDD_UNISON4' if quad else 'FDD_PAIR_UNISON', source_device=primary.device_id,
                            reason=label+': same MIDI note and attack',
                            semantic_compatibility='same source part / exact unison', role=note.role))
                break

    for e in candidates:
        if e.id not in replacements:
            replacements[e.id] = replace(e, device_id=None, device_type=None,
                played_note=None, played_hz=None, actual_start=e.start, actual_duration=0.,
                sustain_added=0., outcome='DROPPED', reason='FDD_UNISON4_CAPACITY' if quad else 'FDD_PAIR_CAPACITY')
    plan.events = sorted([replacements.get(e.id, e) for e in plan.events],
                         key=lambda e: (e.actual_start, e.track, e.id))
    # Pair reservations replace optional FDD copies; other actuator copies stay.
    plan.reinforcements = retained+extras
    for ident in profiles:
        assert _chronology(profiles[ident], fixed[ident]+accepted[ident], []) is not None
        counter = plan.hardware['counters'][ident]
        counter.update({key: 0 for key in counter if key != 'dropReasons'})
        counter['requestedNotes'] = len(candidates)+len(fixed[ident])
        counter['dropReasons'] = {}
        state = HardwareDeviceState()
        for e in sorted(fixed[ident]+accepted[ident], key=lambda e: (e.actual_start, e.id)):
            note = HardwareNote(e.played_hz, e.actual_duration, e.actual_start)
            ev = evaluate(profiles[ident], note, state)
            counter['acceptedNotes'] += 1
            counter['playedNotes'] += 1
            counter['degradedNotes'] += int(ev.quality != Verdict.PASS or ev.timing != Verdict.PASS)
            counter['transitions'] += int(ev.transition_time > 0)
            counter['physicalUnknown'] += int(ev.physical_load == Verdict.UNKNOWN)
            for key, reason in [('tooShort', 'NOTE_TOO_SHORT'),
                                ('outsidePreferredRange', 'OUTSIDE_PREFERRED_RANGE'),
                                ('outsideStableRange', 'OUTSIDE_STABLE_RANGE')]:
                counter[key] += int(reason in ev.quality_reasons)
            before = state.travel_reversals
            advance_state(state, profiles[ident], note, ev)
            counter['travelReversals'] += state.travel_reversals-before
            counter['reversals'] += state.travel_reversals-before
        counter['droppedNotes'] = max(0, counter['requestedNotes']-counter['acceptedNotes'])
        if counter['droppedNotes']:
            counter['dropReasons']['FDD_PAIR_NOT_SELECTED'] = counter['droppedNotes']
        plan.hardware['states'][ident] = state.as_dict()
    plan.hardware['fddPairs'] = {'mode': mode, 'pairs': [list(p) for p in pairs],
        'partChanges': {str(i+1): changes[i] for i in range(len(pairs))},
        'primaryNotes': sum(e.played for e in replacements.values()),
        'unisonCopies': len(extras),
        'notSelected': sum(not e.played for e in replacements.values()),
        'scope': 'two independent parts on FDD1-4 and FDD5-8; planned, not measured' if quad else 'two accompaniment parts; original MIDI pitches only; planned, not measured'}
    if quad:
        plan.hardware['fddUnison4'] = dict(plan.hardware['fddPairs'],
                                           groups=[list(pair) for pair in pairs])
    return plan


def synchronize_unison4(plan, registry):
    """Keep whole unison groups after per-lane attack/physical vetoes.

    Another lane's calibration must never leave a partial four-drive attack.
    Preserve non-FDD sidecars and reservations even if their source is dropped.
    """
    if plan.policy.get('arrangementPreset') != QUAD_PRESET:
        return
    report = plan.hardware.get('fddUnison4')
    if report is None:  # STRICT_TRACKS deliberately bypasses AUTO presets.
        return
    member_groups = [members for members in report.get('groups', [report.get('devices', [])])
                     if members]
    if not member_groups:
        return
    types = {d['id']: d['type'] for d in plan.devices}
    sources = {e.id: e for e in plan.events}
    notes_by_source = defaultdict(list)
    for e in plan.events:
        if e.played and e.device_type == 'FDD':
            notes_by_source[e.id].append((e.device_id, e.actual_start, e.actual_duration, e.played_hz))
    for e in plan.reinforcements:
        if types[e.device_id] == 'FDD':
            notes_by_source[e.source_id].append((e.device_id, e.start, e.duration, e.hz))
    device_group = {ident: index for index, members in enumerate(member_groups) for ident in members}
    states = {ident: HardwareDeviceState() for members in member_groups for ident in members}
    kept = {}
    kept_group = {}
    for source_id, notes in sorted(notes_by_source.items(), key=lambda x: (min(n[1] for n in x[1]), x[0])):
        indexes = {device_group.get(note[0]) for note in notes}
        if len(indexes) != 1 or None in indexes:
            continue
        group_index = indexes.pop()
        members = member_groups[group_index]
        if (len(notes) != len(members) or {n[0] for n in notes} != set(members)
                or len({(n[1], n[3]) for n in notes}) != 1
                or not sources[source_id].played):
            continue
        start, hz = notes[0][1], notes[0][3]
        duration = min(n[2] for n in notes)
        note = HardwareNote(hz, duration, start)
        evaluations = {ident: evaluate(registry.profile(ident), note, states[ident]) for ident in members}
        if any(not ev.authorized or ev.ready_at > start+1e-8
               or Verdict.BLOCKED in (ev.timing, ev.quality, ev.physical_load) for ev in evaluations.values()):
            continue
        kept[source_id] = duration
        kept_group[source_id] = group_index
        for ident, ev in evaluations.items():
            advance_state(states[ident], registry.profile(ident), note, ev)
    plan.events = [replace(e, actual_duration=kept[e.id]) if e.id in kept else
                   replace(e, device_id=None, device_type=None, actual_duration=0.,
                           sustain_added=0., outcome='DROPPED', reason='FDD_UNISON4_SYNC')
                   if e.id in notes_by_source and e.played and e.device_type == 'FDD' else e for e in plan.events]
    articulation = {k: v for k, v in plan.execution_articulation.items() if not k.startswith('extra:')}
    for source_id in notes_by_source:
        if source_id not in kept:
            articulation.pop(source_id, None)
        elif source_id in articulation:
            articulation[source_id] = {**articulation[source_id], 'gate': kept[source_id]}
    extras = []
    for i, extra in enumerate(plan.reinforcements):
        is_fdd = types[extra.device_id] == 'FDD'
        if is_fdd and extra.source_id not in kept:
            continue
        if is_fdd:
            extra = replace(extra, duration=kept[extra.source_id])
        art = plan.execution_articulation.get('extra:'+str(i))
        if art is not None:
            articulation['extra:'+str(len(extras))] = {**art, 'gate': extra.duration} if is_fdd else art
        extras.append(extra)
    plan.reinforcements = extras
    plan.execution_articulation = articulation
    for ident, state in states.items():
        plan.hardware['states'][ident] = state.as_dict()
        index = device_group[ident]
        plan.hardware['counters'][ident]['playedNotes'] = sum(
            group_index == index for group_index in kept_group.values())
    report.update(executedNotes=len(kept),
                  unisonCopies=sum(len(member_groups[index])-1
                                   for index in kept_group.values()),
                  synchronizedVetoes=len(notes_by_source)-len(kept))
