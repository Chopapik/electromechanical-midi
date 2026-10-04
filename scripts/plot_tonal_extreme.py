#!/usr/bin/env python3
"""Plot actual PCM measurements; requires optional matplotlib, not app runtime."""
import argparse
import json
import wave
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--audio-dir',type=Path,default=Path('/tmp/tonal-extreme'))
    args=parser.parse_args();data=np.load(args.audio_dir/'waveform-curves.npz')
    report=json.loads((ROOT/'benchmarks/tonal-extreme-diagnostic.json').read_text())
    colors={'raw':'#526a88','articulated':'#008a75','extreme':'#d75720'}
    fig,axes=plt.subplots(3,1,figsize=(12,9),layout='constrained')
    fig.suptitle('Creep · Guitar 1 only · FINAL PCM16 · fixed shared gain ×4',fontsize=16)
    for mode,color in colors.items():
        axes[0].plot(data['seconds'],data[mode],color=color,lw=1,label=mode.upper())
        axes[1].plot(data['probeSeconds']*1000,data[f'probe_{mode}'],color=color,lw=2,label=mode.upper())
    axes[0].set(xlabel='Source timeline (seconds)',ylabel='10 ms block RMS',title='Same 155 primary notes, 0–60 seconds; no per-file normalization')
    gate=report['probe']['extreme']['gate']*1000
    axes[1].axvline(gate,color='#333',ls='--',label='Physical gate end')
    axes[1].set(xlabel='Time from onset (ms)',ylabel='10 ms block RMS',title=f"Single real note {report['probe']['extreme']['sourceId']} at {report['probe']['extreme']['start']:.3f} s")
    for mode,color in colors.items():
        with wave.open(str(args.audio_dir/f'probe-{mode}.wav'),'rb') as wav:
            pcm=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').reshape(-1,2)/32767
        start=int(report['probe'][mode]['start']*22050)
        y=pcm[start:start+int(.07*22050),0]
        axes[2].plot(np.arange(len(y))*1000/22050,y,color=color,lw=.7,alpha=.85,label=mode.upper())
    axes[2].set(xlabel='Time from onset (ms)',ylabel='PCM amplitude',title='First 70 ms of that note: actual sample waveform, shared axes')
    for ax in axes:
        ax.legend(loc='upper right',ncol=4,fontsize=9);ax.grid(alpha=.2);ax.set_xlim(left=0)
    axes[0].set_ylim(bottom=0);axes[1].set_ylim(bottom=0)
    fig.savefig(ROOT/'benchmarks/tonal-extreme-waveform.png',dpi=160)

if __name__=='__main__':main()
