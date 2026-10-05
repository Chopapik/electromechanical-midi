#!/usr/bin/env python3
"""Creep A/B: identical tonal v2 renderer, different performed durations only."""
import dataclasses
import json
from pathlib import Path
import statistics
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'host'))
from midi_source import MidiSource
from playback.allocator import allocate
from playback.duplicates import normalize
from playback.orchestra import default_orchestra,parse_idle
from playback.capabilities import capabilities_for
from playback.virtual import VirtualOrchestra,WavePreview
from diagnose_tonal_extreme import pcm,compare
OUT=Path('/tmp/source-continuity')


def union(intervals):
    merged=[]
    for start,end in sorted(intervals):
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],end))
        else:merged.append((start,end))
    return merged


def duration(intervals):return sum(b-a for a,b in union(intervals))


def stats(plan,track):
    notes=[e for e in plan.events if e.played and e.track_name==track]
    expected=union([(e.start,e.start+e.duration) for e in notes])
    actual=union([(e.actual_start,e.actual_start+e.actual_duration) for e in notes])
    intersection=[(max(a,c),min(b,d)) for a,b in expected for c,d in actual if max(a,c)<min(b,d)]
    return {'notes':len(notes),'medianSourceMs':statistics.median(e.duration for e in notes)*1000,
        'medianPerformedMs':statistics.median(e.actual_duration for e in notes)*1000,
        'performedVoiceSeconds':sum(e.actual_duration for e in notes),
        'sourceVoiceSeconds':sum(e.duration for e in notes),
        'sourceActiveSeconds':duration(expected),'performedActiveSeconds':duration(actual),
        'sourceActiveTimeCoverage':duration(intersection)/duration(expected)}


def identity(e):
    fields=dataclasses.asdict(e)
    for key in ('actual_duration','sustain_added'):fields.pop(key)
    return fields


def main():
    OUT.mkdir(exist_ok=True)
    source=normalize(MidiSource(ROOT/'midi/0002-02-radiohead_1993-creep-[k] (2).mid'))
    plans={};report={'input':source.path.name,'tonalMode':'extreme_v2','commonGain':1.,'window':[0,source.duration+1.2],'normalization':'none','modes':{}}
    audio={}
    for enabled,label in ((False,'balanced'),(True,'continuity')):
        c=default_orchestra();c.policy['sourceContinuity']=enabled;c.idle_reinforcement=parse_idle({'enabled':True})
        p=allocate(source,c);plans[label]=p
        capabilities=capabilities_for(c.instances())
        # Extensions can consume free gaps, never a normal retrigger reservation.
        if enabled:
            lanes={}
            for e in p.events:
                if e.played and capabilities[e.device_id].tonal:lanes.setdefault(e.device_id,[]).append(e)
            for ident,events in lanes.items():
                events.sort(key=lambda e:(e.actual_start,e.id))
                for a,b in zip(events,events[1:]):assert a.actual_start+a.actual_duration<=b.actual_start+1e-8
        o=VirtualOrchestra();timeline=o.render_plan(p);o.tonal_mode='extreme_v2';w=WavePreview()
        frozen=dataclasses.asdict(p);n=int((source.duration+1.2)*w.RATE);rows=w._plan(o,n)
        result={'primary':p.report()['totals'],'articulation':p.articulation,
            'Guitar 1':stats(p,'Guitar 1'),'Guitar 2':stats(p,'Guitar 2'),
            'reinforcementEvents':len(p.reinforcements),
            'wav':{}}
        for track in ('Guitar 1','Guitar 2','full'):
            selected=rows if track=='full' else [r for r in rows if r[2].kind=='tone' and r[2].source_track==track and not r[2].reinforcement]
            mix=max(1,len([d for d in o.devices if d.in_preview and d.type not in ('DVD_SLED','DVD_TRAY')])) if track=='full' else 1
            left,right=w._render_numpy(np,selected,n,mix)
            assert max(np.max(np.abs(left)),np.max(np.abs(right)))<1
            path=OUT/f'creep-{track.lower().replace(" ","")}-{label}.wav'
            w._write(path,left,right,n,np);y=pcm(path)
            audio[(label,track)]=y
            result['wav'][track]={'file':str(path),'peak':float(np.max(np.abs(y))),'rms':float(np.sqrt(np.mean(y*y))),'clippedSamples':0}
        assert dataclasses.asdict(p)==frozen
        report['modes'][label]=result
    a,b=plans.values()
    assert [identity(e) for e in a.events]==[identity(e) for e in b.events]
    assert a.report()['totals']['played']==b.report()['totals']['played']
    assert a.report()['totals']['dropped']==b.report()['totals']['dropped']
    report['normalAllocationIdenticalExceptDurations']=True
    report['pcmComparison']={track:compare(audio[('balanced',track)],audio[('continuity',track)]) for track in ('Guitar 1','Guitar 2','full')}
    (ROOT/'benchmarks/source-continuity-creep.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({label:{track:report['modes'][label][track] for track in ('Guitar 1','Guitar 2')} for label in plans},indent=2))

if __name__=='__main__':main()
