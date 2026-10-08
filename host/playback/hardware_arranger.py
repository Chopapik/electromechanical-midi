"""Conservative physical allocation, using the existing semantic analysis and plan.

This path never uses the legacy acoustic renderer to decide physical commands.
Counters describe PLANNED commands, not verified movement or audible notes.
"""
from __future__ import annotations
import dataclasses
from collections import Counter

from pitch import fold_note, midi_to_hz
from .hardware import bind_devices
from .hardware_profiles import HardwareDeviceState, HardwareNote, Verdict, evaluate, advance_state
from .performance import PerformancePlan


def fold_for_profile(note, minimum, maximum, mode, profile):
    bands = profile.get('allowedBandsHz')
    if bands is None:
        return fold_note(note, minimum, maximum, mode)
    ratio = profile.get('pitchRatio') if profile.name == 'DVD_SLED' else 1.
    if ratio is None:
        return fold_note(note, minimum, maximum, mode)
    candidates = []
    for low, high in bands:
        low, high = max(minimum, low * ratio), min(maximum, high * ratio)
        if low > high:
            continue
        candidate = fold_note(note, low, high, mode)
        # Strict endpoints: sampled gaps are not qualified.
        if low <= candidate.hz <= high and candidate.in_range:
            candidates.append(candidate)
    if not candidates:
        # Evaluation rejects this candidate; other instruments are still tried.
        return fold_note(note, minimum, maximum, mode)
    if mode == 'low': return min(candidates, key=lambda f: f.octave_shift)
    if mode == 'high': return max(candidates, key=lambda f: f.octave_shift)
    import math
    centre = (minimum + maximum) / 2.
    return min(candidates, key=lambda f: (abs(f.octave_shift), abs(math.log2(f.hz / centre)), f.octave_shift))


def selection_key(evaluation, profile, device_id):
    confidence = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, 'UNKNOWN': 3}
    physical = max((confidence[q.confidence] for q in profile.quantities.values()
                    if q.value is None or q.evidence_type != 'FACT'), default=3)
    return (-evaluation.score, evaluation.transition_time,
            evaluation.braking_distance or 0, evaluation.reversal_rate or 0, physical, device_id)


def allocate_hardware(source, config, context, *, midi_analysis=None, pins=None, name=None, origin='auto'):
    # Reuse classification, normalization provenance, policy and articulation.
    from .allocator import (_source_notes, _dropped, _Slot, _Candidate, _place, _clip,
                            analysis_module, LEAD, PERCUSSION, BASS, HARMONY,
                            _adaptive_cap, _duplicate_kpis)
    from .orchestra import parse_policy
    from .capabilities import capabilities_for
    from .articulation import apply, params_from_policy, apply_source_continuity
    from .tonal_articulation import capture

    policy = parse_policy(config.policy)
    devices = config.instances()  # Keep disabled ordinals: FDD2 must never become FDD1.
    bound, unmapped = bind_devices(devices, 2)
    caps = capabilities_for(devices)
    slots = {}; profiles = {}; states = {}; lanes = {}; excluded = {}
    solo = any(d.solo for d in devices if d.enabled)
    for lane, device in bound.items():
        profile = context.profile_for(device, lane)
        if not context.present(lane) or device.mute or (solo and not device.solo):
            excluded[device.id] = 'NO_DEVICE'; continue
        if profile is None:
            excluded[device.id] = 'PROFILE_UNKNOWN'; continue
        cap = caps[device.id]
        musical = profile.get('musicalStepRate' if profile.name == 'DVD_SLED' else 'musicalHz')
        if profile.name != 'HDD_PERCUSSION' and musical is None:
            excluded[device.id] = 'MUSICAL_RANGE_UNKNOWN'; continue
        if profile.name == 'DVD_SLED':
            ratio = profile.get('pitchRatio')
            if ratio is not None: musical = [x * ratio for x in musical]
        if profile.name == 'FDD':
            step_ms=profile.get('datasheetMinStepMs')
            minimum_us = profile.get('executionMinStepUs') or (step_ms*1000 if step_ms is not None else None)
            if minimum_us is None:
                excluded[device.id]='STEP_INTERVAL_UNKNOWN';continue
            musical = [musical[0], min(musical[1],1000000./minimum_us)]
        cap = dataclasses.replace(cap, min_hz=musical[0] if musical else None,
                                  max_hz=musical[1] if musical else None, retrigger_s=0.)
        slots[device.id] = _Slot(device, cap)
        profiles[device.id] = profile
        states[device.id] = HardwareDeviceState(position=0. if profile.name == 'DVD_SLED' else None,
                                                position_confidence='LOW' if profile.name == 'DVD_SLED' else 'UNKNOWN')
        lanes[device.id] = lane
    midi_analysis = midi_analysis or analysis_module.analyze(source)
    notes = _source_notes(source, midi_analysis, policy); pins = pins or {}
    lead = [s for s in slots.values() if profiles[s.device.id].name == 'VHS']
    accompaniment = [s for s in slots.values() if profiles[s.device.id].name not in ('VHS', 'HDD_PERCUSSION')]
    if policy.get('tonalOverflow') == 'adaptive':
        if not policy.get('maxNoteSeconds'):
            policy['maxNoteSeconds'] = _adaptive_cap(notes, accompaniment, policy, frozenset({BASS, HARMONY}))
        if not policy.get('leadMaxNoteSeconds'):
            policy['leadMaxNoteSeconds'] = _adaptive_cap(notes, lead or accompaniment, policy, frozenset({LEAD}))
    events = []; attempts = {}; requested = Counter(); denied = Counter(); rejected = {d: Counter() for d in slots}
    for item in notes:
        span = item['span']; role = item['role']; pin = pins.get(item['id'])
        if pin is not None and pin.device_id is None:
            events.append(_dropped(item, 'MANUAL_DROP', role, None, pin)); continue
        pool = ([s for s in slots.values() if profiles[s.device.id].name == 'HDD_PERCUSSION']
                if role == PERCUSSION else lead if role == LEAD and lead else accompaniment)
        candidates = []; diagnostics = {}
        for slot in pool:
            device = slot.device; ident = device.id; profile = profiles[ident]; state = states[ident]
            requested[ident] += 1
            gate = pin.gate if pin else 1.
            duration = _clip(span.duration * gate, slot.capability.min_note_s, policy,
                             'leadMaxNoteSeconds' if role == LEAD else 'maxNoteSeconds')
            if profile.name == 'HDD_PERCUSSION':
                played = None; hz = None; folded = False
                stages=[profile.get(k) for k in ('parkMs','settleMs','strikeMs')]
                # Unknown reset duration will be rejected by evaluation, not
                # converted to a zero/infinite mechanical reservation.
                if all(v is not None for v in stages):duration=sum(stages)/1000.
            else:
                transpose = device.transpose + (pin.transpose if pin else 0)
                shifted = span.note + transpose
                if pin is None or pin.octave_fold:
                    fold = fold_for_profile(shifted, slot.capability.min_hz, slot.capability.max_hz, policy['foldMode'], profile)
                    played = fold.midi_note + 12 * fold.octave_shift; hz = fold.hz; folded = bool(fold.octave_shift)
                else: played = shifted; hz = midi_to_hz(shifted); folded = False
            note = HardwareNote(hz, duration, span.start)
            ev = evaluate(profile, note, state)
            diagnostics[ident] = ev.as_dict()
            if not ev.authorized or Verdict.BLOCKED in (ev.timing, ev.quality, ev.physical_load):
                denied[ident] += 1
                for reason in ev.reasons: rejected[ident][reason] += 1
                continue
            arrival = max(span.start, ev.ready_at, slot.busy_until)
            window = (policy['leadMaxMicroDelayMs'] if role == LEAD else
                      policy['maxMicroDelayMs'] if role == PERCUSSION else policy['maxArpeggioMs']) / 1000.
            if arrival - span.start > window + 1e-9:
                denied[ident] += 1
                rejected[ident]['TIMING_CONFLICT'] += 1; continue
            candidates.append((selection_key(ev, profile, ident), slot, played, hz, folded, duration, arrival))
        attempts[item['id']] = diagnostics
        if not candidates:
            reasons = [r for v in diagnostics.values() for r in v['reasons'] if r != 'PHYSICAL_UNKNOWN']
            reason = ('NO_DEVICE' if not pool else reasons[0] if reasons else
                      'PHYSICAL_UNKNOWN' if any(not v['authorized'] for v in diagnostics.values()) else 'TIMING_CONFLICT')
            event = _dropped(item, reason, role, pin.device_id if pin else None, pin)
            events.append(dataclasses.replace(event, hardware={'candidates': diagnostics})); continue
        _, slot, played, hz, folded, duration, arrival = min(candidates, key=lambda c: c[0])
        preferred = pin.device_id if pin and pin.device_id else slot.device.id
        outcome = ('ARPEGGIATED' if arrival - span.start > policy['maxMicroDelayMs']/1000. else
                   'DELAYED') if arrival > span.start+1e-9 else 'REASSIGNED' if preferred != slot.device.id else 'ACCEPTED'
        _place(slot, _Candidate(slot, played, hz, folded), item, outcome, arrival, duration, role, pin, preferred, events)
        note = HardwareNote(hz, duration, arrival)
        ev = evaluate(profiles[slot.device.id], note, states[slot.device.id])
        if profiles[slot.device.id].name=='DVD_SLED' and arrival>states[slot.device.id].ready_at+1e-9:
            states[slot.device.id].current_step_rate=0.
        advance_state(states[slot.device.id], profiles[slot.device.id], note, ev)
        slot.busy_until = states[slot.device.id].ready_at
    events.sort(key=lambda e: (e.actual_start, e.track, e.id))
    duplicate_report = getattr(source, 'duplicate_report', None)
    plan = PerformancePlan(name or source.path.stem, events, [dataclasses.asdict(d) for d in devices], policy,
                           analysis=midi_analysis.as_dict(), origin=origin, lead_devices=tuple(s.device.id for s in lead),
                           dvd_mode=config.dvd_mode, tray_enabled=config.tray_enabled,
                           idle_reinforcement=dict(config.idle_reinforcement),
                           duplicates=_duplicate_kpis(source, notes, accompaniment, duplicate_report) if duplicate_report else {})
    plan.articulation = apply(plan, caps, params_from_policy(policy))
    if policy.get('sourceContinuity'):
        plan.articulation['sourceContinuity'] = apply_source_continuity(plan, caps, policy['sourceContinuityAmount'])
    plan.expression = capture(source)
    # Recheck FINAL durations after sustain. Mechanical reset/normal notes take priority.
    validate_plan(plan, profiles, lanes, attempts, requested, rejected, excluded, unmapped, denied)
    # Reinforcement remains a post-pass. Never let legacy preview choose physical lanes.
    from .reinforcement import apply_reinforcement
    from .allocator import _priority
    apply_reinforcement(plan, lambda e: _priority(e.role, e.velocity, e.duration, plan.policy))
    validate_reinforcement(plan, profiles, lanes)
    return plan


def validate_plan(plan, profiles, lanes, attempts, requested, rejected, excluded, unmapped, denied):
    states = {ident: HardwareDeviceState(position=0. if p.name == 'DVD_SLED' else None)
              for ident, p in profiles.items()}
    counters = {ident: dict(requestedNotes=requested[ident], acceptedNotes=0, playedNotes=0,
                 droppedNotes=denied[ident], degradedNotes=0, dropReasons=dict(rejected[ident]),
                 transitions=0, reversals=0, travelReversals=0, accelerationLimited=0, tooShort=0,
                 outsidePreferredRange=0, outsideStableRange=0, physicalUnknown=0) for ident in profiles}
    final = []
    for event in plan.events:
        if not event.played: final.append(event); continue
        ident = event.device_id; profile = profiles[ident]; state = states[ident]
        note = HardwareNote(event.played_hz, event.actual_duration, event.actual_start)
        ev = evaluate(profile, note, state)
        if not ev.authorized or ev.ready_at > note.start + 1e-8:
            reason = next((r for r in ev.reasons if r != 'PHYSICAL_UNKNOWN'), 'TIMING_CONFLICT')
            counters[ident]['dropReasons'][reason] = counters[ident]['dropReasons'].get(reason, 0) + 1
            counters[ident]['droppedNotes'] += 1
            final.append(dataclasses.replace(event, device_id=None, device_type=None, outcome='DROPPED',
                                             actual_duration=0., reason=reason, hardware=ev.as_dict())); continue
        counter = counters[ident]; counter['acceptedNotes'] += 1; counter['playedNotes'] += 1
        counter['degradedNotes'] += int(ev.quality != Verdict.PASS or ev.timing != Verdict.PASS)
        counter['transitions'] += int(ev.transition_time > 0)
        counter['physicalUnknown'] += int(ev.physical_load == Verdict.UNKNOWN)
        for key, reason in [('accelerationLimited','ACCELERATION_LIMIT'),
                            ('tooShort','NOTE_TOO_SHORT'), ('outsidePreferredRange','OUTSIDE_PREFERRED_RANGE'),
                            ('outsideStableRange','OUTSIDE_STABLE_RANGE'), ('reversals','REVERSAL_CONFLICT')]:
            counter[key] += int(reason in ev.quality_reasons)
        if profile.name=='DVD_SLED' and note.start>state.ready_at+1e-9: state.current_step_rate=0.
        before_reversals=state.travel_reversals
        advance_state(state, profile, note, ev)
        projected_reversals=state.travel_reversals-before_reversals
        counter['travelReversals']+=projected_reversals
        counter['reversals']+=projected_reversals
        final.append(dataclasses.replace(event, hardware={**ev.as_dict(), 'lane':lanes[ident],
                                                         'candidates':attempts.get(event.id, {})}))
    plan.events = final
    plan.hardware = {'schemaVersion':1, 'scope':'planned; not measured physical execution',
                     'physicalLanes':lanes, 'profiles':{d:p.as_dict() for d,p in profiles.items()},
                     'states':{d:s.as_dict() for d,s in states.items()}, 'counters':counters,
                     'excludedDevices':excluded, 'unmapped':unmapped,
                     'policy':'conservative physical allocation; no voice steal through actuator transitions'}


def validate_reinforcement(plan, profiles, lanes):
    # Evaluate the combined chronology, including future primary readiness. An
    # optional dub is removed if it changes any primary event's readiness/quality.
    accepted = []
    primary = {d:sorted([e for e in plan.events if e.played and e.device_id==d], key=lambda e:e.actual_start) for d in profiles}
    for dub in sorted(plan.reinforcements, key=lambda e:(e.start,e.device_id)):
        if dub.device_id not in profiles: continue
        profile = profiles[dub.device_id]
        if profile.name not in ('FDD','DVD_SLED'): continue
        # A conservative stop boundary leaves both reversal/acceleration settling
        # and all primary reservations untouched. No hardware percussion dubs.
        preceding = [e for e in primary[dub.device_id] if e.actual_start < dub.start]
        state = HardwareDeviceState(position=0. if profile.name=='DVD_SLED' else None)
        for e in preceding:
            note=HardwareNote(e.played_hz,e.actual_duration,e.actual_start)
            advance_state(state,profile,note,evaluate(profile,note,state))
        if any(e.actual_start < dub.start+dub.duration and e.end > dub.start for e in primary[dub.device_id]): continue
        note = HardwareNote(dub.hz, dub.duration, dub.start); ev = evaluate(profile, note, state)
        if not ev.authorized or ev.ready_at > dub.start+1e-9: continue
        # DVD momentum can alter next normal note; allow only terminal dubs.
        future=[e for e in primary[dub.device_id] if e.actual_start>=dub.start]
        if profile.name=='DVD_SLED' and future: continue
        if profile.name=='FDD' and future:
            # FDD settling reservation uses the same execution timing as host/firmware.
            from .hardware_profiles import HardwareRegistry
            reserve=(profile.get('reversalIntervalMs')+HardwareRegistry().protocol['fddDirSetupUs']/1000.)/1000.
            if future[0].actual_start-dub.start-dub.duration<reserve: continue
        if any(e.device_id==dub.device_id and e.start+e.duration>dub.start for e in accepted): continue
        accepted.append(dub)
    plan.hardware['reinforcementRejected'] = len(plan.reinforcements)-len(accepted)+len(plan.tray_events)
    plan.reinforcements = accepted
    plan.tray_events = []  # No measured travel/current profile for trays yet.
