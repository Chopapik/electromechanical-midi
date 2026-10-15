"""Counting Stars regression: previous lyric scoring vs vocal + FX routing."""
import sys,json
from pathlib import Path
from collections import Counter
from dataclasses import replace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from midi_source import MidiSource
from playback import semantic
from runtime.registry import DeviceRegistry
from runtime.arranger import arrange
from runtime.compiler import compile_plan


def summary(plan):
    commands=compile_plan(plan).commands
    conflicts=0
    for ident in {e.device_id for e in plan.events if e.played}:
        intervals=sorted([(e.actual_start,e.end) for e in plan.events if e.played and e.device_id==ident]+[(e.start,e.start+e.duration) for e in plan.reinforcements if e.device_id==ident])
        conflicts+=sum(a[1]>b[0]+1e-8 for a,b in zip(intervals,intervals[1:]))
    return {'leadTrack':plan.analysis['leadTrack'],'leadSelection':plan.analysis['leadSelection'],
            'fxTracks':plan.analysis.get('fxTracks',[]),
            'vocalRouting':dict(Counter(e.device_id for e in plan.events if e.track==3 and e.played)),
            'fxRouting':dict(Counter(e.device_id for e in plan.events if e.track==7 and e.played)),
            'fxPhrase':[(round(c.time,6),round(c.hz,3),c.device_id) for c in commands if c.kind=='tone' and c.track==7 and 34<=c.time<=37],
            'conflicts':conflicts,'dropped':sum(not e.played for e in plan.events)}

if __name__=='__main__':
    source=MidiSource(ROOT/'midi/One_Republic_Counting_stars.mid')
    classifier=semantic.classify
    def previous(*args):
        result=[]
        for c in classifier(*args):
            if 'strong lyric-aligned monophonic melody' in c.evidence:
                scores={**c.role_scores,'VOCAL':round(c.role_scores['VOCAL']-.14,3)}
                c=replace(c,confidence=scores[c.final_role],role_scores=scores,
                          evidence=tuple(e for e in c.evidence if e!='strong lyric-aligned monophonic melody'))
            result.append(c)
        return tuple(result)
    with patch.object(semantic,'classify',previous): before=summary(arrange(source,DeviceRegistry()))
    after=summary(arrange(source,DeviceRegistry()))
    assert after['leadTrack']==3 and after['fxTracks']==[7]
    assert after['vocalRouting']=={'vhs-1':665} and after['fxRouting']=={'pc-speaker-fx':141}
    assert after['conflicts']==0
    report={'baseline':before,'experiment':after,'scope':'same enabled inventory; baseline removes new strong-lyrics evidence, so FX remains inactive; track indices are zero based'}
    (ROOT/'reports/counting-stars-speakers.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
