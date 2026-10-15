"""Compare the same inventory with and without GM noise separation.

Usage: .venv/bin/python scripts/compare_unpitched_effects.py /path/to/Avicii_Levels.mid
No hardware is opened. The MIDI is not copied into the repository.
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from midi_source import MidiSource
from playback import sound_roles
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.registry import DeviceRegistry


def summarize(plan, effect_ids):
    timeline = compile_plan(plan)
    noise = [e for e in plan.events if e.id in effect_ids]
    conflicts = 0
    for device in plan.devices:
        intervals = sorted(
            [(e.actual_start, e.end) for e in plan.events if e.played and e.device_id == device['id']]
            + [(e.start, e.start + e.duration) for e in plan.reinforcements if e.device_id == device['id']])
        end = 0.
        for start, stop in intervals:
            conflicts += int(start < end - 1e-8)
            end = max(end, stop)
    return {
        'noiseTriggersPlayedAsTones': sum(e.played for e in noise),
        'noiseToneCommands': sum(c.kind == 'tone' and c.source_id in effect_ids for c in timeline.commands),
        'noiseTriggersExplicitlyOmitted': sum(e.reason == sound_roles.UNSUPPORTED_EFFECT for e in plan.events),
        'tonalNotesPlayed': sum(e.played and e.id not in effect_ids and e.role != 'percussion' for e in plan.events),
        'tonalNotesDropped': sum(not e.played and e.id not in effect_ids and e.role != 'percussion' for e in plan.events),
        'percussionHitsPlayed': sum(e.played and e.role == 'percussion' for e in plan.events),
        'noiseRouting': dict(Counter(e.device_type for e in noise if e.played)),
        'overlapConflicts': conflicts,
        'highlightedEvents': {
            ident: {key: e.as_dict()[key] for key in ('start', 'deviceId', 'playedHz', 'outcome', 'reason')}
            for ident in ('10:1', '8:1', '15:2') if ident in effect_ids
            for e in plan.events if e.id == ident},
    }


def compare(path):
    source = MidiSource(path)
    effect_ids = set(sound_roles.source_effects(source))
    registry = DeviceRegistry()
    with patch.dict(sound_roles.GM_NOISE, {}, clear=True):
        baseline = arrange(source, registry)
    experiment = arrange(source, registry)
    before, after = summarize(baseline, effect_ids), summarize(experiment, effect_ids)
    assert after['noiseToneCommands'] == 0
    assert after['overlapConflicts'] == 0
    assert compile_plan(experiment) == compile_plan(arrange(source, registry))
    if not effect_ids:
        assert compile_plan(baseline) == compile_plan(experiment)
    baseline_played = {e.id: e for e in baseline.events if e.played and e.id not in effect_ids
                       and e.role != 'percussion'}
    newly_dropped = [{'id': e.id, 'time': round(e.start, 6), 'reason': e.reason,
                      'previousDevice': baseline_played[e.id].device_id}
                     for e in experiment.events if not e.played and e.id in baseline_played]
    result = {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'sourceNoiseTriggers': len(effect_ids), 'baseline': before, 'experiment': after,
              'tonalDropDelta': after['tonalNotesDropped'] - before['tonalNotesDropped'],
              'newlyDroppedTonalNotes': newly_dropped}
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('midi', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/levels-unpitched-effects.json')
    args = parser.parse_args()
    controls = [ROOT / 'midi/Every breath you take.mid', ROOT / 'midi/One_Republic_Counting_stars.mid']
    report = {'scope': 'identical registry and policy; baseline disables GM noise classification; planned, not measured',
              'benchmark': compare(args.midi),
              'controls': [compare(path) for path in controls if path.exists()]}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
