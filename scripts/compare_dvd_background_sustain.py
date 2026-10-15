"""Instrument Roles A/B: previous dynamic articulation vs stronger background legato."""
import json
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
from midi_source import MidiSource
from runtime.registry import DeviceRegistry
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from playback import dvd_sustain
from playback.mechanical_arrangement import _chronology
from compare_dvd_sustain import FILES, metrics


def compare():
    results = {}
    original = dvd_sustain.apply
    def dynamic_only(plan, profiles, source):
        preset = plan.policy['arrangementPreset']
        try:
            # Change articulation only, after allocation and reinforcement.
            plan.policy['arrangementPreset'] = 'balanced'
            return original(plan, profiles, source)
        finally:
            plan.policy['arrangementPreset'] = preset
    for filename in FILES:
        registry = DeviceRegistry()
        registry.document['parameters']['arrangementPreset'] = 'instrument_roles'
        registry.document['parameters']['dvdContinuousSustain'] = True
        source = MidiSource(ROOT/'midi'/filename)
        with patch.object(dvd_sustain, 'apply', dynamic_only):
            baseline = arrange(source, registry)
        experiment = arrange(source, registry)
        assert len(baseline.events) == len(experiment.events)
        for a, b in zip(baseline.events, experiment.events):
            assert replace(b, actual_duration=a.actual_duration, sustain_added=a.sustain_added) == a, a.id
            assert b.actual_duration+1e-9 >= a.actual_duration
            if a.device_type != 'DVD_SLED': assert a == b
        ids = {d['id'] for d in experiment.devices if d['type'] == 'DVD_SLED'}
        before, after = compile_plan(baseline), compile_plan(experiment)
        assert [c for c in before.commands if c.device_id not in ids] == [c for c in after.commands if c.device_id not in ids]
        assert baseline.reinforcements == experiment.reinforcements
        assert baseline.tray_events == experiment.tray_events
        result = {'baseline': metrics(baseline), 'background': metrics(experiment),
                  'allocationAndNonDvdCommandsUnchanged': True,
                  'afterTwoMinutes': {
                      'baselineDvdStops': sum(c.kind == 'stop' and c.device_id in ids and c.time >= 120 for c in before.commands),
                      'backgroundDvdStops': sum(c.kind == 'stop' and c.device_id in ids and c.time >= 120 for c in after.commands)}}
        assert result['background']['conflicts'] == 0
        assert result['background']['dropped'] == result['baseline']['dropped']
        for d in registry.devices:
            profile = registry.profile(d['id'])
            if d['enabled'] and profile:
                assert _chronology(profile, [e for e in experiment.events if e.played and e.device_id == d['id']],
                                   [e for e in experiment.reinforcements if e.device_id == d['id']]) is not None
        results[filename] = result
        print(filename, json.dumps(result), flush=True)
    return {'scope': 'same Instrument Roles allocation; only DVD articulation changes; STOP counted from ExecutionTimeline',
            'thermalSafety': 'Unknown; software timelines are not a thermal measurement', 'songs': results}


if __name__ == '__main__':
    (ROOT/'reports/dvd-background-sustain.json').write_text(json.dumps(compare(), indent=2)+'\n')
