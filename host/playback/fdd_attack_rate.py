"""Common musical FDD attack ceiling, including repeats and optional copies.

This is an arrangement rule, not a measured actuator safety limit. Keep source
attacks unchanged and reduce dense runs rather than delaying them into a queue.
"""
from collections import defaultdict
from dataclasses import replace

from .hardware_profiles import HardwareDeviceState, HardwareNote, Verdict, evaluate, advance_state

MIN_INTERVAL_S = .120
EPS = 1e-9


def apply(plan, registry):
    fixed = float(plan.policy.get('fddFixedToneMs', 0))/1000.
    release = float(plan.policy.get('releaseGapMs', 0))/1000.
    interval = max(plan.policy.get('fddMinAttackIntervalMs', MIN_INTERVAL_S*1000)/1000.,
                   fixed+release if fixed else 0.)
    sources = {e.id: e for e in plan.events}
    types = {d['id']: d['type'] for d in plan.devices}
    lanes = defaultdict(list)
    for i, e in enumerate(plan.events):
        if e.played and e.device_type == 'FDD':
            lanes[e.device_id].append(('primary', i, e.actual_start, e.actual_duration,
                                       e.played_hz, e.id, e.articulation))
    for i, e in enumerate(plan.reinforcements):
        if types[e.device_id] == 'FDD':
            source = sources.get(e.source_id)
            lanes[e.device_id].append(('extra', i, e.start, e.duration, e.hz,
                                       e.source_id, source.articulation if source else None))
    removed, durations = set(), {}
    report = {'minAttackIntervalMs': interval*1000,
              'fixedToneMs': fixed*1000 if fixed else 0., 'suppressedAttacks': 0,
              'coalescedRepeats': 0, 'mechanicalVetoes': 0, 'devices': {}}
    for ident, events in sorted(lanes.items()):
        profile = registry.profile(ident)
        events.sort(key=lambda e: (e[2], e[0] != 'primary', e[5], e[1]))
        kept, tails = [], {}
        for event in events:
            if kept and event[2]-kept[-1][2] < interval-EPS:
                removed.add(event[:2])
                report['suppressedAttacks'] += 1
                previous = kept[-1]
                a, b = sources.get(previous[5]), sources.get(event[5])
                tail = tails.get(previous[:2], previous[2]+previous[3])
                if (not fixed and a and b and (a.track, a.channel) == (b.track, b.channel)
                        and abs(previous[4]-event[4]) < 1e-6
                        and not previous[6] and not event[6]
                        and a.outcome not in ('SHORTENED', 'STOLEN')
                        and event[2]-tail <= .040+EPS):
                    tails[previous[:2]] = max(tail, event[2]+event[3])
                    report['coalescedRepeats'] += 1
            else:
                kept.append(event)
        state = HardwareDeviceState()
        last_attack = None
        vetoes = 0
        for position, event in enumerate(kept):
            kind, index, start, duration, hz, source_id, _ = event
            end = max(start+duration, min(tails.get(event[:2], start+duration),
                                         start+max(duration, .4)))
            if position+1 < len(kept):
                end = max(start+duration, min(end, kept[position+1][2]-.003))
            # Removing attacks changes head travel/reversal phase. Re-evaluate
            # every retained note, and retry the original gate if merging fails.
            selected = None
            gates = (fixed,) if fixed else dict.fromkeys((end-start, duration))
            for gate in gates:
                note = HardwareNote(hz, gate, start)
                ev = evaluate(profile, note, state)
                if (ev.authorized and ev.ready_at <= start+1e-8
                        and Verdict.BLOCKED not in (ev.timing, ev.quality, ev.physical_load)):
                    selected = (note, ev)
                    break
            if selected is None:
                removed.add(event[:2])
                report['suppressedAttacks'] += 1
                report['mechanicalVetoes'] += 1
                vetoes += 1
                continue
            note, ev = selected
            durations[event[:2]] = note.duration
            advance_state(state, profile, note, ev)
            if last_attack is not None:
                assert start-last_attack >= interval-EPS
            last_attack = start
        count = sum(e[:2] not in removed for e in events)
        report['devices'][ident] = {'before': len(events), 'after': count, 'mechanicalVetoes': vetoes}
        if ident in plan.hardware.get('states', {}):
            plan.hardware['states'][ident] = state.as_dict()
        if ident in plan.hardware.get('counters', {}):
            plan.hardware['counters'][ident]['attackRateSuppressed'] = len(events)-count
    for i, e in enumerate(plan.events):
        key = ('primary', i)
        if key in removed:
            plan.events[i] = replace(e, device_id=None, device_type=None, actual_duration=0.,
                                    sustain_added=0., outcome='DROPPED', reason='FDD_ATTACK_RATE')
        elif key in durations and abs(durations[key]-e.actual_duration) > EPS:
            plan.events[i] = replace(e, actual_duration=durations[key],
                                    sustain_added=e.sustain_added+durations[key]-e.actual_duration)
    articulation = {k: v for k, v in plan.execution_articulation.items() if not k.startswith('extra:')}
    for i, e in enumerate(plan.events):
        if ('primary', i) in removed:
            articulation.pop(e.id, None)
        elif ('primary', i) in durations and e.id in articulation:
            articulation[e.id] = {**articulation[e.id], 'gate': e.actual_duration}
    from .planning_context import extra_articulation, replace_extras
    extras, extra_art = [], {}
    for i, e in enumerate(plan.reinforcements):
        if ('extra', i) in removed:
            continue
        if ('extra', i) in durations:
            e = replace(e, duration=durations['extra', i])
        art = extra_articulation(plan, i)
        if art is not None:
            # Preserve non-FDD copies exactly, even when their source is omitted.
            extra_art[i] = ({**art, 'gate': e.duration}
                if types[e.device_id] == 'FDD' else art)
        extras.append((i, e))
    replace_extras(plan, extras, articulations=extra_art, primary=articulation)
    plan.articulation['fddAttackRate'] = report
    return report
