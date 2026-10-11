"""Offline A/B/C, physical feasibility and optional exact A/B regression check."""
import sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from midi_source import MidiSource
from runtime.registry import DeviceRegistry
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from playback.mechanical_arrangement import _chronology
from playback.dvd_lead import diagnostics
from compare_fdd_quality import FILES, metrics
FILES=FILES+['0032-01-radiohead_1997-airbag-[k].mid','0063-01-radiohead_2003-2+2=5-[k].mid']
def fingerprint(p):
 data={'events':[e.as_dict() for e in p.events],'reinforcements':[e.as_dict() for e in p.reinforcements],'timeline':compile_plan(p).as_dict()}
 return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
def run():
 result={}
 for filename in FILES:
  source=MidiSource(ROOT/'midi'/filename);r=DeviceRegistry();plans={};rows={}
  for preset in ('balanced','fdd_quality','dvd_lead_low_fdd'):
   r.document['parameters']['arrangementPreset']=preset;p=arrange(source,r);plans[preset]=p
   for ident in p.hardware['profiles']:
    assert _chronology(r.profile(ident),[e for e in p.events if e.played and e.device_id==ident],[e for e in p.reinforcements if e.device_id==ident]) is not None,(filename,preset,ident)
   rows[preset]={**metrics(p),**diagnostics(p),'fingerprint':fingerprint(p)}
  baseline={e.id for e in plans['balanced'].events if e.played and e.role in ('lead','bass')}
  for preset,p in plans.items():
   rows[preset]['importantLostVsBalanced']=sorted(baseline-{e.id for e in p.events if e.played})
   frequencies=rows[preset]['fddFrequenciesHz']
   rows[preset]['fddFrequencySummaryHz']={'min':min(frequencies,default=0),'median':frequencies[len(frequencies)//2] if frequencies else 0,'max':max(frequencies,default=0)}
   dvd=[e for e in p.events if e.played and e.device_type=='DVD_SLED']
   boundaries=sorted([(e.actual_start,1) for e in dvd]+[(e.end,-1) for e in dvd])
   active=peak=0
   for _,delta in boundaries:active+=delta;peak=max(peak,active)
   assert peak<=3,(filename,preset,'DVD polyphony')
   rows[preset]['peakDvdVoices']=peak
   rows[preset]['dvdDutyPerLane']={ident:round(sum(e.actual_duration for e in dvd if e.device_id==ident)/p.duration,4) for ident,lane in p.hardware['physicalLanes'].items() if lane.startswith('sled:')}
   rows[preset]['dropReasons']={}
   for e in p.events:
    if not e.played:rows[preset]['dropReasons'][e.reason]=rows[preset]['dropReasons'].get(e.reason,0)+1
  musical_important={e.id for e in plans['dvd_lead_low_fdd'].events if e.hardware.get('selection',{}).get('important') or any(v.get('musical',{}).get('important') for v in e.hardware.get('candidates',{}).values())}
  originally_played={e.id for e in plans['balanced'].events if e.played}
  for preset,p in plans.items():
   rows[preset]['musicallyImportantLostVsBalanced']=sorted((musical_important & originally_played)-{e.id for e in p.events if e.played})
  r.document['parameters']['fddUnisonEnabled']=False
  assert plans['dvd_lead_low_fdd'].events==arrange(source,r).events
  result[filename]=rows;print(filename,[(k,v['fddNotes'],v['dvdNotes'],len(v['importantLostVsBalanced'])) for k,v in rows.items()],flush=True)
 return result
if __name__=='__main__':
 result=run()
 if '--baseline' in sys.argv:
  old=json.loads(Path(sys.argv[sys.argv.index('--baseline')+1]).read_text())
  for song,rows in result.items():
   for preset in ('balanced','fdd_quality'):assert rows[preset]['fingerprint']==old[song][preset]['fingerprint'],(song,preset,'regression')
 (ROOT/'reports/dvd-lead-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
