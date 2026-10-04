#!/usr/bin/env python3
"""Solo Creep Guitar 1 through the final PCM writer; no allocation/route edits."""
import argparse
import dataclasses
import hashlib
import json
import sys
import wave
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'host'))
from midi_source import MidiSource
from playback.allocator import allocate
from playback.duplicates import normalize
from playback.orchestra import default_orchestra,parse_idle
from playback.virtual import VirtualOrchestra,WavePreview
MODES=('raw','articulated','extreme')


def pcm(path):
    with wave.open(str(path),'rb') as w:
        return np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float64).reshape(-1,2)/32767


def rms_blocks(samples,block=220):
    count=len(samples)//block
    return np.sqrt(np.mean(samples[:count*block].reshape(count,block,2)**2,axis=(1,2)))


def compare(a,b):
    delta=b-a;energy=np.sqrt(np.mean(a*a));norm=energy or 1.
    correlation=float(np.corrcoef(a.ravel(),b.ravel())[0,1])
    # Removing a single best-fit gain still leaves shape/timbre differences.
    fit=float(np.sum(a*b)/max(1e-12,np.sum(a*a)))
    return {'rmsDifference':float(np.sqrt(np.mean(delta*delta))),
        'relativeRmsDifference':float(np.sqrt(np.mean(delta*delta))/norm),
        'changedPcmSamples':int(np.count_nonzero(delta)), 'totalPcmSamples':int(delta.size),
        'correlation':correlation,'bestFitScalarGain':fit,
        'gainRemovedResidualRelativeRms':float(np.sqrt(np.mean((b-fit*a)**2))/norm)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,default=Path('/tmp/tonal-extreme'))
    parser.add_argument('--seconds',type=float,default=60.)
    parser.add_argument('--common-gain',type=float,default=4.)
    parser.add_argument('--baseline-dir',type=Path)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    raw=MidiSource(sorted((ROOT/'midi').glob('*creep*.mid'))[0])
    config=default_orchestra();config.idle_reinforcement=parse_idle({'enabled':True})
    plan=allocate(normalize(raw),config)
    frozen=dataclasses.asdict(plan)
    o=VirtualOrchestra();o.render_plan(plan)
    n=int(args.seconds*WavePreview.RATE);w=WavePreview()
    actual={e.id:e for e in plan.events}
    samples={};results={};lanes={};baseline={}
    for mode in MODES:
        o.tonal_mode=mode
        # Filter AFTER full per-actuator scheduling. Other tracks still have
        # their original reservations; soloing never grants extra voice time.
        all_rows=w._plan(o,n)
        rows=[r for r in all_rows if r[2].kind=='tone' and r[2].source_track=='Guitar 1' and not r[2].reinforcement]
        assert len(rows)>0 and all(r[2].source_id in actual for r in rows)
        assert all(r[4]/w.RATE >= min(actual[r[2].source_id].actual_duration, args.seconds-r[2].time)-2/w.RATE for r in rows), 'audio shortened a normal gate'
        assert all(r[2].time==actual[r[2].source_id].actual_start for r in rows)
        assert frozen==dataclasses.asdict(plan), 'render changed PerformancePlan'
        lanes[mode]=rows
        left,right=w._render_numpy(np,rows,n,1)
        if args.baseline_dir and mode!='extreme':
            # The prior snapshots did not include global Idle RF, but normal
            # lanes must be identical with/without extras. Compare final bytes.
            unboosted=args.output_dir/f'unboosted-{mode}.wav'
            w._write(unboosted,left,right,n,np)
            old=args.baseline_dir/f'creep-guitar1-before-{mode}.wav'
            baseline[mode]=unboosted.read_bytes()==old.read_bytes()
            assert baseline[mode], f'{mode} changed versus pre-EXTREME snapshot'
            unboosted.unlink()
        left*=args.common_gain;right*=args.common_gain
        assert max(np.max(np.abs(left)),np.max(np.abs(right)))<1, 'clipping masks diagnostic waveform'
        path=args.output_dir/f'creep-guitar1-{mode}.wav'
        w._write(path,left,right,n,np)
        samples[mode]=pcm(path) # Analyze FINAL quantized PCM, not parameter objects.
        y=samples[mode]
        results[mode]={'file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'normalNotes':len(rows),'rms':float(np.sqrt(np.mean(y*y))),
            'peak':float(np.max(np.abs(y))),'clippedSamples':int(np.sum(np.abs(y)>=1)),
            'meanAttackMs':float(np.mean([r[2].tonal_articulation.attack*1000 for r in rows])),
            'meanDecayMs':float(np.mean([r[2].tonal_articulation.decay*1000 for r in rows])),
            'meanReleaseMs':float(np.mean([r[2].tonal_articulation.release*1000 for r in rows])),
            'truncatedTails':sum(r[4]<int((r[2].tonal_articulation.gate+r[2].tonal_articulation.release)*w.RATE) for r in rows)}
    ids=[[r[2].source_id for r in lanes[m]] for m in MODES]
    assert ids[0]==ids[1]==ids[2]
    # A real source note through the same mixer/writer isolates its envelope.
    chosen=max(lanes['extreme'],key=lambda r:r[4])
    ident=chosen[2].source_id;isolated={};single={}
    for mode in MODES:
        row=next(r for r in lanes[mode] if r[2].source_id==ident)
        left,right=w._render_numpy(np,[row],n,1)
        target=args.output_dir/f'probe-{mode}.wav'
        w._write(target,left*args.common_gain,right*args.common_gain,n,np)
        y=pcm(target)[chosen[3]:chosen[3]+chosen[4]]
        isolated[mode]=y
        blocks=rms_blocks(y)
        single[mode]={'sourceId':ident,'start':row[2].time,'gate':row[2].duration,
            'audioDuration':row[4]/w.RATE,'device':row[0].type,'velocity':row[2].velocity,
            'peakBlockRms':float(np.max(blocks)),
            'peakBlockMs':float(np.argmax(blocks)*220/w.RATE*1000),
            'rmsFirst10ms':float(np.sqrt(np.mean(y[:220]**2))),
            'rms80to120ms':float(np.sqrt(np.mean(y[int(.08*w.RATE):int(.12*w.RATE)]**2))),
            'rms100to150msAfterGate':float(np.sqrt(np.mean(y[int((row[2].duration+.1)*w.RATE):int((row[2].duration+.15)*w.RATE)]**2))),
            'articulation':row[2].tonal_articulation.debug()}
    curves={'seconds':np.arange(len(rms_blocks(samples['raw'])))*220/w.RATE,
        'probeSeconds':np.arange(len(rms_blocks(isolated['raw'])))*220/w.RATE}
    for m in MODES:
        curves[m]=rms_blocks(samples[m]);curves[f'probe_{m}']=rms_blocks(isolated[m])
    np.savez(args.output_dir/'waveform-curves.npz',**curves)
    report={'file':raw.path.name,'sourceTrack':'Guitar 1','window':[0,args.seconds],
        'sampleRate':w.RATE,'encoding':'stereo PCM16','commonGain':args.common_gain,
        'mixCount':1,'normalization':'none; fixed common gain; no clipping',
        'solo':'only primary Guitar 1 tonal events; no other tracks, hits, reversal noise or any reinforcement',
        'allocation':'full orchestra including idle reinforcement; filter only after actuator scheduling',
        'planUnchanged':frozen==dataclasses.asdict(plan),'primaryTotals':plan.report()['totals'],
        'noteIdsAndOnsetsIdentical':ids[0]==ids[1]==ids[2],
        'regularModesBitIdenticalToBeforeExtreme':baseline,
        'modes':results,'finalPcmComparison':{f'raw_vs_{m}':compare(samples['raw'],samples[m]) for m in ('articulated','extreme')},
        'probe':single}
    (ROOT/'benchmarks/tonal-extreme-diagnostic.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
