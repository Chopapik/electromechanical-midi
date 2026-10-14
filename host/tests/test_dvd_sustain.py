import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playback.dvd_sustain import apply
from playback.performance import PerformanceEvent, PerformancePlan, ReinforcementEvent
from playback.orchestra import parse_policy
from runtime.registry import DeviceRegistry
from runtime.compiler import compile_plan

DVD = 'DVD_STEPPER_1'

def event(i, start, duration=.15, **changes):
    e = PerformanceEvent(str(i),1,'riff',60+i,None,100,0,start,duration,DVD,'DVD_SLED',
                         60+i,220.+i*20,start,duration,'ACCEPTED')
    return replace(e, **changes)

def plan(events):
    return PerformancePlan('riff',events,[{'id':DVD,'type':'DVD_SLED'}],
                           parse_policy({'dvdContinuousSustain':True}))

class DvdSustainTests(unittest.TestCase):
    def setUp(self):
        self.profiles = {DVD: DeviceRegistry().profile(DVD)}
        self.source = SimpleNamespace()
    def apply(self, p): return apply(p,self.profiles,self.source)
    def test_dynamic_riff_exact_legato_deterministic_and_immutable_attacks(self):
        original = [event(i,i*.25) for i in range(6)]
        p = plan(original); q = plan(original)
        self.assertEqual(self.apply(p)['bridged'],5)
        self.apply(q); self.assertEqual(p.events,q.events)
        for a,b in zip(original,p.events):
            self.assertEqual(replace(b,actual_duration=a.actual_duration,sustain_added=0),a)
        self.assertEqual(sum(c.kind=='stop' for c in compile_plan(p).commands),1)
        self.assertEqual(self.apply(p)['bridged'],0)
    def test_repeat_part_channel_stolen_explicit_articulation_and_other_device(self):
        for changes in ({'played_note':60}, {'track':2}, {'channel':1},
                        {'device_type':'FDD'}, {'articulation':'STACCATO'}):
            p=plan([event(0,0),event(1,.25,**changes),event(2,.5)])
            self.apply(p); self.assertEqual(p.events[0].actual_duration,.15)
        for outcome in ('SHORTENED','STOLEN'):
            p=plan([event(0,0,outcome=outcome),event(1,.25),event(2,.5)])
            self.apply(p); self.assertEqual(p.events[0].actual_duration,.15)
    def test_rest_sparse_long_and_skipped_source_attack(self):
        for events in ([event(0,0,.04),event(1,.24),event(2,.48)],
                       [event(0,0,.9),event(1,1),event(2,2)],
                       [event(0,0,1.2),event(1,1.3),event(2,1.55)],
                       [event(0,0),event(9,.2,outcome='DROPPED',device_id=None),event(1,.25),event(2,.5)]):
            p=plan(events); self.apply(p)
            self.assertEqual(p.events[0],events[0])
    def test_reinforcement_reservation_is_not_consumed(self):
        p=plan([event(i,i*.25) for i in range(3)])
        p.reinforcements=[ReinforcementEvent('other',DVD,.17,.04,220,100)]
        self.apply(p); self.assertEqual(p.events[0].actual_duration,.15)
    def test_disabled_and_ceiling(self):
        for policy in ({'dvdContinuousSustain':False},{'dvdMaxBridgeMs':50}):
            p=plan([event(i,i*.25) for i in range(3)]);before=list(p.events)
            p.policy.update(policy); self.apply(p); self.assertEqual(p.events,before)
        for value in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): parse_policy({'dvdMaxBridgeMs':value})
    def test_local_tempo_changes_dynamic_threshold(self):
        p=plan([event(i,i*.35,.25) for i in range(4)])
        self.source.tempo=SimpleNamespace(_segments=[SimpleNamespace(seconds=0,tempo=250000)])
        self.assertEqual(self.apply(p)['bridged'],0)
        p.policy['dvdDynamicAware']=False
        self.assertGreater(self.apply(p)['bridged'],0)
    def test_compiler_ulp_only_dvd_and_preserves_real_gap(self):
        for kind,gap,stops in [('DVD_SLED',0.,1),('DVD_SLED',.000001,2),('FDD',0.,2)]:
            p=plan([event(0,.1,.2,device_type=kind),event(1,.3+gap,device_type=kind)])
            p.devices=[{'id':DVD,'type':kind}]
            self.assertEqual(sum(c.kind=='stop' for c in compile_plan(p).commands),stops)

    def test_mechanical_veto_preserves_primary(self):
        p=plan([event(i,i*.25) for i in range(3)]); before=list(p.events)
        with patch('playback.dvd_sustain._chronology', return_value=None):
            self.assertEqual(self.apply(p)['bridged'],0)
        self.assertEqual(p.events,before)
    def test_source_continuity_gate_and_both_outputs_share_compiled_schedule(self):
        from runtime.outputs import RealOutput, VirtualOutput
        from playback.articulation import apply_source_continuity
        from playback.capabilities import capabilities_for
        from playback.virtual import VirtualDeviceInstance
        p=plan([event(i,i*.25,actual_duration=.08) for i in range(3)])
        caps=capabilities_for([VirtualDeviceInstance.parse({'id':DVD,'type':'DVD_SLED'})])
        apply_source_continuity(p,caps)
        self.assertEqual(self.apply(p)['bridged'],2)
        timeline=compile_plan(p)
        registry=DeviceRegistry(); real=RealOutput(registry); lines=[]
        real.link=SimpleNamespace(send_batch=lambda batch:lines.extend(batch))
        packets=[]; virtual=VirtualOutput(packets.append)
        virtual.dispatch(timeline.commands,epoch=1)
        real.dispatch(timeline.commands)
        self.assertEqual(packets[0]['commands'],[c.as_dict() for c in timeline.commands])
        self.assertEqual(lines,['SLED 1 PLAY 220.00','SLED 1 PLAY 240.00','SLED 1 PLAY 260.00','SLED 1 STOP'])
