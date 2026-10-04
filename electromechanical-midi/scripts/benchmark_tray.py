#!/usr/bin/env python3
"""Unique MIDI: historical inventory, target inventory, and isolated DVD 3/4."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from midi_source import MidiSource
from playback.allocator import allocate
from playback.duplicates import normalize
from playback.orchestra import default_orchestra
from benchmark_dvd_reinforcement import measure, summarize


def run(directory):
    paths = sorted(p for p in directory.rglob('*') if p.suffix.lower() in ('.mid', '.midi'))
    unique = {}
    for path in paths:
        unique.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), path)
    songs = []
    for index, (digest, path) in enumerate(unique.items(), 1):
        print(f'[{index}/{len(unique)}] {path.name}', file=sys.stderr, flush=True)
        source = normalize(MidiSource(path))
        configs = {
            'before': default_orchestra(fdd_count=3, hdd_count=3, tray_count=0, dvd_mode='reinforcement'),
            'after': default_orchestra(dvd_mode='reinforcement'),
            'afterTrayOff': default_orchestra(dvd_mode='reinforcement', tray_enabled=False),
            'oneTray': default_orchestra(tray_count=1, dvd_mode='reinforcement'),
            'threeDvd': default_orchestra(dvd_count=3, dvd_mode='reinforcement'),
        }
        plans = {name: allocate(source, config) for name, config in configs.items()}
        assert [e.as_dict() for e in plans['after'].events] == [e.as_dict() for e in plans['afterTrayOff'].events], path
        assert plans['after'].reinforcements == plans['afterTrayOff'].reinforcements, path
        row = {'file': path.name, 'sha256': digest}
        for name, plan in plans.items():
            report = plan.report()
            row[name] = {**measure(plan), 'percussion': report['percussion'],
                         'tray': plan.tray_report, 'continuity': report['continuity']}
        songs.append(row)
    aggregate = {}
    for mode in ('before', 'after', 'afterTrayOff', 'threeDvd', 'oneTray'):
        rows = [s[mode] for s in songs]
        # Reuse the existing duration-weighted DVD metrics aggregator.
        aggregate[mode] = summarize([{'independent': r, 'reinforcement': r} for r in rows])['reinforcement']
        trays = [r['tray'] for r in rows]
        seconds = sum(r['durationSeconds'] for r in rows)
        aggregate[mode]['tray'] = {k: sum(r[k] for r in trays) for k in
            ('candidates', 'played', 'skippedBusyCooldown', 'skippedSampled', 'skippedSourceDropped', 'skippedDisabled')}
        ids = {i for r in trays for i in r['devices']}
        aggregate[mode]['tray']['devices'] = {i: {
            'events': sum(r['devices'].get(i, {}).get('events', 0) for r in trays),
            'activeTime': round(sum(r['devices'].get(i, {}).get('activeTime', 0) for r in trays), 3),
            'utilization': round(sum(r['devices'].get(i, {}).get('activeTime', 0) for r in trays) / seconds, 4)
        } for i in sorted(ids)}
        gm = {i for r in trays for i in r['gmNotes']}
        aggregate[mode]['tray']['gmNotes'] = {i: sum(r['gmNotes'].get(i, 0) for r in trays) for i in sorted(gm)}
        aggregate[mode]['percussionEvents'] = sum(r['percussion']['requested'] for r in rows)
    return {'filesDiscovered': len(paths), 'uniqueFilesMeasured': len(songs),
            'normalTrayAllocationIdentical': True,
            'method': 'Before already had 4 DVD. Before/after adds FDD4/HDD4/trays; threeDvd isolates DVD3/4 with other settings identical. Trays copy only played GM events.',
            'aggregate': aggregate, 'songs': songs}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--midi-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'benchmarks/dvd-tray.json')
    args = parser.parse_args()
    result = run(args.midi_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
