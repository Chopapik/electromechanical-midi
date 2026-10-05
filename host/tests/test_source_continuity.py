"""Source continuity restores gates in free slots without changing allocation."""
import dataclasses
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playback.articulation import apply_source_continuity
from playback.capabilities import capabilities_for
from playback.virtual import VirtualDeviceInstance,VirtualOrchestra
from playback.performance import PerformanceEvent,PerformancePlan
from playback.engine import PlaybackEngine
from unittest.mock import patch


def event(ident,start,source,actual=.0625,kind='DVD_SLED',outcome='ACCEPTED',note=60):
    return PerformanceEvent(ident,1,'Guitar',note,None,90,0,start,source,
        'one',kind,note,220.,start,actual,outcome)


def build(events):
    device=VirtualDeviceInstance.parse({'id':'one','type':events[0].device_type})
    p=PerformancePlan('Test',events,[dataclasses.asdict(device)],{})
    return p,capabilities_for([device])


class SourceContinuityTest(unittest.TestCase):
    def test_restores_source_end_and_caps_at_next_primary(self):
        p,c=build([event('a',0,2),event('b',.5,1,note=64)])
        before=[dataclasses.asdict(e) for e in p.events]
        r=apply_source_continuity(p,c)
        self.assertEqual(r['extended'],2)
        self.assertLessEqual((p.events[0].actual_start+p.events[0].actual_duration),.5-max(.003,c['one'].retrigger_s)+1e-9)
        self.assertAlmostEqual((p.events[1].actual_start+p.events[1].actual_duration),1.5)
        for original,e in zip(before,p.events):
            now=dataclasses.asdict(e)
            for k in ('actual_duration','sustain_added'):now[k]=original[k]
            self.assertEqual(now,original)
        once=dataclasses.asdict(p)
        self.assertEqual(apply_source_continuity(p,c)['extended'],0)
        self.assertEqual(dataclasses.asdict(p),once)

    def test_half_extensions_preserve_next_primary_and_source(self):
        p,c=build([event('a',0,2),event('b',.5,1,note=64)])
        base=p.events[0].actual_duration
        full=dataclasses.replace(p,events=list(p.events))
        apply_source_continuity(full,c)
        apply_source_continuity(p,c,.5)
        self.assertAlmostEqual(p.events[0].actual_duration,(base+full.events[0].actual_duration)*.5)
        self.assertAlmostEqual(p.events[1].actual_duration,(.0625+1.)*.5)
        self.assertEqual(p.events[0].duration,2.)
        self.assertEqual(p.events[1].actual_start,.5)
        self.assertLess(p.events[0].actual_duration,.5)

    def test_shortened_dropped_and_percussion_are_untouched(self):
        for kind,outcome in [('DVD_SLED','SHORTENED'),('DVD_SLED','DROPPED'),('HDD_VCM','ACCEPTED')]:
            p,c=build([event('a',0,2,kind=kind,outcome=outcome)])
            before=dataclasses.asdict(p)
            self.assertEqual(apply_source_continuity(p,c)['extended'],0)
            self.assertEqual(dataclasses.asdict(p),before)

    def test_delay_does_not_move_original_source_end(self):
        e=dataclasses.replace(event('a',0,1),actual_start=.1)
        p,c=build([e]);apply_source_continuity(p,c)
        self.assertAlmostEqual((p.events[0].actual_start+p.events[0].actual_duration),1.)

    def test_config_and_live_switch_preserve_position(self):
        o=VirtualOrchestra();o.set_config({'sourceContinuity':True,'sourceContinuityAmount':.5,'devices':[]})
        self.assertTrue(o.config()['sourceContinuity'])
        engine=PlaybackEngine()
        try:
            engine._position_base=12.
            with patch.object(engine,'_rebuild_locked') as rebuild:
                engine.configure_virtual({'enabled':True,'sourceContinuity':True,'sourceContinuityAmount':.5,'devices':[]})
                rebuild.assert_called_once_with(keep_position=True)
            self.assertTrue(engine._orchestra.policy['sourceContinuity'])
            self.assertEqual(engine._orchestra.policy['sourceContinuityAmount'],.5)
            self.assertTrue(engine._auto_arrange)
            self.assertEqual(engine._position_base,12.)
        finally:engine.shutdown()

if __name__=='__main__':unittest.main()
