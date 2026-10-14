"""Same inventory/policy A/B; actuator metrics from compiled ExecutionTimeline."""
import json
import sys
from pathlib import Path
from dataclasses import replace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
from midi_source import MidiSource
from runtime.registry import DeviceRegistry
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from playback.mechanical_arrangement import _chronology

FILES = ['0080-02-radiohead_2007-bodysnatchers-[k].mid', 'Every breath you take.mid']


def metrics(plan):
    timeline = compile_plan(plan)
    ids = {d['id'] for d in plan.devices if d['type'] == 'DVD_SLED'}
    work = silence = longest = 0.
    stops = 0
    for ident in sorted(ids):
        start = end = None
        for c in timeline.commands:
            if c.device_id != ident: continue
            if c.kind == 'tone' and start is None:
                if end is not None: silence += c.time-end
                start = c.time
            elif c.kind == 'stop':
                stops += 1
                if start is not None:
                    work += c.time-start
                    longest = max(longest, c.time-start)
                    start = None
                end = c.time
    conflicts = 0
    for d in plan.devices:
        intervals = sorted([(e.actual_start,e.end) for e in plan.events if e.played and e.device_id == d['id']]
                           + [(e.start,e.start+e.duration) for e in plan.reinforcements if e.device_id == d['id']])
        conflicts += sum(a[1] > b[0]+1e-8 for a,b in zip(intervals,intervals[1:]))
    return dict(dvdNotes=sum(e.played and e.device_type=='DVD_SLED' for e in plan.events),
                dvdStops=stops, dvdWorkSeconds=round(work,6), dvdSilenceSeconds=round(silence,6),
                dvdLongestContinuousSeconds=round(longest,6), dropped=sum(not e.played for e in plan.events),
                conflicts=conflicts, bridges=plan.articulation.get('dvdContinuousSustain', {}),
                dvdReinforcements=sum(e.device_id in ids for e in plan.reinforcements))


def compare():
    result = {}
    for filename in FILES:
        registry = DeviceRegistry()
        registry.document['parameters']['mechanicalAware'] = True
        registry.document['parameters']['arrangementPreset'] = 'balanced'
        source = MidiSource(ROOT/'midi'/filename)
        registry.document['parameters']['dvdContinuousSustain'] = False
        baseline = arrange(source, registry)
        registry.document['parameters']['dvdContinuousSustain'] = True
        experiment = arrange(source, registry)
        assert len(baseline.events) == len(experiment.events)
        for a,b in zip(baseline.events,experiment.events):
            assert replace(b, actual_duration=a.actual_duration, sustain_added=a.sustain_added) == a, a.id
            if a.device_type != 'DVD_SLED': assert a == b
        assert baseline.reinforcements == experiment.reinforcements
        assert baseline.tray_events == experiment.tray_events
        after = metrics(experiment)
        assert after['conflicts'] == 0
        for d in registry.devices:
            profile = registry.profile(d['id'])
            if d['enabled'] and profile:
                assert _chronology(profile,[e for e in experiment.events if e.played and e.device_id==d['id']],
                                   [e for e in experiment.reinforcements if e.device_id==d['id']]) is not None
        result[filename] = {'baseline': metrics(baseline), 'experiment': after,
                            'primaryDecisionsPreserved': True, 'otherDevicesAndExtrasUnchanged': True,
                            'physicalChronologyValid': True}
        print(filename, json.dumps(result[filename]), flush=True)
    return {'inventory': DeviceRegistry().devices, 'parameters': registry.document['parameters'],
            'metricScope': 'DVD work and silence summed across actuators; silence excludes leading/trailing rests; longest is one actuator; STOP from compiled timeline including reinforcement',
            'thermalSafety': 'Unknown; software is not physical motor verification', 'songs': result}

if __name__ == '__main__':
    (ROOT/'reports/dvd-sustain-comparison.json').write_text(json.dumps(compare(), indent=2)+'\n')
