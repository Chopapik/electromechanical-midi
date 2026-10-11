"""Offline A/B and exact Balanced regression fingerprint against commit 6754ea2."""
import sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from midi_source import MidiSource
from runtime.arranger import arrange
from runtime.registry import DeviceRegistry
from runtime.compiler import compile_plan
from playback.mechanical_arrangement import _chronology
FILES=['0005-05-radiohead_1993-thinking_about_you.mid','0016-08-radiohead_1994-creep_(acoustic).mid',
       '0068-06-radiohead-2003-where_i_end_and_you_begin.mid','0087-09-radiohead_2007-jigsaw_falling_into_place.mid']
def metrics(plan):
 report=plan.report();played=[e for e in plan.events if e.played]
 roles={role:{'requested':sum(e.role==role for e in plan.events),'played':sum(e.role==role for e in played),
              'dropped':sum(e.role==role and not e.played for e in plan.events),
              'performedSeconds':round(sum(e.actual_duration for e in played if e.role==role),3)} for role in ('lead','bass','harmony')}
 return {**report['fddQuality'],'totals':report['totals'],'roles':roles,
         'dvdNotes':sum(e.device_type=='DVD_SLED' for e in played),
         'dvdSeconds':round(sum(e.actual_duration for e in played if e.device_type=='DVD_SLED'),3),
         'devices':report['devices'],'hardware':report['hardware']['counters']}
if __name__=='__main__':
 baseline=json.loads((ROOT/'reports/fdd-quality-balanced-baseline.json').read_text());result={}
 for filename in FILES:
  path=ROOT/'midi'/filename
  if not path.exists():result[filename]={'available':False};continue
  source=MidiSource(path);r=DeviceRegistry();balanced=arrange(source,r)
  data={'events':[e.as_dict() for e in balanced.events],'reinforcements':[e.as_dict() for e in balanced.reinforcements],'timeline':compile_plan(balanced).as_dict()}
  digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
  assert digest==baseline[filename], filename+' changed Balanced'
  r.document['parameters']['arrangementPreset']='fdd_quality';quality=arrange(source,r)
  for ident in quality.hardware['profiles']:
   p=r.profile(ident)
   assert _chronology(p,[e for e in quality.events if e.played and e.device_id==ident],
                       [e for e in quality.reinforcements if e.device_id==ident]) is not None, filename+' conflict '+ident
  r.document['parameters']['fddUnisonEnabled']=False;plain=arrange(source,r)
  assert quality.events==plain.events, filename+' unison changes primary'
  important=[e for e in balanced.events if e.played and e.role in ('lead','bass')]
  qevents={e.id:e for e in quality.events}
  lost=[e.id for e in important if not qevents[e.id].played]
  result[filename]={'available':True,'balanced':metrics(balanced),'quality':metrics(quality),
                    'balancedFingerprintUnchanged':True,'unisonPrimaryDecisionsIdentical':True,
                    'importantPlayedInBalancedLostInQuality':lost}
  print(filename,result[filename]['balanced']['fddNotes'],result[filename]['quality']['fddNotes'],'lost important',len(lost),flush=True)
 (ROOT/'reports/fdd-quality-comparison.json').write_text(json.dumps({'baselineCommit':'6754ea2','songs':result},indent=2)+'\n')
