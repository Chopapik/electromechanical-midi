"""Adaptive source rhythm protection, offline only."""
import unittest
import copy
from types import SimpleNamespace
from unittest.mock import patch
import test_fdd_legato as helpers
from playback.adaptive_legato import PRESET, PAIR_UNISON
from playback.fdd_legato import select
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.application import Application


class AdaptiveTests(unittest.TestCase):
    setUp = helpers.LegatoTests.setUp
    source = helpers.LegatoTests.source
    registry = helpers.LegatoTests.registry
    assert_feasible = helpers.LegatoTests.assert_feasible
    ensemble = helpers.LegatoTests.ensemble

    def assert_pair_copies(self, plan):
        """Pairs share a complete performed trajectory, including real releases."""
        sources = {e.id:e for e in plan.events if e.played and e.device_type=='FDD'}
        copies = [e for e in plan.reinforcements if e.kind==PAIR_UNISON]
        self.assertEqual(len(copies),len(sources))
        self.assertEqual({e.source_id for e in copies},set(sources))
        for copy in copies:
            source = sources[copy.source_id]
            number = int(source.device_id.split('-')[1])
            partner = number+1 if number%2 else number-1
            self.assertEqual(copy.device_id,f'fdd-{partner}')
            self.assertEqual((copy.hz,copy.start,copy.duration),
                             (source.played_hz,source.actual_start,source.actual_duration))

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
        self.assert_pair_copies(p)
        self.assertEqual(sum(c.kind=='stop' for c in compile_plan(p).commands),16)
        self.assertEqual(compile_plan(p),compile_plan(arrange(s,r)))
        self.assert_feasible(p,r)

    def test_flowing_pitches_keep_legato(self):
        p,r,_ = self.plan([(i*.4,i*.4+.39,60+i%3) for i in range(8)])
        self.assertEqual(p.hardware['adaptiveLegato']['protectedSourceAttacks'],0)
        commands=compile_plan(p).commands
        self.assert_pair_copies(p)
        self.assertEqual(sum(c.kind=='stop' for c in commands),2)
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

    def test_all_four_pairs_follow_identical_rhythmic_trajectories(self):
        r=self.registry(fdd=8)
        r.document['parameters']['arrangementPreset']=PRESET
        s=self.source([(name,i,[(j*.4,j*.4+.1,note) for j in range(16)])
                       for i,(name,note) in enumerate([('Riff',60),('Bass',36),('Guitar',67),('Melody',65)])])
        p=arrange(s,r)
        self.assert_pair_copies(p)
        self.assertEqual({e.device_id for e in p.events if e.played}|
                         {e.device_id for e in p.reinforcements},
                         {f'fdd-{i}' for i in range(1,9)})
        self.assertEqual(compile_plan(p),compile_plan(arrange(s,r)))
        sources={e.id:e for e in p.events}
        for extra in p.reinforcements:
            if extra.kind!=PAIR_UNISON:continue
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
        self.assertFalse(p.reinforcements)
        self.assert_feasible(p,r)

    def test_quiet_single_voice_still_plays_as_one_pair(self):
        p,r,_=self.plan([(0,1,60),(1.2,2.2,62),(2.4,3.4,64)])
        self.assert_pair_copies(p)
        self.assertEqual({e.device_id for e in p.events if e.played}|
                         {e.device_id for e in p.reinforcements},{'fdd-1','fdd-2'})
        self.assert_feasible(p,r)

    def test_pair_unison_preserves_primary_selection_and_articulation(self):
        r=self.registry(fdd=8,dvd=4)
        r.document['parameters']['arrangementPreset']=PRESET
        s=self.source([('Riff',0,[(i*.4,i*.4+.1,60+i%3) for i in range(16)]),
                       ('Pad',1,[(0,6,n) for n in (45,52,57)])])
        with patch('playback.adaptive_legato.pair_unison'):
            baseline=arrange(s,r)
        paired=arrange(s,r)
        self.assertEqual(paired.events,baseline.events)
        for ident,articulation in baseline.execution_articulation.items():
            self.assertEqual(paired.execution_articulation[ident],articulation)
        self.assertEqual(paired.reinforcements[:len(baseline.reinforcements)],
                         baseline.reinforcements)
        non_fdd=lambda p:[c for c in compile_plan(p).commands if not c.device_id.startswith('fdd-')]
        self.assertEqual(non_fdd(paired),non_fdd(baseline))
        self.assert_feasible(paired,r)

    def test_unison_user_policy_can_disable_the_partner(self):
        for policy in ({'fddUnisonEnabled':False},{'fddUnisonMaxVoices':1}):
            with self.subTest(policy=policy):
                r=self.registry(fdd=8)
                r.document['parameters'].update(arrangementPreset=PRESET,**policy)
                p=arrange(self.ensemble(),r)
                self.assertTrue(any(e.played for e in p.events))
                self.assertFalse(p.reinforcements)
                self.assertEqual(p.hardware['adaptiveLegato']['pairUnison']['rejected'],
                                 {'userDisabled':sum(e.played for e in p.events)})
                self.assert_feasible(p,r)

    def test_missing_partners_do_not_borrow_another_pairs_drive(self):
        r=self.registry(fdd=8)
        r.document['parameters']['arrangementPreset']=PRESET
        for ident in ('fdd-2','fdd-4','fdd-6','fdd-8'):
            r.by_id[ident]['enabled']=False
        p=arrange(self.ensemble(),r)
        self.assertTrue(any(e.played for e in p.events))
        self.assertFalse(p.reinforcements)
        self.assertTrue(all(e.device_id in {'fdd-1','fdd-3','fdd-5','fdd-7'}
                            for e in p.events if e.played))
        self.assert_feasible(p,r)

    def test_pair_physical_veto_preserves_every_primary(self):
        from playback.adaptive_legato import pair_unison
        from playback.mechanical_arrangement import ChronologyCache
        r=self.registry(fdd=8)
        r.document['parameters']['arrangementPreset']=PRESET
        s=self.ensemble()
        with patch('playback.adaptive_legato.pair_unison'):
            p=arrange(s,r)
        before=copy.deepcopy(p.events)
        original=ChronologyCache.check
        def veto(cache,primary,extras):
            return None if any(e.kind==PAIR_UNISON for e in extras) else original(cache,primary,extras)
        with patch.object(ChronologyCache,'check',veto):
            pair_unison(p,r)
        self.assertEqual(before,p.events)
        self.assertFalse(p.reinforcements)
        self.assertGreater(p.hardware['adaptiveLegato']['pairUnison']['rejected']['physicalVeto'],0)
        self.assertEqual(p.hardware['adaptiveLegato']['pairUnison']['primaryDropsAdded'],0)
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
        self.assertEqual(sum(' STOP' in line for line in lines),12)
