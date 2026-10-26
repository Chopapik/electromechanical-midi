"""Additive recovery: exact source attacks, immutable musical backbone and limits."""
from dataclasses import replace
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_mechanical_arrangement as helpers
from playback.performance import ReinforcementEvent
from playback.universal_recovery import recover
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.registry import DeviceRegistry


class RecoveryTests(unittest.TestCase):
    setUp=helpers.MechanicalArrangementTests.setUp
    source=helpers.MechanicalArrangementTests.source
    assert_feasible=helpers.MechanicalArrangementTests.assert_feasible

    def fixture(self, notes, family='FDD'):
        registry=DeviceRegistry()
        registry.document['parameters']['arrangementPreset']='universal'
        registry.document['parameters'].update(
            mechanicalSustain=False,sourceContinuity=False,fddFixedToneMs=0)
        for d in registry.devices:
            d['enabled']=d['id']=={'FDD':'fdd-1','DVD_SLED':'DVD_STEPPER_1','VHS':'pc-speaker-fx'}[family]
        source=self.source([('Part',0,notes)])
        with patch('playback.universal_recovery.recover',return_value=set()):
            plan=arrange(source,registry)
        return source,registry,plan

    def omit(self,plan, index):
        event=plan.events[index]
        self.assertTrue(event.played)
        plan.events[index]=replace(event,device_id=None,device_type=None,actual_duration=0.,
            played_note=None,played_hz=None,outcome='DROPPED',reason='DEVICE_BUSY')
        plan.execution_articulation.pop(event.id,None)
        return event

    def test_free_gap_recovers_source_without_changing_existing_primary_or_extras(self):
        source,r,p=self.fixture([(0,.1,60),(.25,.4,64),(.6,.8,67)])
        omitted=self.omit(p,1)
        before=[e for e in p.events if e.played];extras=list(p.reinforcements)
        ids=recover(p,r,source)
        self.assertEqual(ids,{omitted.id})
        after={e.id:e for e in p.events}
        self.assertTrue(all(after[e.id] is e for e in before))
        self.assertEqual(p.reinforcements,extras)
        recovered=after[omitted.id]
        self.assertEqual((recovered.start,recovered.note,recovered.duration,recovered.actual_start),
                         (omitted.start,omitted.note,omitted.duration,omitted.start))
        self.assertEqual((recovered.played_note-recovered.note)%12,0)
        self.assert_feasible(p,r)

    def test_future_reservation_caps_only_new_gate(self):
        source,r,p=self.fixture([(0,.1,60),(.25,.8,64),(.6,.8,67)])
        omitted=self.omit(p,1);future=next(e for e in p.events if e.start==.6)
        recover(p,r,source)
        recovered=next(e for e in p.events if e.id==omitted.id)
        self.assertTrue(recovered.played)
        self.assertLessEqual(recovered.end,future.actual_start-.003+1e-9)
        self.assertEqual(next(e for e in p.events if e.id==future.id),future)
        self.assert_feasible(p,r)

    def test_attack_spacing_prevents_recovery_even_with_gate_gap(self):
        source,r,p=self.fixture([(0,.05,60),(.1,.2,64),(.4,.6,67)])
        # Source second note can have been delayed by the first allocator;
        # recovery must use its ORIGINAL attack, which is below 120 ms.
        omitted=self.omit(p,1)
        ids=recover(p,r,source)
        self.assertNotIn(omitted.id,ids)
        self.assertFalse(next(e for e in p.events if e.id==omitted.id).played)

    def test_profile_veto_does_not_remove_or_shift_existing_notes(self):
        source,r,p=self.fixture([(0,.1,60),(.25,.4,64),(.6,.8,67)])
        self.omit(p,1);before=list(p.events)
        with patch('playback.universal_recovery._chronology',return_value=None):
            self.assertFalse(recover(p,r,source))
        self.assertEqual(p.events,before)
        self.assertGreater(p.hardware['universal']['recovery']['mechanicalVetoes'],0)

    def test_repeated_pitch_requires_actual_release(self):
        source,r,p=self.fixture([(0,.25,60),(.25,.4,60),(.6,.8,67)])
        # Preserve the first gate up to the next original onset.
        first=p.events[0];p.events[0]=replace(first,actual_duration=.25)
        omitted=self.omit(p,1)
        self.assertNotIn(omitted.id,recover(p,r,source))
        self.assertEqual(p.events[0].actual_duration,.25)

    def test_manual_and_noise_omissions_are_not_reinterpreted(self):
        source,r,p=self.fixture([(0,.1,60),(.25,.4,64),(.6,.8,67)])
        self.omit(p,1)
        omitted=p.events[1]
        for changes in ({'reason':'MANUAL_DROP'},{'role':'unpitched_effect'},
                        {'rule_id':'explicit-rule'},{'articulation':'staccato'}):
            with self.subTest(changes=changes):
                candidate=replace(omitted,**changes);p.events[1]=candidate
                self.assertFalse(recover(p,r,source))

    def test_recovery_rejects_unmusical_tiny_gate(self):
        source,r,p=self.fixture([(0,.1,60),(.25,.4,64),(.6,.8,67)])
        self.omit(p,1);p.events[1]=replace(p.events[1],duration=.005)
        self.assertFalse(recover(p,r,source))

    def test_speaker_recovery_obeys_its_physical_profile_and_music_floor(self):
        source,r,p=self.fixture([(0,.1,72),(.25,.4,74),(.6,.8,76)],'VHS')
        omitted=self.omit(p,1)
        self.assertIn(omitted.id,recover(p,r,source))
        self.assert_feasible(p,r)

    def test_dvd_recovery_cannot_skip_acceleration_settling(self):
        source,r,p=self.fixture([(0,.1,84),(.25,.3,86),(.6,.8,88)],'DVD_SLED')
        omitted=self.omit(p,1)
        self.assertNotIn(omitted.id,recover(p,r,source))
        self.assert_feasible(p,r)

    def test_idle_reinforcement_is_a_real_reservation(self):
        source,r,p=self.fixture([(0,.1,60),(.25,.4,64),(.6,.8,67)])
        omitted=self.omit(p,1)
        p.reinforcements.append(ReinforcementEvent(source_id=p.events[0].id,source_device='fdd-1',
            device_id='fdd-1',hz=p.events[0].played_hz,start=.25,duration=.15,velocity=100,kind='UNISON'))
        before=list(p.reinforcements)
        self.assertNotIn(omitted.id,recover(p,r,source))
        self.assertEqual(p.reinforcements,before)

    def test_unchanged_calm_plan_and_determinism(self):
        source,r,p=self.fixture([(0,.1,60),(.4,.5,64),(.8,.9,67)])
        before=compile_plan(p)
        self.assertFalse(recover(p,r,source))
        self.assertEqual(compile_plan(p),before)
        a=arrange(source,r);b=arrange(source,r)
        self.assertEqual(compile_plan(a),compile_plan(b))

    def with_idle_dvd(self,r,p):
        r.by_id['DVD_STEPPER_1']['enabled']=True
        p.hardware['physicalLanes']['DVD_STEPPER_1']='sled:1'
        p.hardware['states']['DVD_STEPPER_1']={}

    def test_held_tail_continues_without_dropped_notes_or_primary_changes(self):
        source,r,p=self.fixture([(0,3,60),(4,4.2,64)])
        self.with_idle_dvd(r,p);before=list(p.events)
        self.assertFalse(recover(p,r,source))  # no newly recovered primary
        self.assertEqual(p.events,before)
        self.assertEqual(len(p.reinforcements),1)
        extra=p.reinforcements[0];e=p.events[0]
        self.assertEqual((extra.source_id,extra.start,extra.hz),(e.id,e.end,e.played_hz))
        self.assertEqual(extra.start+extra.duration,e.start+e.duration)
        self.assertEqual(extra.kind,'CONTINUATION')
        self.assert_feasible(p,r)

    def test_continuation_preserves_future_and_existing_extra_reservations(self):
        source,r,p=self.fixture([(0,3,60),(4,4.2,64)])
        self.with_idle_dvd(r,p)
        reserved=ReinforcementEvent(source_id=p.events[1].id,source_device='fdd-1',
            device_id='DVD_STEPPER_1',start=1.5,duration=1.,hz=p.events[1].played_hz,
            velocity=100,kind='UNISON')
        p.reinforcements.append(reserved);recover(p,r,source)
        self.assertIs(p.reinforcements[0],reserved)
        self.assertEqual(len(p.reinforcements),2)
        self.assertLessEqual(p.reinforcements[1].start+p.reinforcements[1].duration,1.5-.003+1e-9)
        self.assert_feasible(p,r)

    def test_explicit_shortening_and_articulation_do_not_grow_a_tail(self):
        for changes in ({'outcome':'SHORTENED'},{'rule_id':'manual'},{'articulation':'staccato'}):
            with self.subTest(changes=changes):
                source,r,p=self.fixture([(0,3,60),(4,4.2,64)])
                self.with_idle_dvd(r,p);p.events[0]=replace(p.events[0],**changes)
                recover(p,r,source)
                self.assertFalse(p.reinforcements)

    def test_tail_is_not_doubled_when_dvd_already_sounds_the_pitch(self):
        source,r,p=self.fixture([(0,3,60),(4,4.2,64)])
        self.with_idle_dvd(r,p);recover(p,r,source)
        before=list(p.reinforcements);recover(p,r,source)
        self.assertEqual(p.reinforcements,before)

    def test_held_harmony_may_enter_late_but_never_beyond_source_gate(self):
        source,r,p=self.fixture([(0,.7,60),(.5,2,64),(3,3.4,67)],'DVD_SLED')
        self.omit(p,1);p.events[0]=replace(p.events[0],actual_duration=.7)
        before=p.events[0];ids=recover(p,r,source)
        e=p.events[1]
        self.assertIn(e.id,ids);self.assertGreater(e.actual_start,e.start)
        self.assertLessEqual(e.actual_start-e.start,.25+1e-9)
        self.assertLessEqual(e.end,e.start+e.duration+1e-9)
        self.assertFalse(e.hardware['selection']['sourceOnsetPreserved'])
        self.assertIs(p.events[0],before);self.assert_feasible(p,r)

    def test_short_riff_is_not_queued_after_an_occupied_attack(self):
        source,r,p=self.fixture([(0,.7,60),(.5,.8,64),(3,3.4,67)],'DVD_SLED')
        self.omit(p,1);p.events[0]=replace(p.events[0],actual_duration=.7)
        self.assertFalse(recover(p,r,source));self.assertFalse(p.events[1].played)

    def test_continuation_stops_before_next_attack_of_its_source_voice(self):
        source,r,p=self.fixture([(0,3,60),(3,3.5,62),(4,4.2,64)])
        self.with_idle_dvd(r,p);recover(p,r,source)
        tails=[e for e in p.reinforcements if e.source_id==p.events[0].id]
        self.assertEqual(len(tails),1)
        self.assertLessEqual(tails[0].start+tails[0].duration,2.997+1e-9)

    def test_runtime_preserves_backbone_sidecars_and_captures_expression_in_tail(self):
        source,r,p=self.fixture([(0,3,60),(4,4.2,64)])
        self.with_idle_dvd(r,p)
        p.devices.append(deepcopy(r.by_id['DVD_STEPPER_1']))
        p.expression={'0':[{'kind':'pitchwheel','value':4096,'time':1.}]}
        with patch('runtime.planning_pipeline.allocate',side_effect=lambda *a,**k:deepcopy(p)):
            with patch('playback.universal_recovery.recover',return_value=set()):
                before=arrange(source,r)
            after=arrange(source,r)
        self.assertEqual(after.events,before.events)
        for ident,sidecar in before.execution_articulation.items():
            self.assertEqual(after.execution_articulation[ident],sidecar)
        tones=[c for c in compile_plan(after).commands if c.device_id=='DVD_STEPPER_1' and c.kind=='tone']
        self.assertEqual(len(tones),1)
        frequency=tones[0].articulation['frequency']
        self.assertGreater(frequency['values'][-1],tones[0].hz*1.05)
        self.assertAlmostEqual(frequency['times'][-1],.6)
        self.assert_feasible(after,r)

    def test_coverage_counts_a_source_tail_once_and_excludes_time_after_note_off(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
        from benchmark_universal import metrics
        source,r,p=self.fixture([(0,3,60),(4,4.2,64)])
        self.with_idle_dvd(r,p);p.devices.append(deepcopy(r.by_id['DVD_STEPPER_1']))
        recover(p,r,source)
        m=metrics(p,r)
        self.assertAlmostEqual(m['sourceVoiceDurationCoverage'],1.)
        self.assertLess(m['sourceDurationCoverage'],.2)
        # Scoring must stay bounded even for an externally constructed plan
        # with duplicated continuations or a gate beyond the source NOTE_OFF.
        extra=p.reinforcements[0]
        p.reinforcements.append(replace(extra,duration=10.))
        self.assertEqual(metrics(p,r)['sourceVoiceDurationCoverage'],1.)


if __name__=='__main__':unittest.main()
