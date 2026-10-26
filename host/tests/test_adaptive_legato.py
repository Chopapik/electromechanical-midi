"""Adaptive source rhythm protection, offline only."""
import unittest
from types import SimpleNamespace
import test_fdd_legato as helpers
from playback.adaptive_legato import PRESET
from playback.fdd_legato import select
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.application import Application


class AdaptiveTests(unittest.TestCase):
    setUp = helpers.LegatoTests.setUp
    source = helpers.LegatoTests.source
    registry = helpers.LegatoTests.registry
    assert_feasible = helpers.LegatoTests.assert_feasible

    def plan(self, notes):
        r = self.registry(fdd=2)
        r.document['parameters']['arrangementPreset'] = PRESET
        Application(r).set_preset(PRESET)
        s = self.source([('Melody', 0, notes)])
        return arrange(s,r), r, s

    def test_detached_repeated_attacks_survive_and_have_real_stops(self):
        p,r,s = self.plan([(i*.4,i*.4+.12,60) for i in range(8)])
        events = [e for e in p.events if e.played]
        self.assertEqual(len(events),8)
        self.assertEqual(p.hardware['adaptiveLegato']['protectedAttacksRetained'],8)
        self.assertTrue(all(a.end < b.start for a,b in zip(events,events[1:])))
        self.assertEqual(sum(c.kind=='stop' for c in compile_plan(p).commands),8)
        self.assertEqual(compile_plan(p),compile_plan(arrange(s,r)))
        self.assert_feasible(p,r)

    def test_flowing_pitches_keep_legato(self):
        p,r,_ = self.plan([(i*.4,i*.4+.39,60+i%3) for i in range(8)])
        self.assertEqual(p.hardware['adaptiveLegato']['protectedSourceAttacks'],0)
        commands=compile_plan(p).commands
        self.assertEqual(sum(c.kind=='stop' for c in commands),1)
        self.assert_feasible(p,r)

    def test_local_mode_changes_and_long_rest(self):
        notes=[(i*.4,i*.4+.39,60+i%3) for i in range(12)]
        notes += [(8+i*.4,8+i*.4+.1,60) for i in range(12)]
        p,r,_=self.plan(notes)
        kept=[e for e in p.events if e.played]
        self.assertTrue(any(abs(a.end-b.start)<1e-8 for a,b in zip(kept,kept[1:]) if b.start<3))
        self.assertTrue(all(e.end<6 for e in kept if e.start<6))
        self.assertTrue(all(a.end<b.start for a,b in zip(kept,kept[1:]) if a.start>9))
        self.assert_feasible(p,r)

    def test_later_repeat_remains_candidate_after_infeasible_first_return(self):
        clock=SimpleNamespace(accent=lambda e:False)
        events=[SimpleNamespace(id=str(i),start=t,played_hz=hz,velocity=100)
                for i,(t,hz) in enumerate([(0,130),(.3,150),(.4,130),(.6,130)])]
        art=SimpleNamespace(is_protected=lambda e:False)
        chosen=select(events,lambda e:.2,clock,1.,art)
        self.assertEqual([e.start for e in chosen],[0,.3,.6])

    def test_fast_notes_still_respect_physical_floor_and_no_new_source_onsets(self):
        notes=[(i*.08,i*.08+.04,60+i%4) for i in range(40)]
        p,r,_=self.plan(notes)
        self.assertTrue(any(e.played for e in p.events))
        self.assertTrue(all(e.start==e.actual_start for e in p.events if e.played))
        self.assertTrue(all(e.actual_duration>=.14-1e-9 for e in p.events if e.played))
        self.assert_feasible(p,r)

    def test_other_instruments_are_unchanged(self):
        r=self.registry(dvd=4)
        s=self.source([('Riff',0,[(i*.3,i*.3+.1,60+i%4) for i in range(12)]),
                       ('Pad',1,[(0,4,n) for n in (45,52,57)])])
        r.document['parameters']['arrangementPreset']='fdd_legato';a=arrange(s,r)
        r.document['parameters']['arrangementPreset']=PRESET;b=arrange(s,r)
        non_fdd=lambda p:[c for c in compile_plan(p).commands if not c.device_id.startswith('fdd-')]
        self.assertEqual(non_fdd(a),non_fdd(b))
        self.assert_feasible(b,r)

    def test_reinforcement_does_not_fill_protected_source_gaps(self):
        r=self.registry(fdd=8)
        r.document['parameters']['arrangementPreset']=PRESET
        s=self.source([(name,i,[(j*.4,j*.4+.1,note) for j in range(16)])
                       for i,(name,note) in enumerate([('Riff',60),('Bass',36),('Guitar',67),('Melody',65)])])
        p=arrange(s,r)
        sources={e.id:e for e in p.events}
        for extra in p.reinforcements:
            if extra.kind!='FDD_LEGATO_REINFORCEMENT':continue
            source=sources[extra.source_id]
            self.assertGreaterEqual(extra.start,source.actual_start)
            self.assertLessEqual(extra.start+extra.duration,source.end+1e-9)
        self.assert_feasible(p,r)

    def test_strict_tracks_is_unchanged(self):
        r=self.registry(fdd=2)
        r.document['parameters']['arrangementPreset']=PRESET
        r.document['routing']={'mode':'STRICT_TRACKS','tracks':[1,None,None,None]}
        p=arrange(self.source([('Riff',0,[(0,.1,60)])]),r)
        self.assertNotIn('adaptiveLegato',p.hardware)
        self.assertEqual(p.events[0].actual_duration,.2)

    def test_disabled_partners_and_explicit_gate_cap(self):
        r=self.registry(fdd=1)
        r.document['parameters'].update(arrangementPreset=PRESET,maxNoteSeconds=.3)
        p=arrange(self.source([('Riff',0,[(i*.5,i*.5+.1,60+i%3) for i in range(8)])]),r)
        self.assertTrue(any(e.played for e in p.events))
        self.assertTrue(all(e.device_id=='fdd-1' and e.actual_duration<=.3 for e in p.events if e.played))
        self.assert_feasible(p,r)

    def test_classification_uses_local_tempo_and_does_not_mix_parts(self):
        from playback.adaptive_legato import Articulation
        def event(i,t,d,track=1):
            return SimpleNamespace(id=str(i),start=t,duration=d,note=60,track=track,channel=0)
        events=[event(i,i*.2,.1) for i in range(5)]
        slow=Articulation({0:events},SimpleNamespace(beat=lambda t:.5))
        fast=Articulation({0:events},SimpleNamespace(beat=lambda t:.1))
        self.assertEqual(len(slow.protected),5)
        self.assertEqual(len(fast.protected),0)  # Sustained relative to this tempo.
        isolated=[event(i,i*.2,.1,track=i) for i in range(5)]
        separate=Articulation({0:isolated},SimpleNamespace(beat=lambda t:.5))
        self.assertFalse(separate.protected)

    def test_both_outputs_receive_the_protected_timeline(self):
        from runtime.outputs import RealOutput, VirtualOutput
        p,r,_=self.plan([(i*.4,i*.4+.1,60) for i in range(6)])
        timeline=compile_plan(p);lines=[];packets=[]
        real=RealOutput(r)
        real.link=SimpleNamespace(controller_status={'atx':'ON'},send_batch=lambda batch:lines.extend(batch))
        real.dispatch(timeline.commands)
        VirtualOutput(packets.append).dispatch(timeline.commands,epoch=1)
        self.assertEqual(packets[0]['commands'],[c.as_dict() for c in timeline.commands])
        self.assertEqual(sum(' STOP' in line for line in lines),6)
