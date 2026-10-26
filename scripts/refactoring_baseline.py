"""Capture/verify exact, offline planner behaviour for staged refactoring.

  .venv/bin/python scripts/refactoring_baseline.py --capture /tmp/baseline.jsonl.gz
  .venv/bin/python scripts/refactoring_baseline.py --verify /tmp/baseline.jsonl.gz

The default manifest uses fixed 48-second prefixes of five named local MIDI files and
two reproducible synthetic files. No hardware/output/service is instantiated.
An optional JSON --manifest is a list of {id, path, sha256} or
{id, fixture, sha256}; fixture names are "phrases" and "percussion". Paths are
relative to that manifest, or absolute. Missing/changed files fail before planning.

Every AUTO case uses every backend preset. The phrases fixture additionally
exercises STRICT_TRACKS and disabled partners. Output is JSON lines (optionally
gzip), retaining complete commands so verification prints the first difference.
Only explicitly listed diagnostic fields and elapsed planning time are excluded
from equality. Floating-point execution data is neither rounded nor tolerated.
Speaker preferences are isolated: empty by default, optionally copied from
--speaker-settings; verification reuses the frozen copy unless explicitly given.
The tool never updates an existing baseline or any application preferences.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from fnmatch import fnmatchcase
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))

import mido
from midi_source import MidiSource
from arrangement_presets import PRESET_IDS
from playback.orchestra import parse_policy
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.registry import DeviceRegistry

SCHEMA = 1
DIAGNOSTIC_FIELDS = (
    'PerformanceEvent.hardware', 'PerformancePlan.hardware',
    'PerformancePlan.analysis', 'PerformancePlan.source_ref',
    'PerformancePlan.duplicates', 'PerformancePlan.articulation',
    'PerformancePlan.idle_report', 'PerformancePlan.expression',
    'PerformancePlan.strict_report', 'planningSeconds', 'local paths',
    'git/tool versions',
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def supported_presets():
    """Use the shared public catalog, retaining the frozen backend order."""
    for preset in PRESET_IDS:
        parse_policy({'arrangementPreset': preset})
    return list(PRESET_IDS)


def fixture_bytes(name):
    """Small fixed files cover repeats, rests, tempo, polyphony, CC and drums."""
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    tempo = mido.MidiTrack()
    tempo.extend([mido.MetaMessage('set_tempo', tempo=500000),
                  mido.MetaMessage('set_tempo', tempo=400000, time=3840)])
    midi.tracks.append(tempo)
    if name == 'phrases':
        tracks = [('Melody', 0, 0, [(i*240, 110, 60+i%4) for i in range(12)]
                    + [(3840, 900, 67), (5040, 900, 64)]),
                  ('Bass', 1, 33, [(i*960, 850, 36+i%3) for i in range(6)]),
                  ('Pad', 2, 89, [(0, 3000, n) for n in (48, 55, 60)]
                    + [(3840, 1920, n) for n in (50, 57, 62)])]
    elif name == 'percussion':
        tracks = [('Drums', 9, 0, [(i*40, 20, (36, 38, 42, 46)[i%4]) for i in range(120)]),
                  ('Melody', 0, 0, [(i*480, 400, 60+i%5) for i in range(12)])]
    else:
        raise ValueError('Unknown fixture: ' + name)
    for title, channel, program, notes in tracks:
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.extend([mido.MetaMessage('track_name', name=title),
                      mido.Message('program_change', channel=channel, program=program)])
        events = [(0, 0, mido.Message('control_change', channel=channel, control=11, value=100))]
        for tick, duration, note in notes:
            events.extend([(tick, 1, mido.Message('note_on', channel=channel, note=note, velocity=95)),
                           (tick+duration, 0, mido.Message('note_off', channel=channel, note=note))])
        previous = 0
        for tick, _, message in sorted(events, key=lambda row: (row[0], row[1])):
            track.append(message.copy(time=tick-previous))
            previous = tick
    stream = io.BytesIO()
    midi.save(file=stream)
    return stream.getvalue()


def default_manifest():
    music = Path.home() / 'Music/MIDI'
    files = [
        ('bodysnatchers', music / 'radiohead-midi/0080-02-radiohead_2007-bodysnatchers-[k].mid'),
        ('somebody', music / 'gotye-somebody_that_i_used_to_know.mid'),
        ('no-surprises', music / 'radiohead-midi/0041-10-radiohead_1997-no_surprises-[k].mid'),
        ('long-background-national-anthem', music / 'radiohead-midi/0046-03-radiohead_2000-the_national_anthem.mid'),
        ('dense-drums-counting-stars', music / 'One_Republic_Counting_stars.mid'),
    ]
    rows = []
    for name, path in files:
        data = path.read_bytes()
        rows.append({'id': name, 'path': str(path),
                     'sha256': hashlib.sha256(data).hexdigest(), 'excerptSeconds': 48,
                     'excerptSha256': hashlib.sha256(prefix_bytes(data, 48)).hexdigest()})
    rows.extend({'id': 'fixture-'+name, 'fixture': name,
                 'sha256': hashlib.sha256(fixture_bytes(name)).hexdigest()}
                for name in ('phrases', 'percussion'))
    return rows


def prefix_bytes(data, seconds):
    """Keep an explicit prefix with original timing/CC/programs and close gates.

    The source SHA and this derived file's SHA are both frozen in the manifest.
    This is a benchmark fixture transformation, never an application MIDI edit.
    """
    midi = mido.MidiFile(file=io.BytesIO(data))
    tempos = {0: 500000}
    for track in midi.tracks:
        tick = 0
        for message in track:
            tick += message.time
            if message.type == 'set_tempo':
                tempos[tick] = message.tempo
    previous = 0
    remaining = seconds
    tempo = tempos[0]
    for tick, following_tempo in sorted(tempos.items()):
        elapsed = mido.tick2second(tick-previous, midi.ticks_per_beat, tempo)
        if elapsed > remaining:
            break
        remaining -= elapsed
        previous, tempo = tick, following_tempo
    cutoff = previous+round(mido.second2tick(remaining, midi.ticks_per_beat, tempo))
    for index, track in enumerate(midi.tracks):
        kept = mido.MidiTrack()
        active = {}
        tick = last = 0
        for message in track:
            tick += message.time
            if tick > cutoff:
                break
            if message.type == 'end_of_track':
                continue
            kept.append(message.copy(time=tick-last))
            last = tick
            if message.type in ('note_on', 'note_off'):
                key = (message.channel, message.note)
                if message.type == 'note_on' and message.velocity:
                    active[key] = active.get(key, 0)+1
                elif active.get(key, 0):
                    active[key] -= 1
        for (channel, note), count in sorted(active.items()):
            for _ in range(count):
                kept.append(mido.Message('note_off', channel=channel, note=note, time=cutoff-last))
                last = cutoff
        kept.append(mido.MetaMessage('end_of_track', time=cutoff-last))
        midi.tracks[index] = kept
    result = io.BytesIO()
    midi.save(file=result)
    return result.getvalue()


def read_manifest(path):
    rows = json.loads(path.read_text())
    for row in rows:
        if 'path' in row:
            row['path'] = str((path.parent / row['path']).resolve())
    return rows


def resolve_sources(manifest, directory):
    if not manifest or len({row['id'] for row in manifest}) != len(manifest):
        raise ValueError('Manifest requires nonempty, unique source IDs')
    result = []
    for row in manifest:
        if ('path' in row) == ('fixture' in row):
            raise ValueError('Source must have exactly one path or fixture: ' + row['id'])
        data = Path(row['path']).read_bytes() if 'path' in row else fixture_bytes(row['fixture'])
        actual = hashlib.sha256(data).hexdigest()
        if actual != row['sha256']:
            raise ValueError(f"Source SHA mismatch for {row['id']}: expected {row['sha256']}, got {actual}")
        if 'excerptSeconds' in row:
            data = prefix_bytes(data, row['excerptSeconds'])
            if hashlib.sha256(data).hexdigest() != row['excerptSha256']:
                raise ValueError('Derived excerpt SHA mismatch for '+row['id'])
        # Preserve the input stem: classifiers may inspect source metadata/name.
        path = directory / str(len(result)) / (Path(row['path']).name if 'path' in row else row['id']+'.mid')
        path.parent.mkdir()
        path.write_bytes(data)
        result.append((row, MidiSource(path)))
    return result


def configuration_snapshot(preferences, volume_path):
    registry = DeviceRegistry(volume_path=volume_path)
    profiles = {str(p.relative_to(ROOT)): json.loads(p.read_text())
                for p in sorted((ROOT/'config/hardware-profiles').glob('*.json'))}
    value = {'registry': registry.document, 'hardwareProfiles': profiles,
             'speakerPreferences': preferences}
    return {'values': value, 'fingerprint': digest(value)}


def git(command):
    return subprocess.check_output(['git', *command], cwd=ROOT, text=True).strip()


def first_difference(expected, actual, path='$'):
    """Return the first exact leaf difference, including its list index."""
    if type(expected) is not type(actual):
        return f'{path}: expected {expected!r}, got {actual!r}'
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            return f'{path}: keys expected {list(expected)}, got {list(actual)}'
        for key in expected:
            found = first_difference(expected[key], actual[key], path+'.'+key)
            if found:
                return found
    elif isinstance(expected, list):
        for i, (left, right) in enumerate(zip(expected, actual)):
            found = first_difference(left, right, f'{path}[{i}]')
            if found:
                return found
        if len(expected) != len(actual):
            index = min(len(expected), len(actual))
            left = expected[index] if index < len(expected) else '<missing>'
            right = actual[index] if index < len(actual) else '<missing>'
            return f'{path}[{index}]: expected {left!r}, got {right!r} (length {len(expected)} vs {len(actual)})'
    elif isinstance(expected, float):
        if expected.hex() != actual.hex():
            return f'{path}: expected {expected!r}, got {actual!r}'
    elif expected != actual:
        return f'{path}: expected {expected!r}, got {actual!r}'
    return None


def plan_record(plan):
    events = [asdict(event) for event in plan.events]
    diagnostics = [event.pop('hardware') for event in events]
    return {
        'execution': {'events': events, 'reinforcements': [asdict(e) for e in plan.reinforcements],
                      'executionArticulation': plan.execution_articulation,
                      'policy': plan.policy, 'devices': plan.devices,
                      'leadDevices': list(plan.lead_devices), 'dvdMode': plan.dvd_mode,
                      'idleReinforcement': plan.idle_reinforcement,
                      'timeline': compile_plan(plan).as_dict()},
        'diagnostics': {'eventHardware': diagnostics,
                        'hardwareKeys': sorted(plan.hardware),
                        'sourceEventCount': len(events)},
    }


def cases(sources, presets):
    for row, source in sources:
        for preset in presets:
            yield row['id']+'/'+preset+'/AUTO', source, preset, 'AUTO'
        if row.get('fixture') == 'phrases':
            for variant in ('STRICT_TRACKS', 'DISABLED_PARTNERS'):
                for preset in presets:
                    yield row['id']+'/'+preset+'/'+variant, source, preset, variant


def execute_case(source, preset, variant, volume_path):
    registry = DeviceRegistry(volume_path=volume_path)
    registry.document['parameters']['arrangementPreset'] = preset
    if variant == 'STRICT_TRACKS':
        registry.document['routing'] = {'mode': 'STRICT_TRACKS', 'tracks': [1, 2, 3, None]}
    elif variant == 'DISABLED_PARTNERS':
        for ident in ('fdd-2', 'fdd-4', 'fdd-6', 'fdd-8', 'DVD_STEPPER_4'):
            if ident in registry.by_id:
                registry.by_id[ident]['enabled'] = False
                registry.by_id[ident]['realEnabled'] = False
    started = monotonic()
    record = plan_record(arrange(source, registry))
    # A JSON round trip normalizes tuples to lists without changing any floats.
    record = json.loads(json.dumps(record, allow_nan=False))
    record['diagnostics']['planningSeconds'] = monotonic()-started
    record['fingerprint'] = digest(record['execution'])
    return record


def open_records(path, mode):
    return gzip.open(path, mode+'t', encoding='utf-8') if path.suffix == '.gz' else path.open(mode, encoding='utf-8')


def run(path, *, verify=False, manifest=None, preferences=None, presets=None,
        only_cases=None, only_presets=None, progress=print):
    """Only captures on explicit request; verify never replaces the baseline."""
    if verify:
        with open_records(path, 'r') as stream:
            metadata = json.loads(next(stream))
        if metadata['schema'] != SCHEMA:
            raise ValueError('Unsupported baseline schema')
        if manifest is None:
            manifest = metadata['manifest']
        if preferences is None:
            preferences = metadata['configuration']['values']['speakerPreferences']
        if presets is None:
            presets = metadata['presets']
    elif path.exists():
        raise FileExistsError('Refusing to overwrite baseline: '+str(path))
    if not verify and (only_cases or only_presets):
        raise ValueError('Case/preset filters are only available during verification')
    manifest = manifest if manifest is not None else default_manifest()
    preferences = preferences if preferences is not None else {}
    catalog = supported_presets()
    presets = presets if presets is not None else catalog
    if len(set(presets)) != len(presets) or not presets or set(presets)-set(catalog):
        raise ValueError('Invalid preset selection')
    with tempfile.TemporaryDirectory(prefix='orchestra-baseline-') as temporary:
        directory = Path(temporary)
        volume_path = directory/'speaker-settings.json'
        volume_path.write_text(json.dumps(preferences))
        sources = resolve_sources(manifest, directory)
        config = configuration_snapshot(preferences, volume_path)
        contract = {'catalog': catalog, 'presets': presets, 'configuration': config,
                    'sources': [{key: row[key] for key in ('id', 'sha256', 'excerptSeconds', 'excerptSha256') if key in row}
                                for row in manifest]}
        if verify:
            diff = first_difference(metadata['contract'], contract)
            if diff:
                raise ValueError('Baseline input changed: '+diff)
        else:
            metadata = {'schema': SCHEMA, 'manifest': manifest, 'presets': presets,
                        'configuration': config, 'contract': contract,
                        'excludedFromEquality': DIAGNOSTIC_FIELDS,
                        'provenance': {'git': git(['rev-parse', 'HEAD']),
                                       'workingTree': git(['status', '--short']),
                                       'python': platform.python_version(),
                                       'mido': mido.version_info.__str__()}}
        count = 0
        # Inputs are validated before creating a capture file. Failure during
        # planning leaves a .partial file, never a seemingly complete baseline.
        partial = path.with_name(path.name+'.partial.gz' if path.suffix == '.gz' else path.name+'.partial')
        output = path if verify else partial
        if not verify:
            path.parent.mkdir(parents=True, exist_ok=True)
        with open_records(output, 'r' if verify else 'w') as stream:
            if verify:
                next(stream)
            else:
                stream.write(json.dumps(metadata, allow_nan=False)+'\n')
            for ident, source, preset, variant in cases(sources, presets):
                if verify:
                    line = stream.readline()
                    if not line:
                        raise ValueError('Baseline is missing case '+ident)
                    expected = json.loads(line)
                    diff = first_difference(expected['case'], ident, '$.case')
                    if diff:
                        raise ValueError(diff)
                    if ((only_cases and not any(fnmatchcase(ident, pattern) for pattern in only_cases))
                            or only_presets and preset not in only_presets):
                        continue
                actual = {'case': ident, **execute_case(source, preset, variant, volume_path)}
                if verify:
                    diff = diff or first_difference(expected['execution'], actual['execution'])
                    if diff:
                        command = re.search(r'\$\.timeline\.commands\[(\d+)\]', diff)
                        if command:
                            index = int(command[1])
                            for label, value in [('Expected', expected), ('Actual', actual)]:
                                commands = value['execution']['timeline']['commands']
                                diff += '\n'+label+' command: '+json.dumps(commands[index] if index < len(commands) else '<missing>')
                        raise ValueError(ident+': '+diff)
                else:
                    stream.write(json.dumps(actual, allow_nan=False, separators=(',', ':'))+'\n')
                count += 1
                progress(f'{count}: {ident} OK ({actual["diagnostics"]["planningSeconds"]:.2f}s)')
            if verify and stream.readline():
                raise ValueError('Baseline contains unexpected additional cases')
            if not count:
                raise ValueError('No cases matched the verification filters')
        if not verify:
            partial.rename(path)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--capture', type=Path)
    mode.add_argument('--verify', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--speaker-settings', type=Path)
    parser.add_argument('--case', action='append', dest='only_cases',
                        help='Verify only matching case glob(s), e.g. fixture-*/*/AUTO')
    parser.add_argument('--preset', action='append', dest='only_presets',
                        help='Verify only selected preset(s); may be repeated')
    args = parser.parse_args()
    try:
        count = run(args.verify or args.capture, verify=args.verify is not None,
                    manifest=read_manifest(args.manifest) if args.manifest else None,
                    preferences=json.loads(args.speaker_settings.read_text()) if args.speaker_settings else None,
                    only_cases=args.only_cases, only_presets=args.only_presets,
                    progress=lambda message: print(message, flush=True))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'Baseline failed: {error}\n')
    print(f'{"Verified" if args.verify else "Captured"} {count} cases; no hardware accessed.')


if __name__ == '__main__':
    main()
