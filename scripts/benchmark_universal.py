"""Offline corpus benchmark: source retention, compiled commands and physical chronology."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


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
        'weightedOnsetCoverage':round(sum(e.velocity for e in played)/max(1,sum(e.velocity for e in tonal)),6),
        'unrepresentedPartWindows':sum(not b for a,b in parts.values()),
        'partWindows':len(parts), 'toneCommandsByFamily':dict(counts),
        'dvdStops':sum(c.kind=='stop' and registry.by_id[c.device_id]['type']=='DVD_SLED' for c in timeline.commands),
        'dvdWorkSeconds':round(work,3),'dvdLongestContinuousSeconds':round(longest,3),
        'fddAttackViolations':attack_violations,'overlaps':overlaps,'mechanicalConflicts':conflicts,
        'maxDelaySeconds':round(max((e.delay for e in played),default=0.),6),
        'noiseOmitted':sum(e.role=='unpitched_effect' and not e.played for e in plan.events),
        'trayCommands':sum(registry.by_id[c.device_id]['type']=='DVD_TRAY' for c in timeline.commands),
        'drumFingerprint':digest([c.as_dict() for c in timeline.commands if c.kind=='hit']),
        'timelineFingerprint':digest(timeline.as_dict())}
    return result


def run_job(code_root, path, preset):
    sys.path.insert(0,str(Path(code_root)/'host'))
    from midi_source import MidiSource
    from runtime.registry import DeviceRegistry
    from runtime.arranger import arrange
    registry = DeviceRegistry(volume_path=Path('/tmp/universal-benchmark-no-speaker-settings.json'))
    registry.document['parameters']['arrangementPreset'] = preset
    for d in registry.devices:
        if d['type']=='DVD_TRAY': d['enabled']=False
    started=time.monotonic()
    plan=arrange(MidiSource(Path(path)),registry)
    values=metrics(plan,registry)
    if preset=='universal':
        assert not any(values[k] for k in ('fddAttackViolations','overlaps','mechanicalConflicts','trayCommands')), values
    values['planningSeconds']=round(time.monotonic()-started,3)
    values['configurationFingerprint']=digest(registry.document)
    return {'file':Path(path).name,'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'preset':preset,'metrics':values}


def comparisons(rows):
    by_file=defaultdict(dict)
    for row in rows:by_file[row['file']][row['preset']]=row
    compared=[]
    for name,presets in sorted(by_file.items()):
        if not {'instrument_roles','universal'} <= presets.keys():continue
        old=presets['instrument_roles'];new=presets['universal']
        assert old['sha256']==new['sha256']
        a,b=old['metrics'],new['metrics']
        compared.append({'file':name,'tonalNotesRecoveredNet':b['playedTonal']-a['playedTonal'],
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
        for item in json.loads(args.manifest.read_text()):
            path=Path(item.get('path',''))
            if not path.is_file():
                matches=[d/item['file'] for d in args.midi_dir if (d/item['file']).is_file()]
                if len(matches)!=1:raise SystemExit('Cannot uniquely locate '+item['file'])
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
