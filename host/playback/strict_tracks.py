"""Four independent, monophonic FDD lines for a reversible listening experiment."""
from __future__ import annotations

import dataclasses
from collections import Counter

from midi_source import MidiSource
from pitch import fold_note, midi_to_hz, note_name
from .analysis import analyze
from .capabilities import capabilities_for
from .hardware import bind_devices
from .hardware_profiles import HardwareDeviceState, HardwareNote, Verdict, advance_state, evaluate
from .orchestra import OrchestraConfig, parse_policy
from .performance import PerformanceEvent, PerformancePlan


def allocate_strict(source: MidiSource, config: OrchestraConfig, tracks: list[int | None],
                    hardware_context=None) -> PerformancePlan:
    """No cross-track rescue, voice stealing, arpeggios or reinforcement."""
    devices = config.instances()[:4]
    if len(devices) != 4 or any(d.type != 'FDD' for d in devices):
        raise ValueError('STRICT_TRACKS requires four FDD devices in slots 1–4')
    if len(tracks) != 4 or any(t is not None and (not isinstance(t, int) or
            isinstance(t, bool) or t < 0 or t >= len(source.tracks) or
            source.tracks[t].is_drums) for t in tracks):
        raise ValueError('invalid STRICT_TRACKS mapping')
    chosen = [t for t in tracks if t is not None]
    if len(chosen) != len(set(chosen)):
        raise ValueError('each STRICT_TRACKS track must be unique')
    policy = parse_policy(config.policy)
    policy['mechanicalSustain'] = False
    policy['sourceContinuity'] = False
    caps = capabilities_for(devices)
    bound, unmapped = bind_devices(devices, 2)
    lanes = {d.id: lane for lane, d in bound.items()}
    profiles = {}
    if hardware_context is not None:
        for d in devices:
            if d.mode in ('real', 'hybrid') and d.id in lanes and hardware_context.present(lanes[d.id]):
                profiles[d.id] = hardware_context.profile_for(d, lanes[d.id])
    analysis = analyze(source)
    events = []
    report = {}
    attempts = {}
    requested = Counter()
    denied = Counter()
    rejected = {d.id: Counter() for d in devices}
    solo = any(d.enabled and d.solo and not d.mute for d in devices)
    for d, track_index in zip(devices, tracks):
        if track_index is None:
            report[d.id] = {'track': None, 'requested': 0, 'played': 0, 'dropped': 0,
                            'retention': 0., 'chordRejected': 0, 'pitchChanges': 0, 'folded': 0}
            continue
        spans = source.notes(track_index)
        groups = []
        for index, span in enumerate(spans):
            if groups and abs(groups[-1][0] - span.start) < 1e-7:
                groups[-1][1].append((index, span))
            else:
                groups.append((span.start, [(index, span)]))
        profile = profiles.get(d.id)
        cap = caps[d.id]
        low, high = cap.min_hz, cap.max_hz
        if profile is not None:
            musical = profile.get('musicalHz')
            minimum_us = profile.get('executionMinStepUs')
            if musical and minimum_us:
                low, high = max(low, musical[0]), min(high, musical[1], 1e6 / minimum_us)
            else:
                profile = None
        state = HardwareDeviceState()
        previous_pitch = None
        previous_source_note = None
        busy_until = 0.
        playing_until = 0.
        chord_rejected = 0
        output_disabled = not d.enabled or d.mute or (solo and not d.solo)
        for position, (start, group) in enumerate(groups):
            next_start = groups[position + 1][0] if position + 1 < len(groups) else float('inf')
            options = []
            for index, span in group:
                folded = fold_note(span.note, low, high, policy['foldMode'])
                pitch = folded.midi_note + 12 * folded.octave_shift
                duration = span.duration * d.gate
                if next_start >= span.end - 1e-7:
                    duration = min(duration, next_start - start - .012)
                if policy['maxNoteSeconds'] > 0:
                    duration = min(duration, policy['maxNoteSeconds'])
                duration = max(0., duration)
                reason = None
                evaluation = None
                if output_disabled:
                    reason = 'OUTPUT_DISABLED'
                elif not folded.in_range:
                    reason = 'OUT_OF_RANGE'
                elif duration < cap.min_note_s:
                    reason = 'NOTE_TOO_SHORT'
                elif start + 1e-9 < busy_until:
                    reason = ('CHORD_REJECTED' if start < playing_until - 1e-7
                              and span.note != previous_source_note else 'DEVICE_BUSY')
                elif hardware_context is not None and profile is None:
                    reason = 'NO_DEVICE'
                elif profile is not None:
                    evaluation = evaluate(profile, HardwareNote(folded.hz, duration, start), state)
                    if not evaluation.authorized or Verdict.BLOCKED in (evaluation.timing, evaluation.quality, evaluation.physical_load) or evaluation.ready_at > start + 1e-8:
                        reason = next((r for r in evaluation.reasons if r != 'PHYSICAL_UNKNOWN'), 'TIMING_CONFLICT')
                options.append((index, span, pitch, folded.hz, duration, reason, evaluation))
            viable = [o for o in options if o[5] is None]
            winner = min(viable, key=lambda o: (abs(o[2] - previous_pitch) if previous_pitch is not None else -o[2],
                                                -o[1].velocity, o[0])) if viable else None
            for index, span, pitch, hz, duration, reason, evaluation in options:
                selected = winner is not None and index == winner[0]
                if not selected:
                    reason = 'CHORD_REJECTED' if winner is not None else reason or 'DEVICE_BUSY'
                    chord_rejected += int(reason == 'CHORD_REJECTED')
                    denied[d.id] += 1
                    rejected[d.id][reason] += 1
                event = PerformanceEvent(
                    id=f'{track_index}:{index}', track=track_index,
                    track_name=source.tracks[track_index].name, note=span.note,
                    name=note_name(span.note), velocity=span.velocity,
                    channel=span.channel, start=span.start, duration=span.duration,
                    device_id=d.id if selected else None, device_type='FDD' if selected else None,
                    played_note=pitch if selected else None, played_hz=hz if selected else None,
                    actual_start=span.start, actual_duration=duration if selected else 0.,
                    outcome=('FOLDED' if pitch != span.note else 'ACCEPTED') if selected else 'DROPPED',
                    role='lead' if track_index == analysis.lead_track else 'harmony',
                    preferred_device=d.id, reason=None if selected else reason,
                    source_tracks=(track_index,))
                events.append(event)
                if selected:
                    requested[d.id] += 1
                    previous_pitch = pitch
                    previous_source_note = span.note
                    playing_until = start + duration
                    busy_until = start + duration + max(cap.retrigger_s, .012)
                    if profile is not None:
                        attempts[event.id] = {d.id: evaluation.as_dict()}
                        advance_state(state, profile, HardwareNote(hz, duration, start), evaluation)
        selected_events = [e for e in events if e.track == track_index and e.device_id == d.id]
        report[d.id] = {'track': track_index, 'trackName': source.tracks[track_index].name,
                        'requested': len(spans), 'played': len(selected_events),
                        'dropped': len(spans) - len(selected_events),
                        'retention': round(len(selected_events) / len(spans), 4) if spans else 0.,
                        'chordRejected': chord_rejected,
                        'pitchChanges': sum(a.played_note != b.played_note for a, b in zip(selected_events, selected_events[1:])),
                        'folded': sum(e.folded for e in selected_events)}
    events.sort(key=lambda e: (e.actual_start, e.track, e.id))
    plan = PerformancePlan(source.path.stem, events, [dataclasses.asdict(d) for d in devices],
                           policy, analysis=analysis.as_dict(), origin='strict_tracks',
                           strict_report=report, dvd_mode='independent', tray_enabled=False)
    if hardware_context is not None and profiles:
        from .hardware_arranger import validate_plan
        validate_plan(plan, profiles, {d: lanes[d] for d in profiles}, attempts,
                      requested, rejected, {}, unmapped, denied)
        for d in report:
            t = report[d]['track']
            if t is not None:
                played = [e for e in plan.events if e.device_id == d]
                report[d].update(played=len(played), dropped=report[d]['requested'] - len(played),
                                 retention=round(len(played) / report[d]['requested'], 4) if report[d]['requested'] else 0.,
                                 pitchChanges=sum(a.played_note != b.played_note for a, b in zip(played, played[1:])),
                                 folded=sum(e.folded for e in played))
    return plan
