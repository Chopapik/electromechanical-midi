"""Offline source/normalized/Quality/Adaptive diagnostics and exact regressions."""
import sys,json,pickle,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'host'))
from midi_source import MidiSource
from runtime.arranger import arrange
from runtime.registry import DeviceRegistry
from runtime.compiler import compile_plan
from playback.mechanical_arrangement import _chronology
from playback.fdd_adaptive import activity
FILES=['0005-05-radiohead_1993-thinking_about_you.mid','0041-10-radiohead_1997-no_surprises-[k].mid','0032-01-radiohead_1997-airbag-[k].mid']
def fingerprint(p):
 return hashlib.sha256(json.dumps({'events':[e.as_dict() for e in p.events],'reinforcements':[e.as_dict() for e in p.reinforcements],'timeline':compile_plan(p).as_dict()},sort_keys=True).encode()).hexdigest()
def metrics(p):
 report=p.report()
 return {**report['fddQuality'],'totals':report['totals'],'activity':activity(p),
  'shortenedFdd':sum(e.played and e.device_type=='FDD' and e.actual_duration<e.duration-1e-8 for e in p.events),
  'roles':{role:{'played':sum(e.played and e.role==role for e in p.events),'dropped':sum(not e.played and e.role==role for e in p.events)} for role in ('lead','bass','harmony')},
  'perFdd':{d:sum(e.played and e.device_id==d for e in p.events) for d,lane in p.hardware['physicalLanes'].items() if lane.startswith('fdd:')}}
if __name__=='__main__':
 baseline=json.loads((ROOT/'reports/fdd-adaptive-baseline.json').read_text());result={}
 for filename in FILES:
  path=ROOT/'midi'/filename
  if not path.exists():result[filename]={'available':False};continue
  source=MidiSource(path);r=DeviceRegistry()
  for preset in ('balanced','fdd_quality','dvd_lead_low_fdd'):
   r.document['parameters']['arrangementPreset']=preset;p=arrange(source,r)
   assert fingerprint(p)==baseline[filename][preset],(filename,preset,'regression')
   if preset=='fdd_quality':quality=p
  r.document['parameters']['arrangementPreset']='fdd_quality_adaptive';adaptive=arrange(source,r)
  for ident in adaptive.hardware['profiles']:
   assert _chronology(r.profile(ident),[e for e in adaptive.events if e.played and e.device_id==ident],[e for e in adaptive.reinforcements if e.device_id==ident]) is not None,(filename,ident)
  r.document['parameters']['fddUnisonEnabled']=False;plain=arrange(source,r)
  assert adaptive.events==plain.events,(filename,'UNISON altered primary decisions')
  assert adaptive.hardware['adaptive']['dvdPrimaryPreserved']
  result[filename]={'available':True,'oldPresetsUnchanged':True,'quality':metrics(quality),'adaptive':metrics(adaptive),'diagnostics':adaptive.hardware['adaptive'],
   'compiledPrimary':[{k:v for k,v in c.as_dict().items() if k in ('time','device_id','hz','duration','source_id')} for c in compile_plan(adaptive).commands if c.kind=='tone']}
  print(filename,'notes',quality.report()['fddQuality']['fddNotes'],adaptive.report()['fddQuality']['fddNotes'],'recovered',adaptive.hardware['adaptive']['recoveredNotes'],'gates',adaptive.hardware['adaptive']['restoredGates'],flush=True)
 (ROOT/'reports/fdd-adaptive-comparison.json').write_text(json.dumps({'baselineCommit':'1cee5c0','songs':result},indent=2)+'\n')
