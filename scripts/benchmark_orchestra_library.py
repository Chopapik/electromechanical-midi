"""Full recursive MIDI-library benchmark; no transport, audio playback or hardware I/O."""
import argparse,hashlib,json,sys,time
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from benchmark_universal import metrics,configuration_fingerprint
ROOT=Path(__file__).resolve().parents[1]

def implementation_fingerprint(root):
    """Fingerprint production Python and JSON configuration, excluding tests."""
    root=Path(root);digest=hashlib.sha256()
    paths=[p for p in (root/'host').rglob('*.py') if 'tests' not in p.relative_to(root).parts]
    paths+=list((root/'config').rglob('*.json'))
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode()+b'\0'+path.read_bytes()+b'\0')
    return digest.hexdigest()

def run(path,relative,code_root,preset):
    sys.path.insert(0,str(Path(code_root)/'host'))
    from midi_source import MidiSource
    from runtime.registry import DeviceRegistry
    from runtime.arranger import arrange
    from runtime.compiler import compile_plan
    started=time.monotonic()
    row={'file':relative,'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    try:
        source=MidiSource(path)
        registry=DeviceRegistry(volume_path=Path('/tmp/orchestra-library-no-settings.json'))
        registry.document['parameters']['arrangementPreset']=preset
        plan=arrange(source,registry)
        m=metrics(plan,registry);m.pop('retainedImportantIds',None)
        timeline=compile_plan(plan)
        hits=[c for c in timeline.commands if c.kind=='hit']
        drums=[e for e in plan.events if e.role=='percussion']
        mismatches=0
        for group in plan.hardware.get('fddUnison4',{}).get('groups',[]):
            signatures=[[(c.time,c.kind,c.duration,c.hz,c.source_id,c.velocity) for c in timeline.commands if c.device_id==ident] for ident in group]
            mismatches+=bool(signatures and any(s!=signatures[0] for s in signatures))
        m['unisonGroupMismatches']=mismatches
        m.update(sourceDrums=len(drums),playedDrums=sum(e.played for e in drums),
            drumDrops=dict(Counter(e.reason for e in drums if not e.played)),
            hddHits=len(hits),hddByDevice=dict(Counter(c.device_id for c in hits)),
            drumClassCoverage=dict(Counter(str(e.note) for e in drums if e.played)),
            fddByDevice=dict(Counter(c.device_id for c in timeline.commands if c.kind=='tone' and registry.by_id[c.device_id]['type']=='FDD')),
            fddSourceAttacks=sum(e.played and e.device_type=='FDD' for e in plan.events),
            sourceSeconds=round(source.duration,3),
            configurationFingerprint=configuration_fingerprint(registry.document),
            planningSeconds=round(time.monotonic()-started,3))
        tonal=[e for e in plan.events if e.role not in ('percussion','unpitched_effect')]
        for role in ('lead','bass','harmony'):
            events=[e for e in tonal if e.role==role]
            m[role+'Coverage']=round(sum(e.played for e in events)/max(1,len(events)),6)
        m['tracks']=[{'index':t.index,'name':t.name,'notes':t.note_count} for t in source.tracks]
        row['metrics']=m
    except Exception as exc:
        row['error']=type(exc).__name__+': '+str(exc)
        row['seconds']=round(time.monotonic()-started,3)
    return row

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--midi-root',type=Path,required=True)
    p.add_argument('--code-root',type=Path,default=ROOT)
    p.add_argument('--preset',default='instrument_roles_unison4')
    p.add_argument('--workers',type=int,default=2)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    paths=sorted(f for f in a.midi_root.rglob('*') if f.is_file() and f.suffix.lower() in ('.mid','.midi'))
    if not paths:raise SystemExit('No MIDI files found')
    report={'scope':'offline software planning; acoustic, thermal and REAL performance unmeasured',
            'preset':a.preset,'implementationSha256':implementation_fingerprint(a.code_root),
            'files':len(paths),'uniqueMidi':len({hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}),'songs':[]}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futures=[pool.submit(run,str(f),str(f.relative_to(a.midi_root)),str(a.code_root),a.preset) for f in paths]
        for future in as_completed(futures):
            row=future.result();report['songs'].append(row)
            report['songs'].sort(key=lambda r:r['file'])
            a.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
            print(len(report['songs']), '/',len(paths),row['file'],row.get('error') or row['metrics']['planningSeconds'],flush=True)
    errors=[r for r in report['songs'] if 'error' in r]
    print('Complete:',len(report['songs']),'errors:',len(errors),flush=True)
    if errors:raise SystemExit(1)
if __name__=='__main__':main()
