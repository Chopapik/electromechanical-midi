#!/usr/bin/env python3
"""BEFORE (legacy DVD/tray) vs global idle reinforcement, exact PRIMARY A/B."""
import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
from midi_source import MidiSource
from playback.allocator import allocate
from playback.duplicates import normalize
from playback.orchestra import default_orchestra, parse_idle
from playback.capabilities import capabilities_for
from playback.virtual import VirtualDeviceInstance
from playback.reinforcement import _union


def measure(plan):
    report = plan.report()
    events = {e.id: e for e in plan.events}
    devices = {d['id']: d for d in plan.devices}
    caps = capabilities_for([VirtualDeviceInstance.parse(d) for d in plan.devices])
    normal, extras = defaultdict(list), defaultdict(list)
    for e in plan.events:
        if e.played:
            normal[e.device_id].append((e.actual_start, max(e.end, e.actual_start+caps[e.device_id].retrigger_s)))
    by_type, by_role, by_family, by_program = Counter(), Counter(), Counter(), Counter()
    copies = defaultdict(list)
    for e in [*plan.reinforcements, *plan.tray_events]:
        source = events[e.source_id]
        classification = next((t for t in plan.analysis.get('trackClassification', []) if t['index'] == source.track), {})
        role = classification.get('finalRole', source.role)
        family = 'GM percussion' if source.channel == 9 else classification.get('gmFamily') or 'Unknown'
        program = plan.analysis.get('trackPrograms', {}).get(str(source.track), [])
        by_type[devices[e.device_id]['type']] += 1
        by_role[role] += 1
        by_family[family] += 1
        by_program[str(source.note if source.channel == 9 else program[0] if program else None)] += 1
        copies[e.source_id].extend([(e.start, 1), (e.start+e.duration, -1)])
        extras[e.device_id].append((e.start, e.start+e.duration))
    points_all = sorted(point for points in copies.values() for point in points)
    concurrent = peak_all = 0
    for _, delta in points_all:
        concurrent += delta; peak_all = max(peak_all, concurrent)
    short = sum(e.duration < .04 - 1e-8 for e in plan.reinforcements if e.kind == 'tone')
    peaks=[]
    for points in copies.values():
        active=peak=0
        for _,delta in sorted(points):
            active+=delta;peak=max(peak,active)
        peaks.append(peak)
    duration=max((e.end for e in plan.events),default=0)
    metrics={d: {'type':device['type'], 'primarySeconds': round(_union(normal[d]),3),
                'reinforcementSeconds':round(_union(extras[d]),3),
                'utilization':round((_union(normal[d])+_union(extras[d]))/duration,4) if duration else 0,
                'idleSeconds':round(max(0,duration-_union(normal[d])-_union(extras[d])),3),
                **{key:value for key,value in plan.idle_report.get('devices',{}).get(d,{}).items()
                   if key in ('idleButReinforceableSeconds','unusedReinforceableSeconds')}} for d,device in devices.items()}
    return {'primary':report['totals'],'tonal':report['tonal'],'duration':duration,
            'reinforcementEvents':sum(by_type.values()),'byDeviceType':dict(by_type),
            'bySemanticRole':dict(by_role),'byGmFamily':dict(by_family),'byGmInstrument':dict(by_program),
            'averageCopiesPerReinforcedEvent':sum(peaks)/len(peaks) if peaks else 0,
            'maxConcurrentCopies':max(peaks,default=0), 'maxConcurrentReinforcements':peak_all, 'tonalFragmentsBelow40ms':short, 'reinforcedSources':len(copies),
            'rejected':plan.idle_report.get('rejected',{}),'devices':metrics}


def run(directory):
    paths=sorted(p for p in directory.rglob('*') if p.suffix.lower() in ('.mid','.midi'))
    unique={}
    for p in paths: unique.setdefault(hashlib.sha256(p.read_bytes()).hexdigest(),p)
    songs=[]
    before=default_orchestra(dvd_mode='reinforcement')
    after=default_orchestra(dvd_mode='reinforcement')
    after.idle_reinforcement=parse_idle({'enabled':True})
    for index,(digest,path) in enumerate(unique.items(),1):
        print(f'[{index}/{len(unique)}] {path.name}',file=sys.stderr,flush=True)
        source=normalize(MidiSource(path));a=allocate(source,before);b=allocate(source,after)
        assert [e.as_dict() for e in a.events] == [e.as_dict() for e in b.events],path
        assert a.articulation == b.articulation,path
        # Every primary cycle and copy quota is a hard benchmark gate.
        caps=capabilities_for([VirtualDeviceInstance.parse(d) for d in b.devices])
        for extra in b.reinforcements:
            for primary in b.by_device()[extra.device_id]:
                if primary.played:
                    stop=max(primary.end,primary.actual_start+caps[extra.device_id].retrigger_s)
                    assert extra.start+extra.duration <= primary.actual_start+1e-8 or extra.start >= stop-1e-8,(path,extra,primary)
        am,bm=measure(a),measure(b)
        assert bm['maxConcurrentCopies'] <= 1,path
        songs.append({'file':path.name,'sha256':digest,'before':am,'after':bm})
    aggregate={}
    for mode in ('before','after'):
        rows=[s[mode] for s in songs];duration=sum(r['duration'] for r in rows)
        requested=sum(r['primary']['requested'] for r in rows);dropped=sum(r['primary']['dropped'] for r in rows)
        result={'primary':{'requested':requested,'played':sum(r['primary']['played'] for r in rows),'dropped':dropped,'dropRate':dropped/requested if requested else 0},'duration':duration}
        for field in ('byDeviceType','bySemanticRole','byGmFamily','byGmInstrument','rejected'):
            counts=Counter()
            for row in rows: counts.update(row[field])
            result[field]=dict(counts)
        result['reinforcementEvents']=sum(r['reinforcementEvents'] for r in rows)
        result['averageCopiesPerReinforcedEvent']=sum(r['averageCopiesPerReinforcedEvent']*r['reinforcedSources'] for r in rows)/sum(r['reinforcedSources'] for r in rows)
        result['devices']={}
        for ident in rows[0]['devices']:
            reports=[r['devices'][ident] for r in rows]
            entry={'type':reports[0]['type']}
            for field in ('primarySeconds','reinforcementSeconds','idleSeconds','idleButReinforceableSeconds','unusedReinforceableSeconds'):
                entry[field]=round(sum(r.get(field,0) for r in reports),3)
            entry['utilization']=round((entry['primarySeconds']+entry['reinforcementSeconds'])/duration,4)
            result['devices'][ident]=entry
        aggregate[mode]=result
    return {'filesDiscovered':len(paths),'uniqueFilesMeasured':len(songs),'primaryExactlyIdentical':True,
            'primaryCyclesAndCopyQuotaVerified':True,'settings':after.idle_reinforcement,
            'rejectionUnit': 'candidate-target interval evaluations, not dropped MIDI notes',
            'potentialDefinition': 'primary-idle compatible intervals before copy quotas; unusedReinforceableSeconds is the part left unused; tray theoretical motion ignores extra cooldown/sample quotas',
            'missingRequestedSongs':[name for name in ('Echoes',) if not any(name.lower() in s['file'].lower() for s in songs)],
            'aggregate':aggregate,'songs':songs}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--midi-dir',type=Path,default=ROOT/'midi')
    parser.add_argument('--output',type=Path,default=ROOT/'benchmarks/idle-reinforcement.json')
    args=parser.parse_args();data=run(args.midi_dir)
    args.output.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
