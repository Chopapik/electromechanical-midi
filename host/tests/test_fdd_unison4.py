"""Four-drive experimental unison, using the common compiled output plan."""
import dataclasses
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_mechanical_arrangement as helpers
from playback.fdd_pairs import QUAD_PRESET, synchronize_unison4
from playback.allocator import allocate, ManualPin
from playback.analysis import analyze
from playback.performance import ReinforcementEvent
from runtime.registry import PlanningProfiles
from runtime.application import Application
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.outputs import RealOutput, VirtualOutput


class FddUnison4Tests(unittest.TestCase):
    setUp = helpers.MechanicalArrangementTests.setUp
    source = helpers.MechanicalArrangementTests.source
    registry = helpers.MechanicalArrangementTests.registry
    plan = helpers.MechanicalArrangementTests.plan
    assert_feasible = helpers.MechanicalArrangementTests.assert_feasible

    def selected(self, **counts):
        r = self.registry(**counts)
        r.document['parameters']['arrangementPreset'] = QUAD_PRESET
        return r

    def tracks(self):
        return [(name, channel, [(i*.25,i*.25+.15,pitch+i%3) for i in range(8)])
                for name,channel,pitch in [('Riff A',0,60),('Riff B',1,67),('Riff C',2,55),('Riff D',3,64)]]

    def assert_unison(self, plan, members=('fdd-1','fdd-2','fdd-3','fdd-4')):
        timeline = compile_plan(plan)
        signatures = [[(c.time,c.kind,c.hz,c.duration,c.source_id,c.velocity)
                       for c in timeline.commands if c.device_id==ident] for ident in members]
        self.assertTrue(signatures[0])
        self.assertTrue(all(s==signatures[0] for s in signatures))
        return [c for c in timeline.commands if c.kind=='tone' and c.device_id==members[0]]

    def test_four_drives_follow_one_phrase_at_identical_pitch_time_and_duration(self):
        r=self.selected(dvd=0)
        plan=self.plan(self.tracks(),r)
        tones=self.assert_unison(plan)
        self.assertEqual(len(tones),8)
        self.assertEqual(len({e.track for e in plan.events if e.played}),1)
        self.assertEqual(len(plan.reinforcements),24)
        self.assertTrue(all(e.kind=='FDD_UNISON4' for e in plan.reinforcements))
        self.assert_feasible(plan,r)

    def test_phrase_owner_changes_during_pause_without_moving_note_on(self):
        tracks=[('A',0,[(0,.1,60),(.25,.35,62)]),('B',1,[(i*.25,i*.25+.1,67) for i in range(2,8)])]
        r=self.selected(dvd=0);plan=self.plan(tracks,r)
        tones=self.assert_unison(plan)
        self.assertEqual([c.time for c in tones],[i*.25 for i in range(8)])
        self.assertEqual({e.track_name for e in plan.events if e.played},{'A','B'})
        self.assert_feasible(plan,r)

    def test_chords_do_not_become_four_independent_voices(self):
        tracks=[('Chord',0,[(i*.25,i*.25+.1,n) for i in range(8) for n in (60,64,67,71)])]
        plan=self.plan(tracks,self.selected(dvd=0))
        self.assertEqual(len(self.assert_unison(plan)),8)

    def test_missing_device_does_not_renumber_or_enable_additional_drives(self):
        r=self.selected(dvd=0);r.by_id['fdd-2']['enabled']=False
        plan=self.plan(self.tracks(),r)
        self.assert_unison(plan,('fdd-1','fdd-3','fdd-4'))
        commands=compile_plan(plan).commands
        self.assertFalse(any(c.device_id in ('fdd-2','fdd-5','fdd-6','fdd-7','fdd-8') for c in commands))
        self.assert_feasible(plan,r)

    def test_runtime_attack_ceiling_remains_synchronized(self):
        tracks=[('Fast riff',0,[(i*.05,i*.05+.035,60+i%3) for i in range(30)])]
        r=self.selected(dvd=0);p=self.plan(tracks,r)
        with patch('runtime.arranger.allocate',return_value=p): final=arrange(self.source(tracks),r)
        tones=self.assert_unison(final)
        self.assertLess(len(tones),30)
        self.assertTrue(all(b.time-a.time>=.12-1e-9 for a,b in zip(tones,tones[1:])))
        self.assert_feasible(final,r)

    def test_partial_post_filter_group_is_removed_on_every_drive(self):
        r=self.selected(dvd=0);p=self.plan([('A',0,[(0,.15,60),(.5,.65,62)])],r)
        lost=p.reinforcements.pop(0).source_id
        synchronize_unison4(p,r)
        self.assert_unison(p)
        self.assertFalse(any(c.source_id==lost for c in compile_plan(p).commands if c.kind=='tone'))
        self.assertEqual(p.hardware['fddUnison4']['synchronizedVetoes'],1)
        self.assert_feasible(p,r)

    def test_common_gate_is_rechecked_after_per_lane_gate_changes(self):
        r=self.selected(dvd=0);p=self.plan([('A',0,[(0,.15,60)])],r)
        short=p.reinforcements[0].duration/2
        p.reinforcements[0]=dataclasses.replace(p.reinforcements[0],duration=short)
        synchronize_unison4(p,r)
        tones=self.assert_unison(p)
        self.assertTrue(all(c.duration==short for c in tones))
        self.assert_feasible(p,r)

    def test_deterministic_and_non_fdd_allocations_unchanged(self):
        tracks=self.tracks()+[('Pad',4,[(0,3,48),(0,3,55),(0,3,60)])]
        r=self.selected()
        base=self.registry();base.document['parameters']['arrangementPreset']='instrument_roles'
        before=self.plan(tracks,base);p=self.plan(tracks,r);q=self.plan(tracks,r)
        self.assertEqual(compile_plan(p),compile_plan(q))
        self.assertEqual([e for e in p.events if e.device_type!='FDD' and e.played],
                         [e for e in before.events if e.device_type!='FDD' and e.played])
        self.assertEqual([e for e in p.reinforcements if not e.device_id.startswith('fdd-')],
                         [e for e in before.reinforcements if not e.device_id.startswith('fdd-')])
        self.assert_feasible(p,r)

    def test_real_and_virtual_dispatch_same_four_attacks(self):
        r=self.selected(dvd=0);timeline=compile_plan(self.plan([('A',0,[(0,.15,60)])],r))
        lines=[];packets=[];real=RealOutput(r)
        real.link=SimpleNamespace(controller_status={'atx':'ON'},send_batch=lines.extend)
        virtual=VirtualOutput(packets.append)
        real.dispatch(timeline.commands);virtual.dispatch(timeline.commands,epoch=1)
        self.assertEqual(packets[0]['commands'],[c.as_dict() for c in timeline.commands])
        plays=[line for line in lines if ' PLAY ' in line]
        self.assertEqual(len(plays),4)
        self.assertEqual(len({line.split(' PLAY ')[1] for line in plays}),1)

    def test_preset_switch_stops_and_rebuilds_without_autoplay(self):
        app=Application(self.selected());app.load(self.source(self.tracks()).path)
        app.set_preset(QUAD_PRESET)
        self.assertEqual(app.player.state,'stopped')
        self.assertEqual(app.plan.policy['arrangementPreset'],QUAD_PRESET)
        self.assert_unison(app.plan)
        self.assertEqual(app.timeline,compile_plan(app.plan))

    def test_manual_fdd_override_is_rejected_instead_of_breaking_unison(self):
        r=self.selected(dvd=0);source=self.source([('Riff',0,[(0,.1,60)])])
        with self.assertRaisesRegex(ValueError,'ręczne przypisania'):
            allocate(source,r.configuration(),hardware_context=PlanningProfiles(r),midi_analysis=analyze(source),
                     pins={'1:0':ManualPin(device_id='fdd-1',rule_id='fixed')})

    def test_strict_tracks_bypasses_auto_preset_without_crashing(self):
        r=self.selected(dvd=0)
        r.document['routing']={'mode':'STRICT_TRACKS','tracks':[1,2,3,4]}
        p=arrange(self.source(self.tracks()),r)
        self.assertNotIn('fddUnison4',p.hardware)
        self.assertTrue(compile_plan(p).commands)

    def test_application_default_loads_shared_four_drive_plan_without_autoplay(self):
        app=Application()
        app.load(self.source(self.tracks()).path)
        self.assertEqual(app.snapshot()['arrangementPreset'],QUAD_PRESET)
        self.assertEqual(app.player.state,'stopped')
        self.assert_unison(app.plan)

    def test_chronology_replay_work_grows_linearly_for_four_drive_riffs(self):
        from playback.mechanical_arrangement import _chronology
        work=[]
        for count in (32,64):
            r=self.selected(dvd=0)
            tracks=[('Riff',0,[(i*.25,i*.25+.15,60+i%3) for i in range(count)])]
            with patch('playback.fdd_pairs._chronology',wraps=_chronology) as replay:
                p=self.plan(tracks,r)
            self.assertEqual(len(self.assert_unison(p)),count)
            self.assert_feasible(p,r)
            work.append(sum(len(call.args[1])+len(call.args[2]) for call in replay.call_args_list))
        self.assertLessEqual(work[1],2*work[0]+16)
