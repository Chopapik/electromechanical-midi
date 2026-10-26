"""SHA-deduplicated library A/B. Reports failures; never drives hardware.

Run: .venv/bin/python scripts/benchmark_adaptive_legato.py --midi-dir ~/Music/MIDI
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys
from time import monotonic

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'host'))
from scripts.benchmark_universal import metrics, configuration_fingerprint


def measure(path):
    from midi_source import MidiSource
    from runtime.registry import DeviceRegistry
    from runtime.arranger import arrange
    started=monotonic()
    row={'file':str(path),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    try:
        source=MidiSource(Path(path))
    except Exception as error:
        return {**row,'parseError':type(error).__name__+': '+str(error)}
    registry=DeviceRegistry(volume_path=Path('/tmp/adaptive-benchmark-no-settings.json'))
    row['configurationFingerprint']=configuration_fingerprint(registry.document)
    for preset in ('fdd_legato','adaptive_legato'):
        registry.document['parameters']['arrangementPreset']=preset
        plan=arrange(source,registry)
        m=metrics(plan,registry)
        for key in ('overlaps','mechanicalConflicts','fddAttackViolations'):
            assert m[key]==0,(path,preset,key,m[key])
        row[preset]={key:m[key] for key in ('fddStops','fddWorkSeconds','fddLongestContinuousSeconds',
            'fddPeakActiveDrives','nonFddTimelineFingerprint','overlaps','mechanicalConflicts','fddAttackViolations')}
        row[preset]['legato']=plan.hardware.get('fddLegato')
        row[preset]['adaptation']=plan.hardware.get('adaptiveLegato')
    assert row['fdd_legato']['nonFddTimelineFingerprint']==row['adaptive_legato']['nonFddTimelineFingerprint'],path
    row['planningSeconds']=round(monotonic()-started,3)
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--midi-dir',type=Path,action='append',required=True)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/adaptive-legato-library.json')
    args=parser.parse_args()
    paths={};count=0
    for directory in args.midi_dir:
        for path in sorted(directory.rglob('*')):
            if path.is_file() and path.suffix.lower() in ('.mid','.midi'):
                count+=1
                paths.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(),[]).append(str(path))
    result={'scope':'offline MIDI/compiled timeline; no acoustic quality or thermal safety claim',
            'paths':count,'uniqueFiles':len(paths),'songs':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs={pool.submit(measure,aliases[0]):aliases for aliases in paths.values()}
        for job in as_completed(jobs):
            aliases=jobs[job]
            try:row=job.result()
            except Exception as error:row={'file':aliases[0],'planningError':repr(error)}
            row['aliases']=aliases
            result['songs'].append(row)
            result['songs'].sort(key=lambda r:r['file'])
            args.output.write_text(json.dumps(result,indent=2)+'\n')
            print(len(result['songs']),Path(aliases[0]).name,
                  row.get('parseError',row.get('planningError','OK')),flush=True)
    if any('planningError' in r for r in result['songs']):raise SystemExit(1)


if __name__=='__main__':main()
