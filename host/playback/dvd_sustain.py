"""Conservative DVD legato in allocated, fully reserved performance lanes.

200 ms is an experimental ceiling, not a thermal or musical calibration.
Only NOTE_OFF changes. Explicit repeats, source rests and stolen gates survive.
"""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import replace
from statistics import median

from .mechanical_arrangement import _chronology


def apply(plan, profiles, source):
    report = {'enabled': bool(plan.policy.get('dvdContinuousSustain')), 'bridged': 0,
              'addedSeconds': 0., 'maxBridgeMs': plan.policy.get('dvdMaxBridgeMs', 200.)}
    if not report['enabled']:
        return report
    lanes, parts = defaultdict(list), defaultdict(list)
    # Include dropped/routed-away source attacks: they can interrupt a phrase.
    for event in plan.events:
        parts[(event.track, event.channel)].append(event)
        if event.played and event.device_type == 'DVD_SLED':
            lanes[event.device_id].append(event)
    for part in parts.values():
        part.sort(key=lambda e: (e.start, e.id))
    raw = getattr(source, 'source', source)
    segments = getattr(getattr(raw, 'tempo', None), '_segments', [])
    times = [s.seconds for s in segments]
    replacements = {}
    for ident, events in sorted(lanes.items()):
        profile = profiles[ident]
        if not profile.get('continuousRotation'):
            continue
        events.sort(key=lambda e: (e.actual_start, e.id))
        extras = [e for e in plan.reinforcements if e.device_id == ident]
        for current, following in zip(events, events[1:]):
            gap = following.actual_start - current.end
            if not 1e-9 < gap <= plan.policy['dvdMaxBridgeMs'] / 1000.:
                continue
            if (current.track, current.channel) != (following.track, following.channel):
                continue
            if current.played_note == following.played_note or current.outcome in ('SHORTENED', 'STOLEN'):
                continue
            if current.articulation or following.articulation:
                continue
            part = parts[(current.track, current.channel)]
            if any(current.start + 1e-9 < e.start < following.start - 1e-9 for e in part):
                continue
            beat = segments[max(0, bisect_right(times, current.start)-1)].tempo / 1e6 if segments else .5
            local = sorted({e.start for e in part if abs(e.start-current.start) <= 2*beat})
            intervals = [b-a for a,b in zip(local,local[1:]) if b>a]
            if len(intervals) < 2:
                continue
            cadence = median(intervals)
            ioi = following.start-current.start
            source_gap = following.start-(current.start+current.duration)
            # At least fast quarter-note activity when dynamic-aware; never fill a
            # majority-rest gate, isolated pickup, long note or phrase boundary.
            if plan.policy['dvdDynamicAware'] and cadence > min(.4, beat*1.05):
                continue
            if ioi <= 0 or ioi > 1.5*cadence or current.duration > 2*beat:
                continue
            if source_gap > min(beat*.6, ioi*.55) + 1e-9:
                continue
            if any(e.start < following.actual_start-1e-9 and e.start+e.duration > current.end+1e-9 for e in extras):
                continue
            proposal = replace(current, actual_duration=following.actual_start-current.actual_start,
                               sustain_added=current.sustain_added+gap)
            trial = [replacements.get(e.id, e) if e.id != current.id else proposal for e in events]
            # Final complete mechanical chronology vetoes extensions, never
            # drops a primary note to make sustain fit.
            if _chronology(profile, trial, extras) is None:
                continue
            replacements[current.id] = proposal
            report['bridged'] += 1
            report['addedSeconds'] += gap
    plan.events = [replacements.get(e.id, e) for e in plan.events]
    report['addedSeconds'] = round(report['addedSeconds'], 6)
    return report
