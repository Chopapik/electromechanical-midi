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

    def assert_dual_unison(self, plan):
        first=self.assert_unison(plan,('fdd-1','fdd-2','fdd-3','fdd-4'))
        second=self.assert_unison(plan,('fdd-5','fdd-6','fdd-7','fdd-8'))
        self.assertEqual([c.time for c in first],[c.time for c in second])
        self.assertTrue(all(a.hz!=b.hz for a,b in zip(first,second)))
        return first,second

    def test_eight_drives_form_two_independent_four_drive_unison_voices(self):
        r=self.selected(fdd=8,dvd=0)
        plan=self.plan(self.tracks(),r)
        first,second=self.assert_dual_unison(plan)
        self.assertEqual((len(first),len(second)),(8,8))
        self.assertEqual(len({e.track for e in plan.events if e.played}),2)
        self.assertEqual(plan.hardware['fddUnison4']['groups'],
                         [[f'fdd-{i}' for i in range(1,5)],
                          [f'fdd-{i}' for i in range(5,9)]])
        self.assertEqual(len(plan.reinforcements),48)
        self.assert_feasible(plan,r)

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

    def test_second_group_veto_does_not_remove_valid_first_group(self):
        r=self.selected(fdd=8,dvd=0)
        p=self.plan([('A',0,[(0,.15,60)]),('B',1,[(0,.15,67)])],r)
        second=next(e for e in p.events if e.played and e.device_id=='fdd-5')
        p.reinforcements=[e for e in p.reinforcements
                          if not (e.source_id==second.id and e.device_id=='fdd-8')]
        synchronize_unison4(p,r)
        commands=compile_plan(p).commands
        self.assertEqual(sum(c.kind=='tone' and c.device_id in
                             {'fdd-1','fdd-2','fdd-3','fdd-4'} for c in commands),4)
        self.assertFalse(any(c.kind=='tone' and c.device_id in
                             {'fdd-5','fdd-6','fdd-7','fdd-8'} for c in commands))
        self.assertEqual(p.hardware['fddUnison4']['synchronizedVetoes'],1)

    def test_common_gate_is_rechecked_after_per_lane_gate_changes(self):
        r=self.selected(dvd=0);p=self.plan([('A',0,[(0,.15,60)])],r)
        short=p.reinforcements[0].duration/2
        p.reinforcements[0]=dataclasses.replace(p.reinforcements[0],duration=short)
        synchronize_unison4(p,r)
        tones=self.assert_unison(p)
        self.assertTrue(all(c.duration==short for c in tones))
        self.assert_feasible(p,r)

    def test_deterministic_and_existing_background_notes_preserved(self):
        tracks=self.tracks()+[('Pad',4,[(0,3,48),(0,3,55),(0,3,60)])]
        r=self.selected()
        base=self.registry();base.document['parameters']['arrangementPreset']='instrument_roles'
        before=self.plan(tracks,base);p=self.plan(tracks,r);q=self.plan(tracks,r)
        self.assertEqual(compile_plan(p),compile_plan(q))
        # The two logical FDD voices now participate in allocation up front;
        # other lanes may recover real notes, but retain the long source bed.
        old_pad={e.id for e in before.events if e.played and e.track_name=='Pad'}
        new_pad={e.id for e in p.events if e.played and e.track_name=='Pad'}
        self.assertLessEqual(old_pad,new_pad)
        self.assertTrue(all(e.role!='unpitched_effect' for e in p.events if e.played))
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

    def test_real_and_virtual_dispatch_same_two_groups_of_four_attacks(self):
        r=self.selected(fdd=8,dvd=0)
        for device in r.devices:
            if device['type']=='FDD':
                device['realEnabled']=True
        tracks=[('A',0,[(0,.15,60)]),('B',1,[(0,.15,67)])]
        timeline=compile_plan(self.plan(tracks,r))
        lines=[];packets=[];real=RealOutput(r)
        real.link=SimpleNamespace(controller_status={'atx':'ON'},send_batch=lines.extend)
        virtual=VirtualOutput(packets.append)
        real.dispatch(timeline.commands);virtual.dispatch(timeline.commands,epoch=1)
        self.assertEqual(packets[0]['commands'],[c.as_dict() for c in timeline.commands])
        plays=[line for line in lines if ' PLAY ' in line]
        self.assertEqual(len(plays),8)
        payloads=[line.split(' PLAY ')[1] for line in plays]
        self.assertEqual(sorted([payloads.count(value) for value in set(payloads)]),[4,4])

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
        self.assert_dual_unison(app.plan)

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

    def test_two_groups_can_voice_distinct_notes_from_one_polyphonic_part(self):
        r=self.selected(fdd=8,dvd=0)
        tracks=[('Chord riff',0,[(i*.3,i*.3+.15,pitch+i%2) for i in range(8) for pitch in (60,67)])]
        p=self.plan(tracks,r)
        a,b=self.assert_dual_unison(p)
        self.assertEqual((len(a),len(b)),(8,8))
        self.assert_feasible(p,r)

    def test_monophonic_part_is_not_doubled_between_groups(self):
        r=self.selected(fdd=8,dvd=0)
        p=self.plan([('Single riff',0,[(i*.3,i*.3+.15,60+i%3) for i in range(8)])],r)
        commands=compile_plan(p).commands
        for i in range(8):
            attacks=[c for c in commands if c.kind=='tone' and abs(c.time-i*.3)<1e-8]
            self.assertEqual(len(attacks),4)

    def test_fixed_gate_capacity_is_reserved_before_group_selection(self):
        r=self.selected(fdd=8,dvd=0)
        r.document['parameters'].update(fddFixedToneMs=200,fddMinAttackIntervalMs=200)
        tracks=[('A',0,[(i*.25,i*.25+.35,60+i%3) for i in range(12)]),
                ('B',1,[(i*.25,i*.25+.35,67+i%3) for i in range(12)])]
        p=arrange(self.source(tracks),r)
        a,b=self.assert_dual_unison(p)
        self.assertEqual((len(a),len(b)),(12,12))
        self.assertTrue(all(abs(c.duration-.2)<1e-8 for c in a+b))
        self.assert_feasible(p,r)
