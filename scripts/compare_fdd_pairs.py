"""Compare the two paired FDD presets against FDD Riffs + DVD Tło."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'host'), str(ROOT/'scripts')]
from midi_source import MidiSource
from runtime.registry import DeviceRegistry
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from playback.fdd_pairs import PRESETS
from playback.mechanical_arrangement import _chronology
from compare_dvd_sustain import FILES, metrics


def summary(p):
    timeline = compile_plan(p)
    ids = {d['id'] for d in p.devices if d['type'] == 'FDD'}
    tones = [c for c in timeline.commands if c.device_id in ids and c.kind == 'tone']
    result = {'fddTones': len(tones), 'fddTonesByDevice': dict(sorted(Counter(c.device_id for c in tones).items())),
              'fddWorkSeconds': round(sum(c.duration for c in tones), 6),
              'representedFddParts': len({(e.track, e.channel) for e in p.events if e.played and e.device_type == 'FDD'}),
              'dropped': sum(not e.played for e in p.events),
              'pairs': p.hardware.get('fddPairs'), 'dvd': metrics(p)}
    return result


def compare():
    result = {}
    for filename in FILES:
        registry = DeviceRegistry()
        path = ROOT/'midi'/filename
        source = MidiSource(path)
        registry.document['parameters']['arrangementPreset'] = 'instrument_roles'
        baseline = arrange(source, registry)
        ids = {d['id'] for d in baseline.devices if d['type'] == 'FDD'}
        signature = lambda p: [c for c in compile_plan(p).commands if c.device_id not in ids]
        before = signature(baseline)
        variants = {'instrument_roles': summary(baseline)}
        for preset in PRESETS:
            registry.document['parameters']['arrangementPreset'] = preset
            plan = arrange(source, registry)
            assert signature(plan) == before, (filename, preset, 'other actuator commands changed')
            assert len(baseline.events) == len(plan.events)
            original = {e.id: e for e in baseline.events}
            for e in plan.events:
                a = original[e.id]
                assert (e.start, e.duration, e.note, e.track, e.channel) == (a.start, a.duration, a.note, a.track, a.channel)
                if e.played and e.device_type == 'FDD':
                    assert e.actual_start == e.start
                    assert e.actual_duration <= .4+1e-9
            conflicts = 0
            for d in registry.devices:
                profile = registry.profile(d['id'])
                if not d['enabled'] or profile is None:
                    continue
                primaries = [e for e in plan.events if e.played and e.device_id == d['id']]
                extras = [e for e in plan.reinforcements if e.device_id == d['id']]
                assert _chronology(profile, primaries, extras) is not None, (filename, preset, d['id'])
                intervals = sorted([(e.actual_start, e.end) for e in primaries]+[(e.start, e.start+e.duration) for e in extras])
                conflicts += sum(a[1] > b[0]+1e-9 for a,b in zip(intervals, intervals[1:]))
            assert conflicts == 0
            variants[preset] = {**summary(plan), 'nonFddCommandsIdentical': True, 'conflicts': conflicts,
                                'physicalChronologyValid': True}
        result[filename] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'presets': variants}
        print(filename, json.dumps(variants), flush=True)
    return {'scope': 'same MIDI and device configuration; compiled REAL/VIRTUAL schedule; two FDD parts at once', 'songs': result}


if __name__ == '__main__':
    (ROOT/'reports/fdd-pairs.json').write_text(json.dumps(compare(), indent=2)+'\n')
