#!/usr/bin/env python3
"""Creep A/B/C/D: final quantized solo/full PCM with one shared gain."""
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import wave
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'host'))
from midi_source import MidiSource
from playback.duplicates import normalize
from playback.allocator import allocate
from playback.orchestra import default_orchestra,parse_idle
from playback.virtual import VirtualOrchestra,WavePreview
from playback.tonal_articulation import apply_mode,render
from diagnose_tonal_extreme import pcm,compare
MODES={'raw':'raw','articulated':'articulated','extreme':'extreme-v1','extreme_v2':'extreme-v2'}
OUT=Path('/tmp/tonal-extreme-v2')
GAIN=1.


def save(w,rows,n,mix,path):
    left,right=w._render_numpy(np,rows,n,mix)
    left*=GAIN;right*=GAIN
    assert max(np.max(np.abs(left)),np.max(np.abs(right)))<1,'shared gain clips'
    w._write(path,left,right,n,np)
    y=pcm(path)
    return y,{'file':str(path),'peak':float(np.max(np.abs(y))),
              'rms':float(np.sqrt(np.mean(y*y))),
              'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'clippedSamples':0}


def metrics(y,art,rate):
    def rms(a,b):
        window=y[int(a*rate):int(b*rate)]
        return float(np.sqrt(np.mean(window**2))) if window.size else 0.
    block=max(1,int(.005*rate))
    count=len(y)//block
    curve=np.sqrt(np.mean(y[:count*block].reshape(count,block,2)**2,axis=(1,2)))
    peak=int(np.argmax(curve));peakval=float(curve[peak])
    def crossing(db):
        # First post-peak 5 ms RMS crossing; mechanical ripple is retained.
        hits=np.flatnonzero(curve[peak:]<=peakval*10**(db/20))
        return float(hits[0]*block/rate*1000) if len(hits) else None
    sustain_start=min(art.gate,art.attack+art.decay)
    return {'attackParameterMs':art.attack*1000,'peakSample':float(np.max(np.abs(y))),
        'peak5msRms':peakval,'measuredPeakTimeMs':peak*block/rate*1000,
        'rms0to50ms':rms(0,.05),'rms50to200ms':rms(.05,.2),'rms200to500ms':rms(.2,.5),
        'sustainRms':rms(sustain_start,art.gate) if sustain_start<art.gate else None,
        'releaseRms':rms(art.gate,len(y)/rate),
        'postPeakToMinus6dBMs':crossing(-6),'postPeakToMinus20dBMs':crossing(-20),
        'scheduledAudioDurationMs':len(y)/rate*1000,
        'audibleDurationMinus60dBMs':float((np.flatnonzero(np.max(np.abs(y),axis=1)>float(np.max(np.abs(y)))*.001)[-1]+1)/rate*1000),
        'articulation':art.debug()}


def main():
    OUT.mkdir(exist_ok=True)
    source=MidiSource(ROOT/'midi/0002-02-radiohead_1993-creep-[k] (2).mid')
    config=default_orchestra();config.idle_reinforcement=parse_idle({'enabled':True})
    plan=allocate(normalize(source),config);frozen=dataclasses.asdict(plan)
    o=VirtualOrchestra();timeline=o.render_plan(plan);w=WavePreview();rate=w.RATE
    n=int((timeline.duration+.25)*rate);samples={};report={'input':source.path.name,'soloWindow':[0,timeline.duration+.25],
        'commonGain':GAIN,'normalization':'none','primaryTotals':plan.report()['totals'],
        'solo':{},'probes':{},'fullMix':{},'legacyRegression':{}}
    lanes={}
    for mode,label in MODES.items():
        o.tonal_mode=mode;rows=w._plan(o,n);lanes[mode]=rows
        for track in ('Guitar 1','Guitar 2'):
            solo=[r for r in rows if r[2].kind=='tone' and r[2].source_track==track and not r[2].reinforcement]
            assert solo
            primary={e.id:e for e in plan.events}
            assert all(r[4]/rate >= min(primary[r[2].source_id].actual_duration,n/rate-r[2].time)-2/rate for r in solo)
            key=track.lower().replace(' ','')
            y,result=save(w,solo,n,1,OUT/f'creep-{key}-{label}.wav')
            result['notes']=len(solo)
            report['solo'].setdefault(track,{})[label]=result
            samples[(track,mode)]=y
        assert dataclasses.asdict(plan)==frozen
    for track in ('Guitar 1','Guitar 2'):
        identities=[[(r[2].source_id,r[2].time,r[2].duration) for r in lanes[m]
                    if r[2].kind=='tone' and r[2].source_track==track and not r[2].reinforcement] for m in MODES]
        assert all(ids==identities[0] for ids in identities)
        report['solo'][track]['comparison']={f'raw_vs_{MODES[m]}':compare(samples[(track,'raw')],samples[(track,m)]) for m in MODES if m!='raw'}
        report['solo'][track]['comparison']['v1_vs_v2']=compare(samples[(track,'extreme')],samples[(track,'extreme_v2')])
    # Real Creep notes, isolated only after the same full actuator scheduling.
    baseline=[r for r in lanes['extreme_v2'] if r[2].kind=='tone' and not r[2].reinforcement]
    long=max((r for r in baseline if r[2].source_track=='Guitar 1'),key=lambda r:r[2].tonal_articulation.source_duration)
    short=min((r for r in baseline if r[2].source_track=='Guitar 2'),key=lambda r:abs(r[2].tonal_articulation.source_duration-.0625))
    for name,chosen in [('long',long),('short',short)]:
        ident=chosen[2].source_id
        report['probes'][name]={'sourceId':ident,'track':chosen[2].source_track,'sourceDuration':chosen[2].tonal_articulation.source_duration,'modes':{}}
        for mode,label in MODES.items():
            row=next(r for r in lanes[mode] if r[2].kind=='tone' and r[2].source_id==ident and not r[2].reinforcement)
            local=(*row[:3],0,row[4])
            y,_=save(w,[local],row[4],1,OUT/f'probe-{name}-{label}.wav')
            report['probes'][name]['modes'][label]=metrics(y,row[2].tonal_articulation,rate)
    # Freeze legacy implementation from the baseline commit for exact float/PCM regression.
    legacy_path=OUT/'legacy-tonal.py'
    legacy_path.write_bytes(subprocess.check_output(['git','show','9f01049:host/playback/tonal_articulation.py'],cwd=ROOT))
    spec=importlib.util.spec_from_file_location('legacy_tonal_diagnostic',legacy_path)
    legacy=importlib.util.module_from_spec(spec);sys.modules[spec.name]=legacy;spec.loader.exec_module(legacy)
    for mode in ('raw','articulated','extreme'):
        count=0
        for e in o.events:
            if e.kind!='tone' or e.tonal_articulation is None:continue
            base=e.tonal_articulation
            oldbase=legacy.TonalArticulation(**{f.name:getattr(base,f.name) for f in dataclasses.fields(legacy.TonalArticulation)})
            current=apply_mode(base,mode);before=legacy.apply_mode(oldbase,mode)
            assert all(getattr(current,f.name)==getattr(before,f.name) for f in dataclasses.fields(legacy.TonalArticulation))
        for row in lanes[mode]:
            if row[2].kind!='tone':continue
            art=row[2].tonal_articulation
            args={f.name:getattr(art,f.name) for f in dataclasses.fields(legacy.TonalArticulation)}
            old=legacy.TonalArticulation(**args)
            t=np.arange(row[4],dtype=np.float32)/rate
            a=render(t,art,row[2].hz,(row[4]-1)/rate,np)
            b=legacy.render(t,old,row[2].hz,(row[4]-1)/rate,np)
            assert np.array_equal(a,b),mode
            count+=1
        report['legacyRegression'][mode]={'bitIdenticalFloatSamples':True,'checkedTones':count,'modeParametersIdentical':True}
    legacy_path.unlink()
    full={};fulln=int((timeline.duration+.25)*rate)
    mix=max(1,len([d for d in o.devices if d.in_preview and d.type not in ('DVD_SLED','DVD_TRAY')]))
    for mode in ('extreme','extreme_v2'):
        o.tonal_mode=mode
        y,result=save(w,w._plan(o,fulln),fulln,mix,OUT/f'creep-full-{MODES[mode]}.wav')
        full[mode]=y;report['fullMix'][MODES[mode]]=result
        assert dataclasses.asdict(plan)==frozen
    report['fullMix']['comparison']=compare(full['extreme'],full['extreme_v2'])
    report['planUnchanged']=True;report['soloIdsOnsetsGatesIdentical']=True
    report['metricDefinitions']={'decibelTimes':'first post-peak 5ms block RMS crossing relative to peak block; not fitted envelope','sustain':'attack+decay to gate; null when no sustain window','audibleDuration':'last PCM sample above -60dB of own peak; gain used for every file is identical'}
    (ROOT/'benchmarks/tonal-extreme-v2-diagnostic.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'primary':report['primaryTotals'],'fullComparison':report['fullMix']['comparison'],'legacy':report['legacyRegression'],'output':str(OUT)},indent=2))

if __name__=='__main__':main()
