"""Offline corpus benchmark: source retention, compiled commands and physical chronology."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def execution_fingerprint(timeline):
    """Compare active command semantics across archived schema revisions."""
    keys=('time','device_id','kind','duration','hz','velocity','track','source_id','articulation')
    commands=[]
    for command in timeline.commands:
        data=command.as_dict()
        commands.append({k:data[k] for k in keys})
    return digest({'duration':timeline.duration,'commands':commands})


def configuration_fingerprint(document):
    """Execution settings, excluding labels and unavailable inventory entries."""
    active=[d for d in document['devices'] if d.get('enabled',True)]
    families={d['type'] for d in active}
    idle=deepcopy(document.get('idleReinforcement',{}))
    if 'deviceTypes' in idle:idle['deviceTypes']=[k for k in idle['deviceTypes'] if k in families]
    return digest({'devices':active,'parameters':document.get('parameters',{}),
                   'idleReinforcement':idle})


def metrics(plan, registry):
    from runtime.compiler import compile_plan
    from playback.mechanical_arrangement import _chronology
    timeline = compile_plan(plan)
    tonal = [e for e in plan.events if e.role not in ('percussion', 'unpitched_effect')]
    played = [e for e in tonal if e.played]
    by_device = defaultdict(list)
    for c in timeline.commands:
        if c.kind == 'tone': by_device[c.device_id].append(c)
    overlaps = conflicts = attack_violations = 0
    longest = work = 0.
    counts = Counter()
    for d in plan.devices:
        ident = d['id']; events = [e for e in plan.events if e.played and e.device_id == ident]
        extras = [e for e in plan.reinforcements if e.device_id == ident]
        profile = registry.profile(ident)
        if events or extras:
            if _chronology(profile, events, extras) is None: conflicts += 1
        end = -1.; begin = 0.
        commands = by_device[ident]
        for i, c in enumerate(commands):
            overlaps += c.time < end-1e-8
            if c.time > end+1e-9: begin = c.time
            end = c.time+c.duration
            if d['type'] == 'DVD_SLED':
                longest = max(longest, end-begin); work += c.duration
            if d['type'] == 'FDD' and i:
                attack_violations += c.time-commands[i-1].time < plan.policy['fddMinAttackIntervalMs']/1000.-1e-9
        counts[d['type']] += len(commands)
    # Fraction of source duration retained, capped per original event. Extensions
    # do not inflate the score and dropping a long pad is not hidden by many taps.
    total_seconds = sum(e.duration for e in tonal)
    retained = sum(max(0., min(e.end, e.start+e.duration)-max(e.actual_start,e.start)) for e in played)
    tails=defaultdict(list)
    for e in plan.reinforcements:
        if e.kind=='CONTINUATION':tails[e.source_id].append((e.start,e.start+e.duration))
    voice_seconds=0.
    for e in tonal:
        intervals=tails[e.id]+([(e.actual_start,e.end)] if e.played else [])
        end=e.start
        for a,b in sorted(intervals):
            a=max(a,e.start);b=min(b,e.start+e.duration)
            voice_seconds+=max(0.,b-max(a,end));end=max(end,b)
    parts = defaultdict(lambda: [0, 0])
    for e in tonal:
        # Source-active 2 s windows, per logical track/channel; each event votes
        # at its attack. This measures representation, not exhaustive voice coverage.
        key = (e.track, e.channel, int(e.start/2.))
        parts[key][0] += 1; parts[key][1] += int(e.played)
    result = {'sourceTonalNotes':len(tonal), 'playedTonal':len(played),
        'droppedTonal':len(tonal)-len(played),
        'playedByRole':dict(Counter(e.role for e in played)),
        'droppedByRole':dict(Counter(e.role for e in tonal if not e.played)),
        'retainedImportantIds':sorted(e.id for e in played if e.role in ('lead','bass')),
        'dropReasons':dict(Counter(e.reason for e in tonal if not e.played)),
        'sourceDurationCoverage':round(retained/max(1e-9,total_seconds),6),
        'sourceVoiceDurationCoverage':round(voice_seconds/max(1e-9,total_seconds),6),
        'weightedOnsetCoverage':round(sum(e.velocity for e in played)/max(1,sum(e.velocity for e in tonal)),6),
        'unrepresentedPartWindows':sum(not b for a,b in parts.values()),
        'partWindows':len(parts), 'toneCommandsByFamily':dict(counts),
        'dvdStops':sum(c.kind=='stop' and registry.by_id[c.device_id]['type']=='DVD_SLED' for c in timeline.commands),
        'dvdWorkSeconds':round(work,3),'dvdLongestContinuousSeconds':round(longest,3),
        'fddAttackViolations':attack_violations,'overlaps':overlaps,'mechanicalConflicts':conflicts,
        'maxDelaySeconds':round(max((e.delay for e in played),default=0.),6),
        'noiseOmitted':sum(e.role=='unpitched_effect' and not e.played for e in plan.events),
        'drumFingerprint':digest([c.as_dict() for c in timeline.commands if c.kind=='hit']),
        'timelineFingerprint':execution_fingerprint(timeline)}
    recovery=plan.hardware.get('universal',{}).get('recovery')
    fdd=[c for c in timeline.commands if c.kind=='tone' and registry.by_id[c.device_id]['type']=='FDD']
    attacks=Counter(round(c.time,6) for c in fdd)
    repeats=transitions=0
    for ident,commands in by_device.items():
        if registry.by_id[ident]['type']!='FDD':continue
        transitions+=max(0,len(commands)-1)
        repeats+=sum(abs(a.hz-b.hz)<1e-6 for a,b in zip(commands,commands[1:]))
    result.update(fddDistinctPitchOnsets=len({(round(c.time,6),round(c.hz,6)) for c in fdd}),
        fddSourceAttacks=sum(e.played and e.device_type=='FDD' for e in plan.events),
        fddAllEightAttackFraction=sum(v==8 for v in attacks.values())/max(1,len(attacks)),
        fddRepeatedPitchFraction=repeats/max(1,transitions),
        fddGateRangeMs=[min((c.duration for c in fdd),default=0)*1000,
                        max((c.duration for c in fdd),default=0)*1000])
    if 'fddExpressive' in plan.hardware:
        result['fddExpressive']=plan.hardware['fddExpressive']
    if recovery is not None:
        result['recovery']=recovery
    result['backboneTimelineFingerprint']=(recovery or {}).get('backboneTimelineFingerprint',result['timelineFingerprint'])
    return result


def run_job(code_root, path, preset):
    sys.path.insert(0,str(Path(code_root)/'host'))
    from midi_source import MidiSource
    from runtime.registry import DeviceRegistry
    from runtime.arranger import arrange
    registry = DeviceRegistry(volume_path=Path('/tmp/universal-benchmark-no-speaker-settings.json'))
    registry.document['parameters']['arrangementPreset'] = preset
    started=time.monotonic()
    protected={}
    try:
        from playback import universal_recovery
    except ImportError:
        universal_recovery=None  # frozen baseline predating recovery
    if preset=='universal' and universal_recovery is not None:
        original=universal_recovery.recover
        def audited(plan, *args):
            from runtime.compiler import compile_plan
            protected.update(events={e.id:e for e in plan.events if e.played},
                extras=list(plan.reinforcements),sidecars=deepcopy(plan.execution_articulation),
                timeline=execution_fingerprint(compile_plan(plan)))
            return original(plan,*args)
        with patch.object(universal_recovery,'recover',audited):
            plan=arrange(MidiSource(Path(path)),registry)
    else:plan=arrange(MidiSource(Path(path)),registry)
    values=metrics(plan,registry)
    if protected:
        values['backboneTimelineFingerprint']=protected['timeline']
        after={e.id:e for e in plan.events}
        values['originalPlayedEventsIdentical']=all(after[k]==v for k,v in protected['events'].items())
        values['originalReinforcementsIdentical']=plan.reinforcements[:len(protected['extras'])]==protected['extras']
        values['originalArticulationIdentical']=all(plan.execution_articulation.get(k)==v for k,v in protected['sidecars'].items())
        assert all(values[k] for k in ('originalPlayedEventsIdentical','originalReinforcementsIdentical','originalArticulationIdentical'))
    if preset in ('universal','fdd_expressive'):
        assert not any(values[k] for k in ('fddAttackViolations','overlaps','mechanicalConflicts')), values
    values['planningSeconds']=round(time.monotonic()-started,3)
    values['configurationFingerprint']=configuration_fingerprint(registry.document)
    return {'file':Path(path).name,'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'preset':preset,'metrics':values}


def comparisons(rows):
    by_file=defaultdict(dict)
    for row in rows:by_file[row['file']][row['preset']]=row
    compared=[]
    for name,presets in sorted(by_file.items()):
        for baseline,experiment in (('instrument_roles','universal'),('instrument_roles_unison4','fdd_expressive')):
            if not {baseline,experiment} <= presets.keys():continue
            old,new=presets[baseline],presets[experiment]
            assert old['sha256']==new['sha256']
            a,b=old['metrics'],new['metrics']
            compared.append({'file':name,'baselinePreset':baseline,'experimentPreset':experiment,
                'tonalNotesRecoveredNet':b['playedTonal']-a['playedTonal'],
                'previouslyRetainedImportantIdsLost':sorted(set(a['retainedImportantIds'])-set(b['retainedImportantIds'])),
                'drumTimelineIdentical':a['drumFingerprint']==b['drumFingerprint'],
                'durationCoverageDelta':round(b['sourceDurationCoverage']-a['sourceDurationCoverage'],6)})
    return compared


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('midi',type=Path,nargs='*')
    p.add_argument('--manifest',type=Path,help='JSON list with path/file entries')
    p.add_argument('--midi-dir',type=Path,action='append',default=[])
    p.add_argument('--presets',nargs='+',default=['instrument_roles','universal'])
    p.add_argument('--workers',type=int,default=2)
    p.add_argument('--code-root',type=Path,default=ROOT)
    p.add_argument('--output',type=Path,default=ROOT/'reports/universal-arrangement.json')
    args=p.parse_args();paths=args.midi
    if args.manifest:
        inventory=defaultdict(list)
        for directory in args.midi_dir:
            for candidate in sorted(directory.rglob('*')):
                if candidate.is_file() and candidate.suffix.lower() in ('.mid','.midi'):
                    inventory[candidate.name].append(candidate)
        document=json.loads(args.manifest.read_text())
        for item in document.get('songs',[]) if isinstance(document,dict) else document:
            path=Path(item.get('path',''))
            if not path.is_file():
                names=[item['file']]+[Path(a).name for a in item.get('aliases',[])]
                matches=sorted(set(p for name in names for p in inventory[name]))
                if item.get('sha256'):
                    matches=[p for p in matches if hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']]
                if not matches:raise SystemExit('Cannot locate matching MIDI: '+item['file'])
                if not item.get('sha256') and len({hashlib.sha256(p.read_bytes()).hexdigest() for p in matches})>1:
                    raise SystemExit('Ambiguous MIDI: '+item['file'])
                path=matches[0]
            if item.get('sha256') and hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
                raise SystemExit('MIDI hash changed: '+str(path))
            paths.append(path)
    if not paths:raise SystemExit('Supply MIDI paths or a manifest')
    rows=[];args.output.parent.mkdir(parents=True,exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs=[pool.submit(run_job,args.code_root,path,preset) for path in paths for preset in args.presets]
        for job in as_completed(jobs):
            row=job.result();rows.append(row)
            print(row['file'],row['preset'],row['metrics']['playedTonal'],row['metrics']['droppedTonal'],row['metrics']['planningSeconds'],flush=True)
            args.output.write_text(json.dumps({'scope':'software planning; no hardware, temperature or acoustic measurement',
                'songs':sorted(rows,key=lambda r:(r['file'],r['preset'])),
                'comparisons':comparisons(rows)},indent=2)+'\n')


if __name__=='__main__': main()
