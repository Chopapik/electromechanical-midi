"""Pitch-only DVD register after allocation, sustain and voice recovery.

This is a musical register, not a measured mechanical or thermal safe range.
Reservations and every non-DVD command remain unchanged.
"""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import replace
from types import SimpleNamespace

from .instrument_roles import contexts
from .mechanical_arrangement import ChronologyCache
from .planning_context import replace_extras

MIN_HZ = 200.
MAX_HZ = 800.


def _octaves(values):
    return [n for n in range(-16, 17)
            if all(MIN_HZ - 1e-9 <= hz * 2.**n <= MAX_HZ + 1e-9 for hz in values)]


def _choose(choices):
    # Prefer one octave up; otherwise retain the register before lowering it.
    return min(choices, key=lambda n: (abs(n-1), abs(n), n))


def apply(plan, registry, source):
    if 'dvdRegister' in plan.hardware:
        return  # A completed plan must not transpose twice.
    types = {d['id']: d['type'] for d in plan.devices}
    sources = {e.id: e for e in plan.events}
    items = [{'id': e.id, 'track': e.track, 'role': e.role, 'order': i,
              'span': SimpleNamespace(start=e.start, end=e.start+e.duration,
                  duration=e.duration, note=e.note, channel=e.channel)}
             for i, e in enumerate(plan.events)
             if e.role not in ('percussion', 'unpitched_effect')]
    voices = contexts(items, 1.5)
    parts = defaultdict(list)
    for item in items:
        e = sources[item['id']]
        parts[e.track, e.channel, voices[e.id]['voiceId']].append(e)
    raw = getattr(source, 'source', source)
    segments = getattr(getattr(raw, 'tempo', None), '_segments', [])
    times = [s.seconds for s in segments]
    phrases = {}
    for key, events in parts.items():
        previous = None
        phrase = 0
        for e in sorted(events, key=lambda e: (e.start, e.id)):
            index = bisect_right(times, e.start)-1
            beat = segments[index].tempo/1e6 if index >= 0 else .5
            # True source rests split phrases. Sustain extensions do not erase
            # that boundary; dropped/routed-away source notes still participate.
            if previous and e.start-(previous.start+previous.duration) > min(1.5, max(.4, 2*beat)):
                phrase += 1
            phrases[e.id] = (*key, phrase)
            previous = e

    entries = {}
    for e in plan.events:
        if e.played and e.device_type == 'DVD_SLED':
            entries[e.id] = (e.id, e.played_hz, e.device_id, 1.)
    for i, extra in enumerate(plan.reinforcements):
        if types[extra.device_id] == 'DVD_SLED':
            source_event = sources.get(extra.source_id)
            # Retargeted sidecars retain the primary voice's frequency curve,
            # which may be in a different octave from its DVD reinforcement.
            base = source_event.played_hz if source_event else None
            entries['extra:'+str(i)] = (extra.source_id, extra.hz, extra.device_id,
                                        extra.hz/base if base else 1.)
    groups = defaultdict(list)
    curves = {}
    bounds = {}
    for ident, (source_id, hz, _, curve_scale) in entries.items():
        art = plan.execution_articulation.get(ident, {})
        curve = art.get('frequency', {})
        values = tuple(v*curve_scale for v in curve.get('values', ()))
        curves[ident] = values
        bounds[ident] = (hz, *values)
        groups[phrases.get(source_id, ('isolated', source_id))].append(ident)

    shifts = {}
    fallback = 0
    curve_folds = 0
    for group in groups.values():
        choices = _octaves([v for ident in group for v in bounds[ident]])
        if choices:
            shift = _choose(choices)
            shifts.update((ident, shift) for ident in group)
        else:
            fallback += 1
            # An exceptionally wide phrase cannot retain every interval within
            # a fourfold range. Preserve pitch classes instead of dropping notes.
            for ident in group:
                choices = _octaves(bounds[ident]) or _octaves([entries[ident][1]])
                shifts[ident] = _choose(choices)

    new_art = dict(plan.execution_articulation)
    pitches = {}
    for ident, (_, hz, _, _) in entries.items():
        factor = 2.**shifts[ident]
        pitches[ident] = hz*factor
        if curves[ident]:
            values = []
            for v in curves[ident]:
                shifted = v*factor
                if not MIN_HZ-1e-9 <= shifted <= MAX_HZ+1e-9:
                    shifted = v*2.**_choose(_octaves([v]))
                    curve_folds += 1
                values.append(shifted)
            art = plan.execution_articulation[ident]
            new_art[ident] = {**art, 'frequency': {**art['frequency'], 'values': tuple(values)}}
    new_events = [replace(e, played_hz=pitches[e.id],
                         played_note=e.played_note+12*shifts[e.id] if e.played_note is not None else None)
                  if e.id in pitches else e for e in plan.events]
    new_extras = [replace(e, hz=pitches['extra:'+str(i)]) if 'extra:'+str(i) in pitches else e
                  for i, e in enumerate(plan.reinforcements)]

    # Validate the complete final DVD chronology, including all reservations.
    # Failure is explicit; this pass must never discard a note to hide a conflict.
    evaluations = {}
    states = {}
    for device in sorted({entry[2] for entry in entries.values()}):
        chronology = ChronologyCache(registry.profile(device))
        primaries = [e for e in new_events if e.played and e.device_id == device]
        extras = [e for e in new_extras if e.device_id == device]
        result = chronology.check(primaries, extras)
        if result is None:
            raise ValueError('DVD register violates mechanical chronology: '+device)
        evaluations.update((e.id, result[e.id].as_dict()) for e in primaries)
        states[device] = chronology.states[-1].as_dict()
    plan.events = [replace(e, hardware={**e.hardware, **evaluations[e.id],
        'dvdRegister': {'allocatedHz': entries[e.id][1], 'octaves': shifts[e.id]}})
        if e.id in evaluations else e for e in new_events]
    replace_extras(plan, enumerate(new_extras),
                   articulations={i: new_art.get('extra:'+str(i)) for i in range(len(new_extras))},
                   primary={key: value for key, value in new_art.items() if not key.startswith('extra:')})
    plan.hardware['dvdRegister'] = {'minimumHz': MIN_HZ, 'maximumHz': MAX_HZ,
        'preferredOctaves': 1, 'phrases': len(groups), 'individualFoldPhrases': fallback,
        'curveSamplesFolded': curve_folds, 'notes': len(entries),
        'shiftedNotes': sum(n != 0 for n in shifts.values()),
        'octaves': {str(n): sum(s == n for s in shifts.values()) for n in sorted(set(shifts.values()))},
        'states': states, 'scope': 'musical register; physical and thermal behavior unmeasured'}
