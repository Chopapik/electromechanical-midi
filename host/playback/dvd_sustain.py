"""Conservative DVD legato in allocated, fully reserved performance lanes.

Dynamic mode retains the experimental 200 ms ceiling. Instrument Roles adds
tempo-aware background legato up to 350 ms, including unaccented repeats.
Only NOTE_OFF changes; explicit articulation, phrase rests and stolen gates survive.
"""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import replace
from statistics import median

from .mechanical_arrangement import ChronologyCache
from .instrument_roles import enabled as background_enabled


def apply(plan, profiles, source):
    background = background_enabled(plan.policy)
    ceiling = plan.policy.get('dvdBackgroundMaxBridgeMs', 350.) if background else plan.policy.get('dvdMaxBridgeMs', 200.)
    report = {'enabled': bool(plan.policy.get('dvdContinuousSustain')), 'bridged': 0,
              'addedSeconds': 0., 'maxBridgeMs': ceiling,
              'mode': 'background' if background else 'dynamic', 'repeatsBridged': 0}
    if not report['enabled']:
        return report
    if background:
        # Keep every already-valid dynamic bridge; stronger legato may only
        # add releases that still fit the complete physical chronology.
        dynamic = replace(plan, policy={**plan.policy, 'arrangementPreset': 'balanced',
            'dvdMaxBridgeMs': min(ceiling, plan.policy.get('dvdMaxBridgeMs', 200.))})
        existing = apply(dynamic, profiles, source)
        plan.events = dynamic.events
        report['bridged'] = report['dynamicBridgesPreserved'] = existing['bridged']
        report['addedSeconds'] = existing['addedSeconds']
    lanes, parts, voice_parts = defaultdict(list), defaultdict(list), defaultdict(list)
    voices = {}
    if background:
        from types import SimpleNamespace
        from .instrument_roles import contexts
        items = [{'id': e.id, 'track': e.track, 'role': e.role, 'order': order,
                  'span': SimpleNamespace(start=e.start, end=e.start+e.duration,
                       duration=e.duration, note=e.note, channel=e.channel)}
                 for order, e in enumerate(plan.events) if e.role not in ('percussion', 'unpitched_effect')]
        voices = contexts(items, plan.policy.get('mechanicalPhraseWindowMs', 1500.)/1000.)
    def voice_key(event):
        return (event.track, event.channel, voices[event.id]['voiceId'])
    # Include dropped/routed-away source attacks: they can interrupt a phrase.
    for event in plan.events:
        parts[(event.track, event.channel)].append(event)
        if background and event.id in voices:
            voice_parts[voice_key(event)].append(event)
        if event.played and event.device_type == 'DVD_SLED':
            lanes[event.device_id].append(event)
    for part in [*parts.values(), *voice_parts.values()]:
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
        chronology = ChronologyCache(profile)
        for current, following in zip(events, events[1:]):
            gap = following.actual_start - current.end
            if not 1e-9 < gap <= ceiling / 1000.:
                continue
            if (current.track, current.channel) != (following.track, following.channel):
                continue
            repeated = current.played_note == following.played_note
            if (repeated and not background) or current.outcome in ('SHORTENED', 'STOLEN'):
                continue
            if background and repeated and abs(current.velocity-following.velocity) >= 24:
                continue
            if current.articulation or following.articulation:
                continue
            part = parts[(current.track, current.channel)]
            beat = segments[max(0, bisect_right(times, current.start)-1)].tempo / 1e6 if segments else .5
            interruptions = (voice_parts[voice_key(current)] + voice_parts[voice_key(following)]) if background else part
            def interrupts(event):
                if not current.start + 1e-9 < event.start < following.start - 1e-9:
                    return False
                # A rendered FDD grace attack can decorate the DVD release
                # gap. It must fit wholly inside that source gap; missing,
                # sustained or explicitly articulated notes still interrupt.
                ornament = (background and event.played and event.device_type == 'FDD'
                            and not event.articulation
                            and event.duration <= min(.03, beat/8.)
                            and event.start >= current.start+current.duration-1e-9
                            and event.start+event.duration <= following.start+1e-9)
                return not ornament
            if any(interrupts(e) for e in interruptions):
                continue
            ioi = following.start-current.start
            source_gap = following.start-(current.start+current.duration)
            # At least fast quarter-note activity when dynamic-aware; never fill a
            # majority-rest gate, isolated pickup, long note or phrase boundary.
            if background:
                # A bed can breathe more slowly than a riff. Short repeated
                # release gaps are legato unless articulation/accent says otherwise.
                if ioi <= 0 or current.duration < .4*ioi:
                    continue
                if source_gap > min(ceiling/1000., beat*.9, ioi*.6)+1e-9:
                    continue
            else:
                local = sorted({e.start for e in part if abs(e.start-current.start) <= 2*beat})
                intervals = [b-a for a,b in zip(local,local[1:]) if b>a]
                if len(intervals) < 2:
                    continue
                cadence = median(intervals)
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
            if chronology.check(trial, extras) is None:
                continue
            replacements[current.id] = proposal
            report['bridged'] += 1
            report['repeatsBridged'] += int(repeated)
            report['addedSeconds'] += gap
    plan.events = [replacements.get(e.id, e) for e in plan.events]
    report['addedSeconds'] = round(report['addedSeconds'], 6)
    return report
