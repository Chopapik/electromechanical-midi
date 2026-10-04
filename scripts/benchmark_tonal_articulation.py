#!/usr/bin/env python3
"""Source audit + eight-song RAW/ARTICULATED regression and waveform benchmark."""
import argparse
import collections
import dataclasses
import json
import statistics
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'host'))
from midi_source import MidiSource
from playback.analysis import analyze
from playback.duplicates import normalize
from playback.allocator import allocate
from playback.orchestra import default_orchestra,parse_idle
from playback.virtual import VirtualOrchestra,WavePreview
from playback.tonal_articulation import chord_context
SONGS=[('Creep','*creep*'),('No Surprises','*no_surprises*'),('Let Down','*let_down*'),
 ('Jigsaw Falling Into Place','*jigsaw_falling_into_place*'),('Nude','*nude*'),
 ('Street Spirit','*street_spirit*'),('2+2=5','*2+2=5*'),('There There','*there_there*')]


def distribution(values):
    v=sorted(values)
    if not v:return {}
    return {'min':v[0],'p10':v[int((len(v)-1)*.1)],'median':statistics.median(v),
            'p90':v[int((len(v)-1)*.9)],'max':v[-1]}


def source_audit(s):
    analysis=analyze(s).as_dict();roles={x['index']:x['finalRole'] for x in analysis['trackClassification']}
    expr=s.expression_events();rows=[]
    for tr in s.tracks:
        notes=s.notes(tr.index)
        if not notes or tr.is_drums:continue
        groups=[]
        for note in notes:
            if not groups or note.start-groups[-1][0].start>.05:groups.append([])
            groups[-1].append(note)
        chords=[g for g in groups if len(set(n.note for n in g))>1]
        # Count overlaps with distinct later onset groups, not simultaneous chord tones.
        onset_groups=collections.defaultdict(list)
        for n in notes:onset_groups[n.start].append(n)
        seq=sorted(onset_groups)
        overlap=sum(max(n.end for n in onset_groups[a])>b+1e-6 for a,b in zip(seq,seq[1:]))
        gaps=[b-max(n.end for n in onset_groups[a]) for a,b in zip(seq,seq[1:])]
        messages=collections.Counter(m.type for m in s._midi.tracks[tr.index])
        controls=collections.defaultdict(list)
        for e in expr:
            if e['track']==tr.index:
                controls[(e['kind'],e.get('control'))].append(e)
        rows.append({'index':tr.index,'name':tr.name,'channels':[c+1 for c in tr.channels],
            'semanticRole':roles[tr.index],'programsZeroBased':s.programs(tr.index),
            'notes':len(notes),'velocity':distribution([n.velocity for n in notes]),
            'durationMs':distribution([n.duration*1000 for n in notes]),
            'noteOffMessages':messages['note_off'],'noteOnMessages':messages['note_on'],
            'noteOnZeroMessages':sum(m.type=='note_on' and m.velocity==0 for m in s._midi.tracks[tr.index]),
            'distinctOnsetOverlaps':overlap,'gapMs':distribution([g*1000 for g in gaps]),
            'chordGroups50ms':len(chords),'nonzeroOnsetSpreadGroups':sum(g[-1].start>g[0].start+1e-9 for g in chords),
            'chordSpreadMs':distribution([(g[-1].start-g[0].start)*1000 for g in chords]),
            'controllers':[{'kind':kind,'cc':cc,'count':len(v),'values':distribution([e['value'] for e in v]),
                            'nonzero':sum(e['value']!=0 for e in v)} for (kind,cc),v in controls.items()]})
    return {'file':s.path.name,'duration':s.duration,'tracks':rows,'expressionEvents':list(expr),
            'duplicates':normalize(s).duplicate_report.as_dict()}


def audit(p,mode):
    frozen=[dataclasses.asdict(e) for e in p.events]
    o=VirtualOrchestra();o.tonal_mode=mode;o.render_plan(p)
    w=WavePreview();w._plan(o,int((p.duration+1)*w.RATE))
    assert frozen==[dataclasses.asdict(e) for e in p.events]
    events=w.tonal_stats['events'];primary=[e for e in events if not e['reinforcement']]
    originals={e.id:e for e in p.events}
    assert all(e['audioDuration']>=originals[e['sourceId']].actual_duration-2/w.RATE for e in primary), 'audio shortened a PRIMARY gate'
    return o,w,{'primary':p.report()['totals'],'tonalEvents':len(primary),
        'meanAttackMs':statistics.mean(e['attackMs'] for e in primary),
        'meanDecayMs':statistics.mean(e['decayMs'] for e in primary),
        'meanReleaseMs':statistics.mean(e['releaseMs'] for e in primary),
        'legatoTransitions':sum(e['legato'] for e in primary),
        'staccatoEvents':sum(e['staccato'] for e in primary),
        'strumLikeGroups':len(o.strum_groups),'retriggers':w.tonal_stats['retriggers'],
        'audibleReinforcement':sum(e['reinforcement'] for e in events),
        'suppressedReinforcement':w.tonal_stats['suppressedReinforcement'],
        'pedalEvents':sum(e['sustainPedal'] for e in primary),
        'profiles':dict(collections.Counter(e['profile'] for e in primary)),
        'acousticOnsetsMatchPlan':all(e.time==originals[e.source_id].actual_start
            for e in o.events if e.kind=='tone' and not e.reinforcement),
        'explicitAllocatorDelayEvents':sum(e.played and e.actual_start>e.start+1e-6 for e in p.events)}


def export(o,folder,duration):
    import numpy as np
    folder.mkdir(parents=True,exist_ok=True);w=WavePreview();n=int((duration+.25)*w.RATE)
    mix=max(1,len([d for d in o.devices if d.in_preview and d.type not in ('DVD_SLED','DVD_TRAY')]))
    metrics={}
    for mode in ('raw','articulated'):
        o.tonal_mode=mode;rows=w._plan(o,n);l,r=w._render_numpy(np,rows,n,mix)
        w._write(folder/f'creep-{mode}.wav',l,r,n,np)
        metrics[mode]={'rms':float(np.sqrt(np.mean(l*l+r*r)/2)),'peak':float(max(np.max(np.abs(l)),np.max(np.abs(r))))}
    # Previous renderer: same plan and HDD, tonal gate ignores velocity/CC/bend.
    rows=w._plan(o,n);others=[r for r in rows if r[2].kind!='tone'];l,r=w._render_numpy(np,others,n,mix)
    for d,profile,e,start,length in rows:
        if e.kind!='tone':continue
        length=min(n-start,int(e.duration*w.RATE));t=np.arange(length,dtype=np.float64)/w.RATE
        if d.type=='VHS':y=(np.sin(2*np.pi*e.hz*t)+.2*np.sin(6*np.pi*e.hz*t))*np.minimum(1,t*40)
        else:
            pulse=np.exp(-((t*e.hz)%1)*(14 if d.type=='FDD' else 9))
            resonance=900 if d.type=='FDD' else 1300 if d.type=='DVD_SLED' else 600
            y=pulse*(.55+.45*np.sin(2*np.pi*resonance*t))
        gain=.12*d.volume/mix
        l[start:start+length]+=y*gain*(1-max(0,d.pan));r[start:start+length]+=y*gain*(1+min(0,d.pan))
    w._write(folder/'creep-legacy.wav',l,r,n,np)
    metrics['legacy']={'rms':float(np.sqrt(np.mean(l*l+r*r)/2)),'peak':float(max(np.max(np.abs(l)),np.max(np.abs(r))))}
    return metrics


def main():
    args=argparse.ArgumentParser();args.add_argument('--audio-dir',type=Path,default=Path('/tmp/tonal-articulation'))
    args=args.parse_args();results=[];creep=None
    for title,pattern in SONGS:
        paths=sorted((ROOT/'midi').glob(pattern+'.mid'))
        if not paths:raise SystemExit(f'Missing MIDI: {title}')
        raw=MidiSource(paths[0]);source=normalize(raw);config=default_orchestra(hdd_count=4)
        config.idle_reinforcement=parse_idle({'enabled':True})
        p=allocate(source,config);other=allocate(source,config)
        spans={f'{t.index}:{n.order}':n for t in source.tracks for n in source.notes(t.index)}
        assert all((e.start,e.duration,e.velocity)==(spans[e.id].start,spans[e.id].duration,spans[e.id].velocity) for e in p.events)
        assert p.events==other.events and p.reinforcements==other.reinforcements
        audit_source=source_audit(raw)
        _,_,before=audit(p,'raw');o,w,after=audit(other,'articulated')
        assert before['primary']==after['primary']
        cc=collections.Counter(e.get('control') for e in raw.expression_events() if e['kind']=='control_change')
        item={'song':title,'file':raw.path.name,'primaryDecisionsIdentical':True,'sourceOnsetsDurationsVelocityPreserved':True,'raw':before,'articulated':after,
            'pitchBendMessages':sum(e['kind']=='pitchwheel' for e in raw.expression_events()),
            'nonzeroPitchBends':sum(e['kind']=='pitchwheel' and e['value']!=0 for e in raw.expression_events()),
            'ccUsage':{str(k):cc[k] for k in (7,11,64,1)},'reinforcementPlanned':len(p.reinforcements),'tonalReinforcementPlanned':sum(e.kind=='tone' for e in p.reinforcements)}
        if title=='Creep':
            creep=audit_source;item['audio']=export(o,args.audio_dir,p.duration)
            item['tonalEvents']=w.tonal_stats['events']
            item['normalization']=source.as_dict()
        results.append(item);print(title,after,flush=True)
    output={'configuration':'4 FDD / 4 DVD / VHS / 4 HDD / 2 trays; idle reinforcement ON; identical allocator settings',
        'creepSource':creep,'results':results}
    (ROOT/'benchmarks/tonal-articulation.json').write_text(json.dumps(output,indent=2)+'\n')

if __name__=='__main__':main()
