"""Phrase reorchestration for FDD; source pitches/onsets, fewer motor starts.

Only the final Expressive FDD pool is rewritten. Other instruments and their
sidecars are frozen. Constants below are musical experiments, not calibration.
"""
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import replace

from .capabilities import capabilities_for
from .hardware_arranger import fold_for_profile
from .hardware_profiles import HardwareDeviceState, HardwareNote, Verdict, evaluate, advance_state, min_note_ms
from .performance import ReinforcementEvent

PRESET = 'fdd_legato'
EPS = 1e-9
MIN_DWELL = .140
MAX_DWELL = .220
MIN_BRIDGE = .180
MAX_BRIDGE = .450
ROLE = {'lead': 0, 'bass': 1, 'harmony': 2}
REINFORCEMENT = 'FDD_LEGATO_REINFORCEMENT'


class Clock:
    def __init__(self, source):
        raw = getattr(source, 'source', source)
        self.segments = raw.tempo._segments
        self.times = [s.seconds for s in self.segments]
        self.ticks = raw.ticks_per_beat

    def beat(self, time):
        return self.segments[max(0, bisect_right(self.times, time)-1)].tempo/1e6

    def accent(self, event):
        segment = self.segments[max(0, bisect_right(self.times, event.start)-1)]
        beat_position = segment.tick/self.ticks+(event.start-segment.seconds)/(segment.tempo/1e6)
        return abs(beat_position-round(beat_position)) < .08

    def bridge(self, time):
        return max(MIN_BRIDGE, min(MAX_BRIDGE, self.beat(time)*.9))


def phrases(events, clock):
    """Keep a part through short interleaved ornaments; never join other parts."""
    by_part = defaultdict(list)
    for event in events:
        by_part[event.track, event.channel].append(event.start)
    result, current = [], []
    source_end = 0.
    ignored = set()
    for event in events:
        part = event.track, event.channel
        owner = (current[-1].track, current[-1].channel) if current else None
        continuous = current and event.start-source_end <= clock.bridge(event.start)+EPS
        if current and part != owner:
            times = by_part[owner]
            index = bisect_right(times, event.start+EPS)
            pickup = (index < len(times) and times[index]-source_end <= clock.bridge(event.start)+EPS
                      and times[index]-event.start <= clock.bridge(event.start)+EPS)
            held = source_end >= event.start-EPS
            higher_role = ROLE.get(event.role, 2) < ROLE.get(current[-1].role, 2)
            if (pickup or held) and not higher_role:
                ignored.add(event.id)
                continue
            continuous = False
        if not continuous and current:
            result.append((current, event.start))
            current = []
        current.append(event)
        # A later selected source voice replaces an earlier held chord member.
        # Its NOTE_OFF, not the longest historical gate, defines the next rest.
        source_end = event.start+event.duration
    if current:
        result.append((current, float('inf')))
    return result, ignored


def select(events, dwell, clock, end, articulation=None):
    """Maximum-salience source subsequence with a minimum pitch residence time.

    Keep the phrase entry. Same performed-pitch repetitions can share a body;
    beat accents and velocity guide the reduction of intervening fast notes.
    """
    # Adaptive selection keeps later repeats available: the first return to a
    # pitch can be infeasible while a subsequent attack fits the residence.
    runs = []
    for event in events:
        if articulation is not None or not runs or abs(event.played_hz-runs[-1].played_hz) > 1e-6:
            runs.append(event)
    first = runs[0]
    if first.start+dwell(first) > end+EPS:
        return []
    candidates = sorted([e for e in runs[1:] if e.start >= first.start+dwell(first)-EPS
                         and e.start+dwell(e) <= end+EPS],
                        key=lambda e: (e.start+dwell(e), e.start, e.id))
    ends = [e.start+dwell(e) for e in candidates]
    scores, take, previous = [0.], [], []
    for index, event in enumerate(candidates):
        before = bisect_right(ends, event.start+EPS, 0, index)
        weight = 1.+event.velocity/127.+(2. if clock.accent(event) else 0.)
        value = scores[before]+weight
        chosen = value > scores[-1]+EPS
        scores.append(value if chosen else scores[-1])
        take.append(chosen)
        previous.append(before)
    selected = []
    index = len(candidates)
    while index:
        if take[index-1]:
            selected.append(candidates[index-1])
            index = previous[index-1]
        else:
            index -= 1
    selected = [first]+list(reversed(selected))
    # A skipped excursion may bring two selected tones back to the same pitch.
    return [e for i, e in enumerate(selected) if not i or abs(e.played_hz-selected[i-1].played_hz)>1e-6
            or articulation is not None and (articulation.is_protected(e) or articulation.is_protected(selected[i-1]))]


def strong_windows(pool, clock):
    """Source attacks, including repetitions later held by legato, drive dynamics.

    A beat needs three attacks from at least two logical voices, velocity >=80,
    and a metrical accent (or >=100 velocity). Keep the body for two beats,
    merging adjacent accents rather than starting/stopping a drive every beat.
    These are musical heuristics, not measured actuator limits.
    """
    attacks = sorted((e.start, group, e.id, e) for group, events in pool.items() for e in events)
    times = [a[0] for a in attacks]
    windows = []
    for time, group, ident, event in attacks:
        beat = clock.beat(time)
        # Include simultaneous/strummed attacks, never move the actual entry.
        local = attacks[bisect_left(times, time-beat+EPS):bisect_right(times, time+.015)]
        if (len(local) < 3 or len({a[1] for a in local}) < 2
                or event.velocity < 80 or not (clock.accent(event) or event.velocity >= 100)):
            continue
        end = time+2*beat
        if windows and time <= windows[-1][1]+EPS:
            windows[-1] = windows[-1][0], max(windows[-1][1], end)
        else:
            windows.append((time, end))
    return windows


def reinforce(plan, registry, pool, clock):
    """Double strong phrase bodies on spare pair members, protecting all primaries.

    Follow the existing performed pitch, including mid-note entries on a source
    accent. Copies never fill source rests or delay/take time from another voice.
    Complete future travel and attack spacing are checked before committing a
    block; an optional failure only removes the block, never a primary note.
    """
    from .mechanical_arrangement import ChronologyCache

    report = {'blocks': 0, 'tones': 0, 'seconds': 0., 'rejected': {}, 'primaryDropsAdded': 0}
    plan.hardware['fddLegato']['reinforcement'] = report
    # Expressive disables the older generic unison pass internally; respect
    # the user's configuration, not that allocator implementation flag.
    policy = registry.configuration().policy
    if not policy['fddUnisonEnabled'] or policy['fddUnisonMaxVoices'] < 2:
        return
    windows = strong_windows(pool, clock)
    report['strongWindows'] = len(windows)
    groups = plan.hardware['fddExpressive']['groups']
    primary = defaultdict(list)
    runs = defaultdict(list)
    for event in plan.events:
        if event.played and event.device_type == 'FDD':
            primary[event.device_id].append(event)
    for ident, events in primary.items():
        for event in sorted(events, key=lambda e: (e.actual_start, e.id)):
            lane = runs[ident]
            if not lane or abs(lane[-1][-1].end-event.actual_start) > EPS:
                lane.append([])
            lane[-1].append(event)
    interval = plan.policy['fddMinAttackIntervalMs']/1000.
    release = max(.003, plan.policy['releaseGapMs']/1000.)
    rejected = Counter()
    for group in groups:
        for source_device in group:
            for target in (d for d in group if d != source_device):
                profile = registry.profile(target)
                chronology = ChronologyCache(profile)
                extras = [e for e in plan.reinforcements if e.device_id == target]
                baseline = chronology.check(primary[target], extras)
                if baseline is None:
                    raise ValueError('FDD Legato: invalid primary chronology '+target)
                baseline = {e.id: baseline[e.id].score for e in primary[target]}
                # Reserve future primary gates before spending any spare time.
                reserved = sorted([(e.actual_start, e.end) for e in primary[target]]+
                                  [(e.start, e.start+e.duration) for e in extras])
                free, cursor = [], 0.
                for start, end in reserved:
                    if start-release > cursor+EPS:
                        free.append((cursor, start-release))
                    cursor = max(cursor, end+release)
                free.append((cursor, float('inf')))
                for run in runs[source_device]:
                    for a, b in windows:
                        if b <= run[0].actual_start or a >= run[-1].end:
                            continue
                        for left, right in free:
                            start, end = max(a, left, run[0].actual_start), min(b, right, run[-1].end)
                            if end-start < max(.350, clock.beat(start))-EPS:
                                continue
                            copies = []
                            for event in run:
                                at, stop = max(start, event.actual_start), min(end, event.end)
                                if stop <= at+EPS:
                                    continue
                                dwell = max(interval, MIN_DWELL,
                                    min(MAX_DWELL, clock.beat(at)*.5),
                                    (min_note_ms(profile, event.played_hz) or 0)/1000.)
                                if stop-at < dwell-EPS:
                                    if not copies:
                                        continue  # Enter at the next existing pitch change.
                                    break  # Do not append a tiny final click.
                                copies.append(ReinforcementEvent(event.id, target, at, stop-at,
                                    event.played_hz, event.velocity, kind=REINFORCEMENT,
                                    source_device=source_device, reason='strong FDD legato phrase body',
                                    semantic_compatibility='same performed pitch trajectory; spare pair member',
                                    role=event.role))
                            if not copies or copies[-1].start+copies[-1].duration-copies[0].start < max(.350, clock.beat(copies[0].start))-EPS:
                                continue
                            attacks = sorted([e.actual_start for e in primary[target]]+
                                             [e.start for e in extras+copies])
                            if any(y-x < interval-EPS for x, y in zip(attacks, attacks[1:])):
                                rejected['attackSpacing'] += 1
                                continue
                            evaluation = chronology.check(primary[target], extras+copies)
                            if evaluation is None or any(evaluation[k].score+EPS < score for k, score in baseline.items()):
                                rejected['physicalVeto'] += 1
                                continue
                            for extra in copies:
                                plan.execution_articulation['extra:'+str(len(plan.reinforcements))] = {
                                    'kind':'fdd_legato', 'gate':extra.duration, 'legato':True,
                                    'frequency':{'times':(0.,), 'values':(extra.hz,)}}
                                plan.reinforcements.append(extra)
                            extras += copies
                            report['blocks'] += 1
                            report['tones'] += len(copies)
                            report['seconds'] += sum(e.duration for e in copies)
    report.update(seconds=round(report['seconds'], 3), rejected=dict(rejected))


def apply(plan, registry, source, adaptive=False):
    if 'fddExpressive' not in plan.hardware:  # STRICT_TRACKS is deliberately unchanged.
        return
    clock = Clock(source)
    config = registry.configuration()
    devices = {d.id: d for d in config.instances()}
    caps = capabilities_for(list(devices.values()))
    groups = plan.hardware['fddExpressive']['groups']
    group_for = {ident: i for i, group in enumerate(groups) for ident in group}
    pool = defaultdict(list)
    for event in plan.events:
        if event.played and event.device_type == 'FDD':
            pool[group_for[event.device_id]].append(event)
    from .adaptive_legato import Articulation
    articulation = Articulation(pool, clock) if adaptive else None
    states = {ident: HardwareDeviceState() for ident in group_for}
    load = Counter()
    replacements, sidecars, decisions = {}, {}, {}
    reasons = Counter()
    owners, part_changes = {}, Counter()
    phrase_count = 0
    release = max(.003, plan.policy['releaseGapMs']/1000.)
    for group_index, events in sorted(pool.items()):
        events.sort(key=lambda e: (e.start, e.id))
        chunks, ignored = phrases(events, clock)
        for ident in ignored:
            decisions[ident] = 'FDD_LEGATO_PART_CONTINUITY'
        for sequence, boundary in chunks:
            phrase_count += 1
            end = boundary-release
            selected = []
            physical_veto = False
            for ident in sorted(groups[group_index], key=lambda d: (load[d], d)):
                profile, cap, device = registry.profile(ident), caps[ident], devices[ident]
                mapped = []
                for event in sequence:
                    low, high = profile.get('musicalHz')
                    folded = fold_for_profile(event.note+device.transpose, max(low, cap.min_hz),
                                              min(high, cap.max_hz), plan.policy['foldMode'], profile)
                    if not folded.in_range:
                        break
                    mapped.append(replace(event, device_id=ident, preferred_device=ident,
                        played_note=folded.midi_note+12*folded.octave_shift, played_hz=folded.hz))
                if len(mapped) != len(sequence):
                    physical_veto = True
                    continue
                def dwell(e):
                    return max(plan.policy['fddMinAttackIntervalMs']/1000.,
                        (min_note_ms(profile, e.played_hz) or 0)/1000.,
                        max(MIN_DWELL, min(MAX_DWELL, clock.beat(e.start)*.5)))
                def residence(e):
                    return dwell(e)+(max(release, articulation.gap(e))
                        if articulation and articulation.is_protected(e) else 0.)
                chosen = select(mapped, residence, clock, end, articulation)
                if not chosen:
                    continue
                state = replace(states[ident], hit_times=list(states[ident].hit_times))
                candidate = []
                tail = sequence[-1].start+sequence[-1].duration
                for index, event in enumerate(chosen):
                    stop = chosen[index+1].start if index+1 < len(chosen) else min(end,max(tail,event.start+dwell(event)))
                    if articulation and articulation.is_protected(event):
                        if index+1 < len(chosen):
                            stop -= max(release, articulation.gap(event))
                        stop = min(stop, event.start+max(event.duration, dwell(event)))
                    # The backbone derives an AUTO cap for allocating short
                    # source attacks. Phrase bodies honor only an explicit cap.
                    limit = config.policy.get('leadMaxNoteSeconds' if event.role=='lead' else 'maxNoteSeconds', 0)
                    if limit:
                        stop = min(stop, event.start+limit)
                    duration = stop-event.start
                    if duration < dwell(event)-EPS:
                        break
                    note = HardwareNote(event.played_hz, duration, event.start)
                    ev = evaluate(profile, note, state)
                    if (not ev.authorized or Verdict.BLOCKED in (ev.timing,ev.quality,ev.physical_load)
                            or ev.ready_at > event.start+1e-8
                            or state.last_event_time is not None and event.start-state.last_event_time < plan.policy['fddMinAttackIntervalMs']/1000.-EPS):
                        break
                    event = replace(event, actual_start=event.start, actual_duration=duration,
                        sustain_added=max(0.,duration-event.duration), outcome='ACCEPTED', reason='FDD phrase legato',
                        hardware={**ev.as_dict(), 'lane':registry.by_id[ident]['lane'],
                            'selection':{**event.hardware.get('selection',{}),'reason':'FDD phrase legato',
                                         'legatoPhrase':phrase_count,'part':[event.track,event.channel]}})
                    candidate.append(event)
                    advance_state(state,profile,note,ev)
                if len(candidate) != len(chosen):
                    physical_veto = True
                    continue
                selected = candidate
                states[ident] = state
                load[ident] += sum(e.actual_duration for e in selected)
                break
            if selected:
                part = selected[0].track, selected[0].channel
                part_changes[group_index] += int(group_index in owners and owners[group_index] != part)
                owners[group_index] = part
            for event in selected:
                replacements[event.id] = event
                sidecars[event.id] = {**plan.execution_articulation.get(event.id,{}),
                    'kind':'fdd_legato','gate':event.actual_duration,'legato':True,
                    'frequency':{'times':(0.,),'values':(event.played_hz,)}}
            for event in sequence:
                if event.id not in replacements:
                    previous = next((e for e in reversed(selected) if e.start <= event.start+EPS
                                     and e.end >= event.start-EPS and abs(e.played_hz-event.played_hz)<1e-6), None)
                    decisions[event.id] = ('FDD_LEGATO_REPEAT_HELD' if previous else
                        'FDD_LEGATO_REDUCTION' if selected else
                        'FDD_LEGATO_PHYSICAL_VETO' if physical_veto else 'FDD_LEGATO_NO_TONE_ROOM')
    for events in pool.values():
        for event in events:
            if event.id not in replacements:
                reason = decisions[event.id]
                reasons[reason] += 1
                replacements[event.id] = replace(event, device_id=None, device_type=None,
                    played_note=None, played_hz=None, actual_duration=0., actual_start=event.start,
                    sustain_added=0., outcome='DROPPED', reason=reason)
    plan.events = sorted([replacements.get(e.id,e) for e in plan.events], key=lambda e:(e.actual_start,e.track,e.id))
    for ident in replacements:
        plan.execution_articulation.pop(ident,None)
    plan.execution_articulation.update(sidecars)
    plan.hardware['fddLegato'] = {'version':2,'phrases':phrase_count,'baselineNotes':sum(map(len,pool.values())),
        'selectedNotes':len(sidecars),'reductions':dict(reasons),
        'dwellRangeMs':[MIN_DWELL*1000,MAX_DWELL*1000],
        'bridgeRangeMs':[MIN_BRIDGE*1000,MAX_BRIDGE*1000],
        'nonFddPreserved':True,'scope':'experimental phrase reorchestration; not acoustic or thermal calibration'}
    if articulation:
        plan.hardware['adaptiveLegato'] = articulation.report()
        plan.hardware['adaptiveLegato'].update(
            protectedAttacksRetained=sum(e.id in articulation.protected for e in replacements.values() if e.played),
            selectedSourceAttacks=len(sidecars))
    reinforce(plan, registry, pool, clock)
    # Refresh final FDD counters/states and validate the complete changed travel.
    from .fdd_expression import without_accents
    without_accents(plan,registry)
    plan.hardware['fddExpressive']['allocationPreserved'] = False
    pairs = plan.hardware['fddPairs']
    pairs.update(mode='phrase_legato',primaryNotes=len(sidecars),
        notSelected=pairs['notSelected']+sum(reasons.values()),
        baselinePartChanges=pairs.get('partChanges',{}),
        partChanges={str(i+1):part_changes[i] for i in range(len(groups))},
        scope='four stable phrase voices; spare pair members reinforce strong bodies; acoustic result unmeasured')
