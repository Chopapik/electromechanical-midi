#!/usr/bin/env python3
"""Seven-song vanilla-HDD audit; RAW/ARTICULATED have identical allocation."""
from __future__ import annotations
import argparse
import collections
import dataclasses
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
from midi_source import MidiSource
from playback.allocator import allocate
from playback.duplicates import normalize
from playback.orchestra import default_orchestra, parse_idle
from playback.virtual import VirtualOrchestra, WavePreview, effective_profile
from playback.hdd_articulation import KINDS

SONGS = [('There There','*there_there*'),('2+2=5','*2+2=5*'),('Sail to the Moon','*Sail to the Moon*'),
         ('Let Down','*let_down*'),('Jigsaw Falling Into Place','*jigsaw_falling_into_place*'),
         ('No Surprises','*no_surprises*'),('Creep','*creep*')]

def audit(plan, mode):
    before = [dataclasses.asdict(e) for e in plan.events]
    orchestra = VirtualOrchestra(); orchestra.hdd_mode = mode
    orchestra.render_plan(plan)
    preview = WavePreview(); preview._plan(orchestra, int((plan.duration+1)*preview.RATE))
    assert before == [dataclasses.asdict(e) for e in plan.events], 'renderer mutated primary plan'
    stats = preview.hdd_stats
    rows = stats['events']
    return orchestra, rows, {
        'mode': mode, 'audioEvents':len(rows),
        'articulations': {k: sum(r['articulation']==k for r in rows) for k in KINDS},
        'meanAudioDurationMs':round(statistics.mean(r['duration']*1000 for r in rows),3) if rows else 0,
        'retriggers': stats['chokes'], 'chokedEvents':sum(r['choked'] for r in rows),
        'reinforcementAudioEvents':sum(r['reinforcement'] for r in rows),
        'suppressedReinforcement':stats['suppressedReinforcement'],
    }


def export_intro(orchestra, folder):
    import numpy as np
    folder.mkdir(parents=True, exist_ok=True)
    n=30*WavePreview.RATE
    preview=WavePreview()
    mix_count=max(1,len([d for d in orchestra.devices if d.in_preview and d.type not in ('DVD_SLED','DVD_TRAY')]))
    for mode in ('raw','articulated'):
        orchestra.hdd_mode=mode
        rows=preview._plan(orchestra,n)
        left,right=preview._render_numpy(np,rows,n,mix_count)
        preview._write(folder/f'there-there-{mode}.wav',left,right,n,np)
    # Reproduce the previous one-timbre HDD preview using the same primary/extra onsets.
    other=[row for row in rows if row[0].type!='HDD_VCM']
    left,right=preview._render_numpy(np,other,n,mix_count)
    devices={d.id:d for d in orchestra.devices}
    for e in orchestra.events:
        d=devices[e.device]
        if d.type!='HDD_VCM' or e.kind!='hit' or not d.in_preview: continue
        start=int(e.time*preview.RATE); length=min(n-start,int(.12*preview.RATE))
        if length<=0: continue
        t=np.arange(length,dtype=np.float32)/preview.RATE
        y=np.exp(-t*32)*(np.sin(2*np.pi*230*t)+.25*np.sin(2*np.pi*690*t))
        y *= (e.velocity/127)**(effective_profile(d).get('velocityExponent') or .6)
        gain=.12*d.volume/mix_count
        left[start:start+length]+=y*gain*(1-max(0,d.pan))
        right[start:start+length]+=y*gain*(1+min(0,d.pan))
    preview._write(folder/'there-there-legacy.wav',left,right,n,np)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--midi-dir',type=Path,default=ROOT/'midi')
    parser.add_argument('--output',type=Path,default=ROOT/'benchmarks/hdd-articulation.json')
    parser.add_argument('--audio-dir',type=Path,default=Path('/tmp/hdd-articulation'))
    args=parser.parse_args()
    results=[]
    for title,pattern in SONGS:
        paths=sorted(args.midi_dir.glob(pattern+'.mid'))
        if not paths: raise SystemExit(f'Missing benchmark MIDI: {title}')
        path=paths[0]
        source=normalize(MidiSource(path))
        config=default_orchestra(hdd_count=4)
        config.idle_reinforcement=parse_idle({'enabled':True})
        plan=allocate(source,config)
        # Independent allocation run and full decision equality, not just aggregate counts.
        other=allocate(source,config)
        assert plan.events==other.events and plan.reinforcements==other.reinforcements and plan.tray_events==other.tray_events
        before=[dataclasses.asdict(e) for e in plan.events]
        raw,raw_rows,raw_stats=audit(plan,'raw')
        art,rows,art_stats=audit(other,'articulated')
        assert before==[dataclasses.asdict(e) for e in other.events]
        report=plan.report()['totals']
        item={'song':title,'file':path.name,'primaryBefore':report,'primaryAfter':other.report()['totals'],
              'primaryDecisionsIdentical':True,
              'hddPrimaryEvents':sum(e.played and e.device_type=='HDD_VCM' for e in plan.events),
              'hddReinforcementEvents':sum(e.kind=='hit' for e in plan.reinforcements),
              'raw':raw_stats,'articulated':art_stats}
        if title=='There There':
            intro=[r for r in rows if r['start']<30]
            group=collections.defaultdict(list)
            for r in intro: group[(r['track'],r['channel'],r['note'],r['articulation'],r['pitchBand'])].append(r)
            item['intro']={'requestedSourceEvents':[e.as_dict() for e in plan.events if e.role=='percussion' and e.start<30],
                'audioEvents':intro, 'sources':[{'track':key[0],'channel':key[1],
                'note':key[2],'articulation':key[3],'pitchBand':key[4],
                'events':len(value),'primary':sum(not v['reinforcement'] for v in value),
                'reinforcement':sum(v['reinforcement'] for v in value),
                'resonanceHz':sorted(set(round(v['resonanceHz'],2) for v in value)),
                'devices':dict(collections.Counter(v['deviceId'] for v in value))} for key,value in sorted(group.items())],
                'devices':dict(collections.Counter(r['deviceId'] for r in intro))}
            export_intro(art,args.audio_dir)
        results.append(item)
        print(title,item['hddPrimaryEvents'],item['hddReinforcementEvents'],art_stats,flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'configuration':'4 FDD / 4 DVD / VHS / 4 HDD / 2 tray, idle reinforcement ON',
        'note':'Before/after compares the restored existing four-HDD allocator; RAW/ARTICULATED only change audio.',
        'results':results},indent=2)+'\n')

if __name__=='__main__':main()
