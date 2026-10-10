import sys,json,statistics
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'host'))
from midi_source import MidiSource
from runtime.registry import DeviceRegistry
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from playback.mechanical_arrangement import _chronology
FILES=['Every breath you take.mid','The Police - Message in a Bottle.mid','0080-02-radiohead_2007-bodysnatchers-[k].mid','0087-09-radiohead_2007-jigsaw_falling_into_place.mid']
def metrics(p):
 played=[e for e in p.events if e.played]; dvd=[e.actual_duration for e in played if e.device_type=='DVD_SLED'];u=[e for e in p.reinforcements if e.kind=='UNISON']
 conflicts=0
 for d in p.devices:
  intervals=sorted([(e.actual_start,e.end) for e in played if e.device_id==d['id']]+[(e.start,e.start+e.duration) for e in p.reinforcements if e.device_id==d['id']])
  conflicts+=sum(a[1]>b[0]+1e-8 for a,b in zip(intervals,intervals[1:]))
 return dict(played=len(played),dropped=len(p.events)-len(played),fdd=sum(e.device_type=='FDD' for e in played),dvd=len(dvd),dvdMean=statistics.fmean(dvd) if dvd else 0,dvdMax=max(dvd,default=0),longFdd=sum(e.device_type=='FDD' and e.actual_duration>=2 for e in played),unison=len(u),unisonSeconds=sum(e.duration for e in u),conflicts=conflicts,devices=p.report()['devices'],hardware=p.hardware['counters'],commands=len(compile_plan(p).commands),shortened=sum(e.outcome=='SHORTENED' for e in played),sourceSeconds=sum(e.duration for e in played),performedSeconds=sum(e.actual_duration for e in played),folded=sum(e.folded for e in played))
if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description='Compare mechanical plans with recorded pre-change baseline and verify unison invariants.')
 parser.add_argument('--output',type=Path,default=root/'reports/mechanical-arrangement-comparison.json')
 parser.add_argument('--baseline',type=Path,default=root/'reports/mechanical-arrangement-baseline.json')
 args=parser.parse_args();baseline=json.loads(args.baseline.read_text());result={}
 for f in FILES:
  if not (root/'midi'/f).exists():
   result[f]={'available':False};continue
  r=DeviceRegistry();r.by_id['DVD_STEPPER_4']['enabled']=False
  source=MidiSource(root/'midi'/f)
  p=arrange(source,r);current=metrics(p)
  r.document['parameters']['fddUnisonEnabled']=False
  plain=arrange(source,r)
  assert p.events==plain.events, f+' unison changed a primary decision'
  assert current['conflicts']==0, f+' overlapping reservations'
  physical={}
  for d in r.devices:
   profile=r.profile(d['id'])
   if not d['enabled'] or not profile: continue
   chronology=_chronology(profile,[e for e in p.events if e.played and e.device_id==d['id']],
                          [e for e in p.reinforcements if e.device_id==d['id']])
   assert chronology is not None, f+' failed physical chronology '+d['id']
   physical[d['id']]={'notes':len(chronology),'degradedQuality':sum(e.quality.value=='DEGRADED' for e in chronology.values()),
                     'unknownPhysicalLoad':sum(e.physical_load.value=='UNKNOWN' for e in chronology.values())}
  sources={e.id:e for e in p.events}
  for e in p.reinforcements:
   if e.kind=='UNISON':
    n=sources[e.source_id]
    assert (e.start,e.duration,e.hz)==(n.actual_start,n.actual_duration,n.played_hz)
  result[f]={'available':True,'before':baseline[f],'after':current,
      'withoutUnison':metrics(plain),'physicalChronology':physical,'unisonPrimaryDecisionsIdentical':True,
      'unisonDropsAdded':current['dropped']-metrics(plain)['dropped']}
  print(f,current['played'],current['dropped'],'unison',current['unison'],flush=True)
 args.output.write_text(json.dumps({'baselineCommit':'da1af20','inventory':'4 FDD + 3 DVD + existing VHS/HDD; fourth DVD disabled in both runs',
    'missingRequestedMidi':['Radiohead — Glass Eyes','Radiohead — All I Need'],
    'songs':result},indent=2)+'\n')
