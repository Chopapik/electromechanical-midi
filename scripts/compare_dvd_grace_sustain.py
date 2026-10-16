"""A/B the FDD grace-attack fix with identical allocation and device settings."""
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'host'), str(ROOT/'scripts')]
from midi_source import MidiSource
from runtime.registry import DeviceRegistry
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from playback import dvd_sustain
from playback.mechanical_arrangement import _chronology
from compare_dvd_sustain import FILES, metrics


def compare():
    namespace = {'__package__': 'playback'}
    # Pin the previous, committed background policy for reproducible comparison.
    exec(subprocess.check_output(['git', 'show', 'f7bd18e:host/playback/dvd_sustain.py'], cwd=ROOT), namespace)
    result = {}
    for filename in FILES:
        registry = DeviceRegistry()
        registry.document['parameters']['arrangementPreset'] = 'instrument_roles'
        path = ROOT/'midi'/filename
        source = MidiSource(path)
        with patch.object(dvd_sustain, 'apply', namespace['apply']):
            before = arrange(source, registry)
        after = arrange(source, registry)
        for a, b in zip(before.events, after.events):
            assert replace(b, actual_duration=a.actual_duration, sustain_added=a.sustain_added) == a, a.id
            assert b.actual_duration+1e-9 >= a.actual_duration
            if a.device_type != 'DVD_SLED':
                assert a == b
        assert len(before.events) == len(after.events)
        assert before.reinforcements == after.reinforcements
        ids = {d['id'] for d in after.devices if d['type'] == 'DVD_SLED'}
        timelines = [compile_plan(p) for p in (before, after)]
        assert [c for c in timelines[0].commands if c.device_id not in ids] == [c for c in timelines[1].commands if c.device_id not in ids]
        for d in registry.devices:
            profile = registry.profile(d['id'])
            if d['enabled'] and profile:
                assert _chronology(profile, [e for e in after.events if e.played and e.device_id == d['id']],
                                   [e for e in after.reinforcements if e.device_id == d['id']]) is not None
        window = [sum(c.kind == 'stop' and c.device_id in ids and 135 <= c.time < 138 for c in t.commands)
                  for t in timelines]
        result[filename] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'before': metrics(before), 'after': metrics(after),
            'dvdStops135To138': dict(zip(('before', 'after'), window)),
            'allocationAndOtherDevicesUnchanged': True, 'physicalChronologyValid': True}
        assert result[filename]['after']['conflicts'] == 0
        assert result[filename]['before']['dropped'] == result[filename]['after']['dropped']
        print(filename, json.dumps(result[filename]), flush=True)
    assert result[FILES[0]]['dvdStops135To138']['after'] < result[FILES[0]]['dvdStops135To138']['before']
    return {'baselineCommit': 'f7bd18e', 'preset': 'instrument_roles',
            'thermalSafety': 'Unmeasured; software continuity does not establish thermal safety', 'songs': result}


if __name__ == '__main__':
    (ROOT/'reports/dvd-grace-sustain.json').write_text(json.dumps(compare(), indent=2)+'\n')
