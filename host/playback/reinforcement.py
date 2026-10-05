"""One acoustic post-plan pass, with tonal / strike / tray compatibility policies.

PRIMARY events are immutable. Reservations use performed intervals (after FDD
sustain), never source MIDI durations. No serial commands are emitted here.
"""
from __future__ import annotations

import bisect
import dataclasses
from collections import Counter, defaultdict

from .capabilities import capabilities_for
from .performance import PerformancePlan, ReinforcementEvent
from .orchestra import parse_idle
from .virtual import VirtualDeviceInstance, effective_profile
from .tray import add_reinforcement as tray_accents

EPS = 1e-9
REJECTIONS = ('deviceBusy', 'deviceNeededSoon', 'incompatibleRole', 'outOfRange',
              'cooldown', 'maxCopiesReached', 'scoreTooLow', 'fragmentTooShort')


def _union(intervals):
    end = float('-inf')
    total = 0.0
    for start, stop in sorted(intervals):
        if stop > end:
            total += stop - max(start, end)
            end = stop
    return total


def _identity(plan, event):
    item = next((t for t in plan.analysis.get('trackClassification', []) if t['index'] == event.track), {})
    programs = plan.analysis.get('trackPrograms', {}).get(str(event.track), [])
    if event.role == 'percussion' and event.channel == 9:
        return 'PERCUSSION', 'GM percussion', event.note
    return item.get('finalRole', event.role.upper()), item.get('gmFamily'), Counter(programs).most_common(1)[0][0] if programs else None


def _compatible(source, target, capability, identity, affinity):
    role, family, program = identity
    if target.type == 'VHS':
        if source.role != 'lead' or role not in ('VOCAL', 'LEAD', 'LEAD_VOCAL', 'LEAD_MELODY'):
            return 'incompatibleRole', 0, ''
    elif source.role not in ('harmony', 'bass'):
        return 'incompatibleRole', 0, ''
    hz = source.played_hz
    profile = effective_profile(target)
    low = profile.get('preferredMinHz') or capability.min_hz
    high = profile.get('preferredMaxHz') or capability.max_hz
    if hz is None or (low is not None and hz < low) or (high is not None and hz > high):
        return 'outOfRange', 0, ''
    # Unknown DVD range is accepted for ordinary accompaniment, never bass.
    if source.role == 'bass' and not capability.has_range:
        return 'outOfRange', 0, ''
    if not affinity:
        return None, 20, 'generic compatible accompaniment' if target.type != 'VHS' else 'lead-only'
    track, other_role, other_family, other_program = affinity
    if track == source.track:
        return None, 60, 'same source track'
    if other_role == role:
        if role in ('OTHER', 'UNKNOWN', 'HARMONY') and family is not None and other_family is not None and family != other_family:
            return 'incompatibleRole', 0, ''
        bonus = 15 if role in ('OTHER', 'UNKNOWN') else 30
        reason = 'same semantic role'
    elif {other_role, role} <= {'STRINGS', 'PAD_SYNTH', 'BACKING_VOCAL'}:
        bonus, reason = 20, 'related strings/pad/backing role'
    else:
        return 'incompatibleRole', 0, ''
    if program is not None and program == other_program:
        bonus += 20
        reason += '; same GM instrument'
    elif family is not None and family == other_family:
        bonus += 12
        reason += '; same GM family'
    return None, bonus, reason


def apply_reinforcement(plan, priority):
    """Single entry point; disabled mode preserves the previous DVD/tray policy."""
    config = parse_idle(plan.idle_reinforcement)
    if not config['enabled']:
        plan.reinforcements = legacy_dvd(plan, priority) if plan.dvd_mode == 'reinforcement' else []
        tray_accents(plan)
        plan.idle_report = {'enabled': False}
        return
    plan.reinforcements = []
    rejects = Counter({key: 0 for key in REJECTIONS})
    copies = Counter()
    theoretical = defaultdict(list)
    original_tray_enabled = plan.tray_enabled
    plan.tray_enabled = original_tray_enabled and 'DVD_TRAY' in config['deviceTypes']
    tray_accents(plan, copies, config['maxCopiesPerEvent'], config['minScore'], theoretical)
    plan.tray_enabled = original_tray_enabled
    rejects['cooldown'] += plan.tray_report['skippedBusyCooldown']
    rejects['scoreTooLow'] += plan.tray_report['skippedSampled'] + plan.tray_report['skippedScore']
    rejects['maxCopiesReached'] += plan.tray_report['skippedMaxCopies']
    instances = [VirtualDeviceInstance.parse(d) for d in plan.devices if d.get('enabled', True)]
    by_id = {d.id: d for d in instances}
    solo = any(d.solo and not d.mute for d in instances)
    targets = [d for d in instances if d.type in config['deviceTypes'] and d.in_preview
               and not d.mute and (not solo or d.solo)
               and (d.type != 'VHS' or config['vhsEnabled'])]
    caps = capabilities_for(instances)
    played = [e for e in plan.events if e.played and e.device_id in by_id
              and by_id[e.device_id].in_preview and not by_id[e.device_id].mute
              and (not solo or by_id[e.device_id].solo)]
    identity = {e.id: _identity(plan, e) for e in played}
    primaries = defaultdict(list)
    affinity_votes = defaultdict(Counter)
    for e in plan.events:
        if e.played:
            # A percussive note's busy cycle exceeds its MIDI note length.
            stop = max(e.end, e.actual_start + caps[e.device_id].retrigger_s)
            primaries[e.device_id].append((e.actual_start, stop))
    for e in played:
        affinity_votes[e.device_id][(e.track, *identity[e.id])] += e.actual_duration
    affinity = {d.id: (next(((e.track, *identity[e.id]) for e in played if e.track == d.track), None)
                        if d.track is not None else
                        affinity_votes[d.id].most_common(1)[0][0] if affinity_votes[d.id] else None)
                for d in targets}
    for intervals in primaries.values():
        intervals.sort()
    starts = {d.id: [s for s, _ in primaries[d.id]] for d in targets}
    reserve = config['lookAheadMs'] / 1000
    duration = max((e.end for e in plan.events), default=0.0)

    def availability(target, time, stop):
        intervals = primaries[target.id]
        index = bisect.bisect_right(starts[target.id], time + EPS) - 1
        if index >= 0 and intervals[index][1] > time + EPS:
            return 'deviceBusy'
        upcoming = index + 1
        if upcoming < len(intervals) and stop + reserve > intervals[upcoming][0] + EPS:
            return 'deviceNeededSoon'
        return None

    # Mechanical accents: existing tray policy runs first so a crash is not
    # multiplied across HDD and trays. Only selected strong strikes may use HDD.
    hits = [e for e in played if e.role == 'percussion' and e.channel == 9]
    hits.sort(key=lambda e: (e.actual_start, -e.velocity, e.id))
    busy = defaultdict(lambda: float('-inf'))
    for source in hits:
        for target in (d for d in targets if d.type == 'HDD_VCM'):
            if target.id == source.device_id:
                continue
            if source.note not in (49, 55, 57, 41, 43, 45, 47, 48, 50, 35, 36, 38, 40) or source.velocity < 105:
                rejects['scoreTooLow'] += 1
                continue
            time = source.actual_start
            length = caps[target.id].retrigger_s
            conflict = availability(target, time, time + length)
            if conflict:
                rejects[conflict] += 1
                continue
            if 75 + source.velocity / 127 * 20 >= config['minScore']:
                theoretical[target.id].append((time, time + length))
            if busy[target.id] > time + EPS:
                rejects['cooldown'] += 1
                continue
            if copies[source.id] >= config['maxCopiesPerEvent']:
                rejects['maxCopiesReached'] += 1
                continue
            score = 75 + source.velocity / 127 * 20
            if score < config['minScore']:
                rejects['scoreTooLow'] += 1
                continue
            plan.reinforcements.append(ReinforcementEvent(source.id, target.id, time,
                length, 0, source.velocity, kind='hit', source_device=source.device_id,
                reason='strong GM accent; idle HDD; reserved primary cycle', score=score,
                semantic_compatibility='PERCUSSION', role='PERCUSSION', gm_family='GM percussion', gm_program=source.note))
            copies[source.id] += 1
            busy[target.id] = time + length + config['percussionCooldownMs'] / 1000

    # Extend the original DVD interval sweep to all compatible tonal targets.
    tonal = [e for e in played if e.role != 'percussion' and e.actual_duration > EPS]
    updates = defaultdict(list)
    for e in tonal:
        updates[e.actual_start].append((1, e))
        updates[e.end].append((0, e))
    for target in targets:
        if target.type not in ('FDD', 'DVD_SLED', 'VHS'):
            continue
        for start, stop in primaries[target.id]:
            updates[max(0, start - reserve)]
            updates[stop]
    times = sorted(updates)
    active = {}
    previous = {}
    for time, end in zip(times, times[1:]):
        for kind, e in sorted(updates[time], key=lambda p: (p[0], p[1].id)):
            if kind:
                active[e.id] = e
            else:
                active.pop(e.id, None)
        if end - time <= EPS:
            continue
        current = {}
        local_copies = Counter()
        candidates = []
        for target in targets:
            if target.type not in ('FDD', 'DVD_SLED', 'VHS'):
                continue
            for source in active.values():
                if source.device_id == target.id:
                    continue
                conflict = availability(target, time, end)
                if conflict:
                    rejects[conflict] += 1
                    continue
                reject, bonus, reason = _compatible(source, target, caps[target.id], identity[source.id], affinity[target.id])
                if reject:
                    rejects[reject] += 1
                    continue
                score = priority(source) + bonus - max(0, len(active) - 5) * 2
                key = (source.id, target.id)
                if key in previous:
                    score += 6  # retain an existing copy instead of rapid churn
                if score < config['minScore']:
                    rejects['scoreTooLow'] += 1
                    continue
                theoretical[target.id].append((time, end))
                if end - time < caps[target.id].min_note_s and key not in previous:
                    rejects['deviceNeededSoon'] += 1
                    continue
                candidates.append((score, source, target, reason))
        used = set()
        for score, source, target, reason in sorted(candidates, key=lambda c: (-c[0], c[1].id, c[2].id)):
            if target.id in used:
                continue
            if local_copies[source.id] >= config['maxCopiesPerEvent']:
                rejects['maxCopiesReached'] += 1
                continue
            if local_copies[source.id] and score - 18 < config['minScore']:
                rejects['scoreTooLow'] += 1
                continue
            used.add(target.id)
            local_copies[source.id] += 1
            key = (source.id, target.id)
            old = previous.get(key)
            if old is not None and abs(plan.reinforcements[old].start + plan.reinforcements[old].duration - time) < EPS:
                plan.reinforcements[old] = dataclasses.replace(plan.reinforcements[old], duration=end - plan.reinforcements[old].start)
                current[key] = old
            else:
                role, family, program = identity[source.id]
                current[key] = len(plan.reinforcements)
                plan.reinforcements.append(ReinforcementEvent(source.id, target.id, time, end-time,
                    source.played_hz, source.velocity, source_device=source.device_id,
                    reason='idle compatible device; ' + reason, score=score,
                    semantic_compatibility=reason, role=role, gm_family=family, gm_program=program))
        previous = current

    minimum = config['minDurationMs'] / 1000
    rejects['fragmentTooShort'] += sum(e.kind == 'tone' and e.duration + EPS < minimum for e in plan.reinforcements)
    plan.reinforcements = [e for e in plan.reinforcements if e.kind != 'tone' or e.duration + EPS >= minimum]
    all_extras = [*plan.reinforcements, *plan.tray_events]
    actual = defaultdict(list)
    role_counts, family_counts, program_counts, type_counts = Counter(), Counter(), Counter(), Counter()
    sources = {e.id: e for e in played}
    for extra in all_extras:
        source = sources[extra.source_id]
        role, family, program = identity[source.id]
        actual[extra.device_id].append((extra.start, extra.start + extra.duration))
        type_counts[by_id[extra.device_id].type] += 1
        role_counts[role] += 1
        family_counts[family or ('GM percussion' if source.channel == 9 else 'Unknown')] += 1
        program_counts[str(source.note if source.channel == 9 else program)] += 1
    metrics = {}
    for device in instances:
        normal = _union(primaries[device.id])
        reinforced = _union(actual[device.id])
        potential = _union(theoretical[device.id])
        metrics[device.id] = {'primarySeconds': round(normal, 3),
            'reinforcementSeconds': round(reinforced, 3),
            'idleSeconds': round(max(0, duration - normal - reinforced), 3),
            'idleButReinforceableSeconds': round(potential, 3),
            'unusedReinforceableSeconds': round(max(0, potential - reinforced), 3),
            'utilization': round((normal + reinforced) / duration, 4) if duration else 0}
    per_source = defaultdict(list)
    for extra in all_extras:
        per_source[extra.source_id].extend([(extra.start, 1), (extra.start + extra.duration, -1)])
    peaks = []
    for points in per_source.values():
        value = peak = 0
        for _, delta in sorted(points):
            value += delta
            peak = max(peak, value)
        peaks.append(peak)
    plan.idle_report = {'enabled': True, 'events': len(all_extras),
        'byDeviceType': dict(type_counts), 'bySemanticRole': dict(role_counts),
        'byGmFamily': dict(family_counts), 'byGmInstrument': dict(program_counts),
        'averageCopiesPerReinforcedEvent': round(sum(peaks) / len(peaks), 3) if peaks else 0,
        'rejected': dict(rejects), 'devices': metrics,
        'rejectionUnit': 'candidate-target interval evaluations; percussion candidate-target hits',
        'copiesDefinition': 'simultaneous tonal copies; total mechanical strike copies per source event',
        'potentialDefinition': 'compatible score-qualified idle tonal intervals before copy quota; free HDD accent cycles; compatible tray motion ignoring extra copy/cooldown/sample quotas'}
def legacy_dvd(plan: PerformancePlan, priority) -> list[ReinforcementEvent]:
    """Fill idle DVD intervals after normal allocation and articulation finish."""
    dvd = [device for device in plan.devices if device.get('enabled', True) and device['type'] == 'DVD_SLED'
           and device.get('mode', 'virtual') in ('virtual', 'hybrid')
           and not device.get('mute', False)]
    if any(device.get('enabled', True) and device.get('solo') and not device.get('mute') for device in plan.devices):
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
        sources.sort(key=lambda event: (-priority(event),
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
