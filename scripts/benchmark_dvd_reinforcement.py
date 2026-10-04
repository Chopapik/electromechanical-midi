#!/usr/bin/env python3
"""Compare four normal DVD voices with and without acoustic reinforcement."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))

from midi_source import MidiSource  # noqa: E402
from playback.allocator import allocate  # noqa: E402
from playback.duplicates import normalize  # noqa: E402
from playback.orchestra import default_orchestra  # noqa: E402


def measure(plan) -> dict:
    report = plan.report()
    dvd = [item for item in report['devices'] if item['type'] == 'DVD_SLED']
    extras = {item['deviceId']: 0.0 for item in dvd}
    for event in plan.reinforcements:
        extras[event.device_id] += event.duration
    normal_time = sum(item['activeTime'] for item in dvd)
    extra_time = sum(event.duration for event in plan.reinforcements)
    duration = plan.duration
    return {
        'requested': report['tonal']['requested'],
        'played': report['tonal']['played'],
        'dropped': report['tonal']['dropped'],
        'dropRate': report['tonal']['dropRate'],
        'reinforcementEvents': len(plan.reinforcements),
        'reinforcementSeconds': round(extra_time, 3),
        'dvdNormalSeconds': round(normal_time, 3),
        'durationSeconds': round(duration, 3),
        'dvdDoublingPercentOfNormalWork': round(100 * extra_time / normal_time, 2)
        if normal_time else 0.0,
        'dvdUtilization': {
            item['deviceId']: {
                'normalSeconds': item['activeTime'],
                'reinforcementSeconds': round(extras[item['deviceId']], 3),
                'totalUtilization': round((item['activeTime'] + extras[item['deviceId']]) / duration, 4)
                if duration else 0.0,
            } for item in dvd
        },
    }


def summarize(songs: list[dict]) -> dict:
    result = {}
    for mode in ('independent', 'reinforcement'):
        rows = [song[mode] for song in songs]
        requested = sum(row['requested'] for row in rows)
        dropped = sum(row['dropped'] for row in rows)
        normal_seconds = sum(row['dvdNormalSeconds'] for row in rows)
        extra_seconds = sum(row['reinforcementSeconds'] for row in rows)
        duration = sum(row['durationSeconds'] for row in rows)
        device_ids = rows[0]['dvdUtilization'] if rows else {}
        result[mode] = {
            'requested': requested,
            'played': sum(row['played'] for row in rows),
            'dropped': dropped,
            'dropRate': round(dropped / requested, 4) if requested else 0.0,
            'reinforcementEvents': sum(row['reinforcementEvents'] for row in rows),
            'reinforcementSeconds': round(extra_seconds, 3),
            'dvdNormalSeconds': round(normal_seconds, 3),
            'durationSeconds': round(duration, 3),
            'dvdDoublingPercentOfNormalWork': round(100 * extra_seconds / normal_seconds, 2)
            if normal_seconds else 0.0,
            'dvdUtilization': {
                device_id: {
                    'normalSeconds': round(sum(row['dvdUtilization'][device_id]['normalSeconds']
                                               for row in rows), 3),
                    'reinforcementSeconds': round(sum(row['dvdUtilization'][device_id]['reinforcementSeconds']
                                                      for row in rows), 3),
                    'totalUtilization': round(sum(
                        row['dvdUtilization'][device_id]['normalSeconds'] +
                        row['dvdUtilization'][device_id]['reinforcementSeconds']
                        for row in rows) / duration, 4) if duration else 0.0,
                } for device_id in device_ids
            },
        }
    return result


def run(paths: list[Path]) -> dict:
    a_config = default_orchestra()
    b_config = default_orchestra(dvd_mode='reinforcement')
    assert a_config.devices == b_config.devices and a_config.policy == b_config.policy
    unique: dict[str, Path] = {}
    for path in paths:
        unique.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), path)
    songs = []
    for index, (digest, path) in enumerate(unique.items(), 1):
        print(f'[{index}/{len(unique)}] {path.name}', file=sys.stderr, flush=True)
        source = normalize(MidiSource(path))
        a = allocate(source, a_config)
        b = allocate(source, b_config)
        if ([event.as_dict() for event in a.events] != [event.as_dict() for event in b.events]
                or a.devices != b.devices or a.policy != b.policy):
            raise AssertionError(f'normal allocation changed: {path.name}')
        a_metrics, b_metrics = measure(a), measure(b)
        if any(a_metrics[key] != b_metrics[key]
               for key in ('requested', 'played', 'dropped', 'dropRate', 'dvdNormalSeconds')):
            raise AssertionError(f'normal metrics changed: {path.name}')
        songs.append({'file': path.name, 'sha256': digest,
                      'independent': a_metrics, 'reinforcement': b_metrics})
    return {
        'method': {'uniqueBy': 'SHA-256', 'normalAllocationIdentical': True,
                   'physicalAndLogicalDvdVoices': 4,
                   'doublingPercentDefinition': 'reinforcement DVD-seconds / normal DVD-seconds * 100',
                   'utilizationDefinition': '(normal + reinforcement active seconds) / song duration'},
        'filesDiscovered': len(paths), 'uniqueFilesMeasured': len(songs),
        'aggregate': summarize(songs), 'songs': songs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--midi-dir', type=Path, default=ROOT / 'midi')
    parser.add_argument('--output', type=Path, default=ROOT / 'benchmarks/dvd-reinforcement.json')
    args = parser.parse_args()
    paths = sorted(path for path in args.midi_dir.rglob('*')
                   if path.is_file() and path.suffix.lower() in ('.mid', '.midi'))
    result = run(paths)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Measured {result['uniqueFilesMeasured']} unique MIDI from "
          f"{result['filesDiscovered']} files: {args.output}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
