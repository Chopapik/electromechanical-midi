"""Offline, identical-inventory comparison of Balanced and FDD Riffs + DVD Tło."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
from midi_source import MidiSource
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.registry import DeviceRegistry
from playback.instrument_roles import PRESET


def metrics(plan):
    played = [e for e in plan.events if e.played]
    fdd = [e for e in played if e.device_type == 'FDD']
    dvd = [e for e in played if e.device_type == 'DVD_SLED']
    finish = max((e.start+e.duration for e in plan.events), default=0.)
    def merge(intervals):
        merged = []
        for start, end in sorted((max(120., a), min(finish, b)) for a, b in intervals
                                 if b > 120. and a < finish):
            if merged and start <= merged[-1][1]+1e-9:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return merged
    background = merge((e.start, e.start+e.duration) for e in plan.events
                       if e.role in ('bass', 'harmony') and e.device_type != 'VHS' and e.duration >= .65)
    dvd_ids = {d['id'] for d in plan.devices if d['type'] == 'DVD_SLED'}
    dvd_intervals = merge((c.time, c.time+c.duration) for c in compile_plan(plan).commands
                          if c.kind == 'tone' and c.device_id in dvd_ids)
    background_seconds = sum(b-a for a, b in background)
    covered = sum(max(0., min(b, d)-max(a, c)) for a, b in background for c, d in dvd_intervals)
    longest = 0.
    overlaps = 0
    for device in plan.devices:
        intervals = sorted([(e.actual_start, e.end) for e in played if e.device_id == device['id']]
                           + [(e.start, e.start+e.duration) for e in plan.reinforcements if e.device_id == device['id']])
        begin, end = 0., 0.
        for start, stop in intervals:
            overlaps += int(start < end-1e-8)
            if start > end+1e-9:
                begin = start
            end = max(end, stop)
            if device['type'] == 'DVD_SLED':
                longest = max(longest, end-begin)
    return {
        'playedTonal': sum(e.role != 'percussion' for e in played),
        'droppedTonal': sum(not e.played and e.role not in ('percussion', 'unpitched_effect') for e in plan.events),
        'fddNotes': len(fdd), 'dvdNotes': len(dvd),
        'longSourceNotesOnFdd': sum(e.duration >= .65 for e in fdd),
        'longSourceNotesOnDvd': sum(e.duration >= .65 for e in dvd),
        'fddLongestHoldSeconds': round(max((e.actual_duration for e in fdd), default=0.), 3),
        'dvdLongestContinuousSeconds': round(longest, 3),
        'overlaps': overlaps,
        'sourceLongBackgroundAfter120Seconds': round(background_seconds, 3),
        'dvdSilentDuringLongBackgroundAfter120Seconds': round(max(0., background_seconds-covered), 3),
    }


def compare(path):
    source = MidiSource(path)
    registry = DeviceRegistry()
    registry.document['parameters']['arrangementPreset'] = 'balanced'
    baseline = arrange(source, registry)
    registry.document['parameters']['arrangementPreset'] = PRESET
    experiment = arrange(source, registry)
    a, b = compile_plan(baseline), compile_plan(experiment)
    speakers = {d['id'] for d in baseline.devices if d['type'] == 'VHS'}
    unchanged_drums = [c for c in a.commands if c.kind == 'hit'] == [c for c in b.commands if c.kind == 'hit']
    unchanged_speakers = [c for c in a.commands if c.device_id in speakers] == [c for c in b.commands if c.device_id in speakers]
    result = {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'baseline': metrics(baseline), 'experiment': metrics(experiment),
              'percussionTimelineIdentical': unchanged_drums, 'speakerTimelinesIdentical': unchanged_speakers}
    if 'bodysnatchers' in path.name.lower():
        focus = [e for e in experiment.events if e.id in ('5:989', '5:990', '5:991')]
        commands = [c for c in b.commands if c.source_id in {e.id for e in focus} and c.kind == 'tone']
        assert len(focus) == len(commands) == 3
        assert all(e.device_type == 'DVD_SLED' and e.end >= e.start+e.duration-1e-8 for e in focus)
        result['backgroundTailRegression'] = [
            {'sourceId': c.source_id, 'device': c.device_id, 'start': round(c.time, 6),
             'compiledEnd': round(c.time+c.duration, 6)} for c in commands]
    assert unchanged_drums and unchanged_speakers
    assert result['experiment']['overlaps'] == 0
    assert result['experiment']['fddLongestHoldSeconds'] <= .4
    assert result['experiment']['droppedTonal'] <= result['baseline']['droppedTonal']
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('midi', type=Path, nargs='*')
    args = parser.parse_args()
    paths = args.midi or [ROOT/'midi/0080-02-radiohead_2007-bodysnatchers-[k].mid',
                         ROOT/'midi/Every breath you take.mid']
    report = {'scope': 'same inventory and settings; only arrangementPreset changes; software planning only',
              'songs': [compare(path) for path in paths]}
    (ROOT/'reports/instrument-roles.json').write_text(json.dumps(report, indent=2)+'\n')
