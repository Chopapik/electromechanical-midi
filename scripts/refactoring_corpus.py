"""Offline full-corpus guard for shared planner refactoring.

Capture using frozen host/config/scripts copied to /tmp before production edits:
  .venv/bin/python /tmp/SNAPSHOT/scripts/refactoring_corpus.py --capture REPORT \
    --midi-dir ~/Music/MIDI --midi-dir /absolute/repo/midi --workers 3
Verify with current code:
  .venv/bin/python scripts/refactoring_corpus.py --verify REPORT --workers 3

Every SHA-unique source is processed with universal, fdd_expressive and
adaptive_legato. Digests cover the COMPLETE unrounded execution projection used
by refactoring_baseline.py, including primary decisions and sidecars, extras,
device/policy data and ordered compiler commands. Diagnostic/timing data and
code provenance are excluded. Preferences are isolated and frozen as {}.

Unlike the 117-case small baseline, this report stores digests, not full plans.
If a digest differs, this tool identifies source/preset; use --dump-case with
both frozen and current code to save complete projections and locate the first
differing command with refactoring_baseline.first_difference. The frozen source
directory is local /tmp state: preserve it separately if later diagnosis needs
to survive system cleanup. Missing/changed original MIDI fails without fallback.
No transport, output, service, power or actuator is instantiated.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
from refactoring_baseline import (DeviceRegistry, MidiSource, arrange, configuration_snapshot,
                                  digest, first_difference, git, plan_record, supported_presets)

PRESETS = ('universal', 'fdd_expressive', 'adaptive_legato')


def collect(directories):
    paths = {}
    count = 0
    for directory in directories:
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        for path in sorted(directory.rglob('*')):
            if path.is_file() and path.suffix.lower() in ('.mid', '.midi'):
                count += 1
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                paths.setdefault(sha, []).append(str(path.resolve()))
    return count, [{'sha256': sha, 'path': aliases[0], 'aliases': aliases}
                   for sha, aliases in sorted(paths.items())]


def validate_manifest(rows):
    if not rows or len({row['sha256'] for row in rows}) != len(rows):
        raise ValueError('Corpus manifest must contain unique, nonempty SHA entries')
    for row in rows:
        actual = hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()
        if actual != row['sha256']:
            raise ValueError('Source SHA mismatch: '+row['path'])


def measure(row, dump_preset=None):
    started = monotonic()
    try:
        source = MidiSource(Path(row['path']))
    except Exception as error:
        return {'sha256': row['sha256'], 'parseError': type(error).__name__+': '+str(error)}
    values = {}
    with tempfile.TemporaryDirectory(prefix='orchestra-corpus-') as temporary:
        volume_path = Path(temporary)/'isolated-speaker-settings.json'
        volume_path.write_text('{}')
        for preset in (dump_preset,) if dump_preset else PRESETS:
            registry = DeviceRegistry(volume_path=volume_path)
            registry.document['parameters']['arrangementPreset'] = preset
            try:
                execution = plan_record(arrange(source, registry))['execution']
                values[preset] = execution if dump_preset else digest(execution)
            except Exception as error:
                return {'sha256': row['sha256'], 'planningError': preset+': '+repr(error)}
    return {'sha256': row['sha256'], 'presets': values,
            'planningSeconds': monotonic()-started}


def current_configuration():
    with tempfile.TemporaryDirectory(prefix='orchestra-corpus-config-') as temporary:
        path = Path(temporary)/'speakers.json'
        path.write_text('{}')
        return configuration_snapshot({}, path)


def save_report(path, report):
    partial = path.with_suffix(path.suffix+'.partial')
    partial.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    partial.replace(path)


def run(path, *, verify=False, directories=(), workers=3):
    if verify:
        report = json.loads(path.read_text())
        if report['schema'] != 1 or report['presets'] != list(PRESETS):
            raise ValueError('Unsupported corpus schema/preset set')
        manifest = report['manifest']
    else:
        if path.exists():
            raise FileExistsError('Refusing to overwrite corpus report: '+str(path))
        path_count, manifest = collect(directories)
        report = {'schema': 1, 'scope': 'exact complete planning digests; offline only',
                  'presets': list(PRESETS), 'paths': path_count, 'manifest': manifest,
                  'configuration': current_configuration(),
                  'provenance': {'sourceRoot': str(ROOT), 'git': git(['rev-parse', 'HEAD'])
                                 if (ROOT/'.git').exists() else 'frozen local snapshot'},
                  'songs': []}
        path.parent.mkdir(parents=True, exist_ok=True)
    validate_manifest(manifest)
    if any(preset not in supported_presets() for preset in PRESETS):
        raise ValueError('A guarded preset is missing from the backend')
    diff = first_difference(report['configuration'], current_configuration())
    if diff:
        raise ValueError('Corpus configuration changed: '+diff)
    expected = {song['sha256']: song for song in report['songs']}
    measured = []
    failures = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(measure, row): row for row in manifest}
        for job in as_completed(jobs):
            row = jobs[job]
            try:
                result = job.result()
            except Exception as error:
                result = {'sha256': row['sha256'], 'planningError': repr(error)}
            measured.append(result)
            status = result.get('parseError', result.get('planningError', 'OK'))
            if verify:
                before = {k: v for k, v in expected.get(row['sha256'], {}).items() if k != 'planningSeconds'}
                after = {k: v for k, v in result.items() if k != 'planningSeconds'}
                diff = first_difference(before, after)
                if diff:
                    failures.append(row['sha256']+': '+diff)
                    status = 'DIFFERENT '+diff
            elif 'planningError' in result:
                failures.append(row['sha256']+': '+result['planningError'])
            print(f'{len(measured)}/{len(manifest)} {Path(row["path"]).name}: {status}', flush=True)
    if verify:
        if failures:
            raise ValueError(f'{len(failures)} corpus differences. First: '+failures[0]+
                             '\nUse --dump-case SHA/PRESET --dump-output PATH with frozen/current code for exact details.')
    else:
        report['songs'] = sorted(measured, key=lambda song: song['sha256'])
        report['summary'] = {'uniqueSources': len(manifest),
                             'readableSources': sum('presets' in row for row in measured),
                             'parseErrors': sum('parseError' in row for row in measured),
                             'planningErrors': len(failures)}
        save_report(path, report)
        if failures:
            raise ValueError('Corpus contains planning failures: '+failures[0])
    print(f'{"Verified" if verify else "Captured"} {len(manifest)} sources × {len(PRESETS)} presets; no hardware accessed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--capture', type=Path)
    mode.add_argument('--verify', type=Path)
    mode.add_argument('--dump-case', help='SHA/PRESET; requires --report and --dump-output')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--dump-output', type=Path)
    parser.add_argument('--midi-dir', action='append', type=Path)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    try:
        if args.dump_case:
            if not args.report or not args.dump_output:
                raise ValueError('--dump-case requires --report and --dump-output')
            sha, preset = args.dump_case.split('/', 1)
            if preset not in PRESETS:
                raise ValueError('Unknown guarded preset')
            report = json.loads(args.report.read_text())
            row = next(row for row in report['manifest'] if row['sha256'] == sha)
            validate_manifest([row])
            result = measure(row, preset)
            if 'presets' not in result:
                raise ValueError(str(result))
            if args.dump_output.exists():
                raise FileExistsError(args.dump_output)
            args.dump_output.write_text(json.dumps(result['presets'][preset], allow_nan=False)+'\n')
        else:
            if not 1 <= args.workers <= 3:
                raise ValueError('Use 1–3 workers')
            run(args.verify or args.capture, verify=args.verify is not None,
                directories=args.midi_dir or [Path.home()/'Music/MIDI', ROOT/'midi'], workers=args.workers)
    except (OSError, ValueError, KeyError, StopIteration) as error:
        parser.exit(1, 'Corpus failed: '+str(error)+'\n')


if __name__ == '__main__':
    main()
