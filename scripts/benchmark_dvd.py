#!/usr/bin/env python3
"""Compare the same normalized MIDI on seven versus eleven virtual voices.

Usage: .venv/bin/python scripts/benchmark_dvd.py [song.mid ...]
The JSON output is reproducible and contains only measurements from local MIDI.
"""
from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))

from midi_source import MidiSource  # noqa: E402
from playback.allocator import allocate  # noqa: E402
from playback.duplicates import normalize  # noqa: E402
from playback.orchestra import default_orchestra  # noqa: E402

DEFAULT_SONGS = (
    'midi/0087-09-radiohead_2007-jigsaw_falling_into_place.mid',
    'midi/0002-02-radiohead_1993-creep-[k].mid',
    'midi/0063-01-radiohead_2003-2+2=5-[k].mid',
)


def measure(source, dvd_count: int) -> dict:
    plan = allocate(source, default_orchestra(dvd_count=dvd_count))
    report = plan.report()
    devices = report['devices']
    return {
        'deviceCount': len(plan.devices),
        'requested': report['totals']['requested'],
        'played': report['totals']['played'],
        'dropped': report['totals']['dropped'],
        'dropRate': report['totals']['dropRate'],
        'tonalRequested': report['tonal']['requested'],
        'tonalDropped': report['tonal']['dropped'],
        'reassigned': report['totals']['reassigned'],
        'delayed': report['totals']['delayed'],
        'arpeggiated': report['totals']['arpeggiated'],
        'voiceSteals': report['totals']['voiceSteals'],
        'shortened': report['totals']['shortened'],
        'accompanimentContinuity': report['continuity']['accompanimentContinuity'],
        'totalTonalSilenceSeconds': report['continuityTonal']['orchestraSilentTime'],
        'longSilentGaps': report['continuityTonal']['longGapCount'],
        'fddUtilization': {item['deviceId']: item['utilization'] for item in devices
                           if item['type'] == 'FDD'},
        'dvdUtilization': {item['deviceId']: item['utilization'] for item in devices
                           if item['type'] == 'DVD_SLED'},
        'dvdEvents': {item['deviceId']: item['notes'] for item in devices
                      if item['type'] == 'DVD_SLED'},
        'vhsUtilization': {item['deviceId']: item['utilization'] for item in devices
                           if item['type'] == 'VHS'},
        'nonLeadVhsEvents': report['leadDevices']['nonLeadEvents'],
        'leadRequested': report['lead']['requested'],
        'leadPlayed': report['lead']['played'],
        'leadDropped': report['lead']['dropped'],
    }


def main(paths: list[str]) -> int:
    results = {}
    for song in paths or DEFAULT_SONGS:
        path = Path(song)
        if not path.is_file():
            results[song] = {'error': 'local MIDI file missing'}
            continue
        source = normalize(MidiSource(path))
        results[path.name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                              'seven': measure(source, 0),
                              'eleven': measure(source, 4)}
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
