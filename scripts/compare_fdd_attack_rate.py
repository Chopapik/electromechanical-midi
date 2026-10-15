"""Common final-pass A/B on the real Airbag MIDI; count compiled commands."""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
from midi_source import MidiSource
from runtime.registry import DeviceRegistry
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from playback.fdd_attack_rate import apply
from playback.mechanical_arrangement import _chronology

PRESETS = ('balanced', 'fdd_quality', 'fdd_quality_adaptive', 'dvd_lead_low_fdd',
           'instrument_roles', 'instrument_roles_unison', 'instrument_roles_duet')


def metrics(p):
    timeline = compile_plan(p)
    ids = {d['id'] for d in p.devices if d['type'] == 'FDD'}
    result = {}
    for start, end, label in [(0, float('inf'), 'wholeSong'), (94, 100, '94To100Seconds')]:
        lanes = {ident: [c for c in timeline.commands if c.kind == 'tone' and c.device_id == ident
                        and start <= c.time < end] for ident in ids}
        intervals = [b.time-a.time for ns in lanes.values() for a,b in zip(ns, ns[1:])]
        result[label] = {'fddAttacks': sum(map(len, lanes.values())),
                         'minAttackIntervalMs': round(min(intervals)*1000, 6) if intervals else None,
                         'intervalsBelow120Ms': sum(t < .120-1e-9 for t in intervals),
                         'fddStops': sum(c.kind == 'stop' and c.device_id in ids and start <= c.time < end
                                         for c in timeline.commands)}
    return result


def compare(path, presets):
    source = MidiSource(path)
    results = {}
    for preset in presets:
        registry = DeviceRegistry()
        registry.document['parameters']['arrangementPreset'] = preset
        with patch('playback.fdd_attack_rate.apply', return_value={}):
            before = arrange(source, registry)
        after = copy.deepcopy(before)
        report = apply(after, registry)
        ids = {d['id'] for d in after.devices if d['type'] == 'FDD'}
        other = lambda p: [c for c in compile_plan(p).commands if c.device_id not in ids]
        assert other(before) == other(after)
        for a, b in zip(before.events, after.events):
            assert (a.start, a.note, a.duration, a.track, a.channel) == (b.start, b.note, b.duration, b.track, b.channel)
            if b.played: assert a.actual_start == b.actual_start
        for d in registry.devices:
            if not d['enabled'] or d['id'] not in ids: continue
            assert _chronology(registry.profile(d['id']),
                [e for e in after.events if e.played and e.device_id == d['id']],
                [e for e in after.reinforcements if e.device_id == d['id']]) is not None
        results[preset] = {'before': metrics(before), 'after': metrics(after),
                           'nonFddCommandsUnchanged': True, 'physicalChronologyValid': True,
                           'report': report}
        assert results[preset]['after']['wholeSong']['intervalsBelow120Ms'] == 0
        print(preset, json.dumps(results[preset]), flush=True)
    return {'midi': Path(path).name, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'scope': 'same allocation, common FDD final pass; compiled REAL/VIRTUAL commands', 'presets': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('midi', nargs='?', default=str(ROOT/'midi/0032-01-radiohead_1997-airbag-[k].mid'))
    parser.add_argument('--all-presets', action='store_true')
    args = parser.parse_args()
    (ROOT/'reports/fdd-attack-rate-airbag.json').write_text(json.dumps(compare(args.midi,
        PRESETS if args.all_presets else ('balanced', 'instrument_roles_duet')), indent=2)+'\n')
