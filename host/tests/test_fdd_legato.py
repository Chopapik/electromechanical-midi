"""FDD phrase reorchestration, actual compiled STOPs and mock outputs only."""
import copy
import math
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import test_mechanical_arrangement as helpers
from playback.fdd_legato import PRESET, REINFORCEMENT, apply, reinforce, strong_windows, Clock
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.outputs import RealOutput, VirtualOutput
from runtime.application import Application


class LegatoTests(unittest.TestCase):
    setUp = helpers.MechanicalArrangementTests.setUp
    source = helpers.MechanicalArrangementTests.source
    assert_feasible = helpers.MechanicalArrangementTests.assert_feasible

    def registry(self, fdd=8, dvd=0):
        r=helpers.MechanicalArrangementTests.registry(self,fdd=fdd,dvd=dvd)
        r.document['parameters'].update(arrangementPreset=PRESET,mechanicalSustain=True,sourceContinuity=True)
        return r

    def commands(self,p):
        return [c for c in compile_plan(p).commands if c.device_id.startswith('fdd-')]

    def ensemble(self):
        parts=[('Riff',(60,62,64)),('Bass',(36,38,40)),
               ('Guitar',(67,69,71)),('Melody',(65,67,69))]
        return self.source([(name,i,[(j*.25,j*.25+.08,notes[j%3]) for j in range(24)])
                            for i,(name,notes) in enumerate(parts)])

    def test_strong_ensemble_uses_all_eight_without_short_accent_stops(self):
        from scripts.benchmark_universal import metrics
        r=self.registry();s=self.ensemble()
        with patch('playback.fdd_legato.reinforce'):
            before=arrange(s,r)
        p=arrange(s,r);m=metrics(p,r)
        self.assertEqual(before.events,p.events)
        self.assertEqual(m['fddPeakActiveDrives'],8)
        self.assertGreater(m['fddAllEightActiveSeconds'],5)
        self.assertEqual(p.hardware['fddLegato']['reinforcement']['blocks'],4)
        self.assertEqual(m['fddStops'],8)  # One final stop per drive, not per attack.
        sources={e.id:e for e in p.events}
        for i,e in enumerate(p.reinforcements):
            if e.kind!=REINFORCEMENT:continue
            source=sources[e.source_id]
            self.assertNotEqual(e.device_id,source.device_id)
            self.assertEqual(e.hz,source.played_hz)
            self.assertGreaterEqual(e.duration,.14-1e-9)
            self.assertGreaterEqual(e.start,source.actual_start)
            self.assertLessEqual(e.start+e.duration,source.end+1e-9)
            self.assertEqual(p.execution_articulation['extra:'+str(i)]['kind'],'fdd_legato')
        self.assertEqual(compile_plan(p),compile_plan(arrange(s,r)))
        self.assertEqual(m['fddAttackViolations']+m['overlaps']+m['mechanicalConflicts'],0)
        self.assert_feasible(p,r)

    def test_quiet_and_single_voice_passages_do_not_force_all_drives(self):
        r=self.registry();s=self.ensemble()
        with patch('playback.fdd_legato.reinforce'):
            p=arrange(s,r)
        pool={i:[replace(e,velocity=45) for e in p.events
                 if e.played and e.device_id==f'fdd-{i*2+1}'] for i in range(4)}
        self.assertEqual(strong_windows(pool,Clock(s)),[])
        reinforce(p,r,pool,Clock(s))
        self.assertFalse(any(e.kind==REINFORCEMENT for e in p.reinforcements))

    def test_reinforcement_respects_future_reservations_and_primary_states(self):
        r=self.registry();s=self.ensemble()
        with patch('playback.fdd_legato.reinforce'):
            p=arrange(s,r)
        pool={i:[e for e in p.events if e.played and e.device_id==f'fdd-{i*2+1}'] for i in range(4)}
        first=next(e for e in p.events if e.played and e.device_id=='fdd-1')
        future=replace(first,id='future',device_id='fdd-2',actual_start=2.,actual_duration=1.)
        p.events.append(future);before=copy.deepcopy(p.events)
        reinforce(p,r,pool,Clock(s))
        self.assertEqual(p.events,before)
        copies=[e for e in p.reinforcements if e.device_id=='fdd-2']
        self.assertTrue(copies)
        self.assertTrue(all(e.start+e.duration<=future.actual_start-.003+1e-9 or
                            e.start>=future.end+.003-1e-9 for e in copies))
        self.assert_feasible(p,r)

    def test_user_unison_switch_disabled_partner_and_physical_veto(self):
        r=self.registry();s=self.ensemble()
        r.document['parameters']['fddUnisonEnabled']=False
        p=arrange(s,r)
        self.assertFalse(any(e.kind==REINFORCEMENT for e in p.reinforcements))
        r.document['parameters']['fddUnisonEnabled']=True
        for ident in ('fdd-2','fdd-4','fdd-6','fdd-8'):r.by_id[ident]['enabled']=False
        p=arrange(s,r)
        self.assertFalse(any(e.kind==REINFORCEMENT for e in p.reinforcements))
        r=self.registry()
        with patch('playback.fdd_legato.reinforce'):
            p=arrange(s,r)
        before=copy.deepcopy(p.events)
        pool={i:[e for e in p.events if e.played and e.device_id==f'fdd-{i*2+1}'] for i in range(4)}
        # An impossible minimum gate rejects the optional bodies, not primaries.
        with patch('playback.fdd_legato.min_note_ms',return_value=10000):
            reinforce(p,r,pool,Clock(s))
        self.assertEqual(before,p.events)
        self.assertFalse(any(e.kind==REINFORCEMENT for e in p.reinforcements))

    def test_copy_enters_a_held_pitch_and_follows_the_same_legato_timeline(self):
        r=self.registry();s=self.ensemble()
        with patch('playback.fdd_legato.reinforce'):
            p=arrange(s,r)
        pool={i:[e for e in p.events if e.played and e.device_id==f'fdd-{i*2+1}'] for i in range(4)}
        # A dynamic section begins inside an already sounding tone.
        with patch('playback.fdd_legato.strong_windows',return_value=[(1.02,3.70)]):
            reinforce(p,r,pool,Clock(s))
        copies=[e for e in p.reinforcements if e.kind==REINFORCEMENT]
        self.assertTrue(copies)
        self.assertTrue(any(abs(e.start-1.02)<1e-9 for e in copies))
        sources={e.id:e for e in p.events}
        for e in copies:
            self.assertEqual(e.hz,sources[e.source_id].played_hz)
            self.assertGreaterEqual(e.duration,.14-1e-9)
        commands=self.commands(p)
        self.assertEqual(sum(c.kind=='stop' for c in commands),8)
        timeline=compile_plan(p);lines,packets=[],[]
        real=RealOutput(r);real.link=SimpleNamespace(controller_status={'atx':'ON'},send_batch=lambda batch:lines.extend(batch))
        real.dispatch(timeline.commands);VirtualOutput(packets.append).dispatch(timeline.commands,epoch=1)
        self.assertEqual(packets[0]['commands'],[c.as_dict() for c in timeline.commands])
        self.assertEqual(sum(' STOP' in line for line in lines),8)
        self.assert_feasible(p,r)

    def test_physical_veto_rejects_only_optional_blocks(self):
        from playback.mechanical_arrangement import ChronologyCache
        r=self.registry();s=self.ensemble()
        with patch('playback.fdd_legato.reinforce'):
            p=arrange(s,r)
        before=copy.deepcopy(p.events)
        pool={i:[e for e in p.events if e.played and e.device_id==f'fdd-{i*2+1}'] for i in range(4)}
        original=ChronologyCache.check
        def veto(cache,primary,extras):
            return None if any(e.kind==REINFORCEMENT for e in extras) else original(cache,primary,extras)
        with patch.object(ChronologyCache,'check',veto):
            reinforce(p,r,pool,Clock(s))
        self.assertEqual(before,p.events)
        self.assertFalse(p.reinforcements)
        self.assertGreater(p.hardware['fddLegato']['reinforcement']['rejected']['physicalVeto'],0)

    def test_pitch_changes_share_one_drive_without_intermediate_stop(self):
        r=self.registry(fdd=2)
        p=arrange(self.source([('Riff',0,[(i*.3,i*.3+.08,n) for i,n in enumerate((60,62,64,65,67))])]),r)
        tones=[c for c in self.commands(p) if c.kind=='tone']
        self.assertGreaterEqual(len(tones),3)
        self.assertEqual(len({c.device_id for c in tones}),1)
        self.assertEqual(sum(c.kind=='stop' for c in self.commands(p)),1)
        for a,b in zip(tones,tones[1:]):self.assertAlmostEqual(a.time+a.duration,b.time)
        self.assertTrue(all(c.duration>=.14-1e-9 for c in tones))
        self.assertTrue(all(e.start==e.actual_start and (e.played_note-e.note)%12==0 for e in p.events if e.played))
        self.assert_feasible(p,r)

    def test_repeated_attacks_become_a_single_held_source_pitch(self):
        r=self.registry(fdd=2)
        p=arrange(self.source([('Riff',0,[(i*.2,i*.2+.08,60) for i in range(8)])]),r)
        tones=[c for c in self.commands(p) if c.kind=='tone']
        self.assertEqual(len(tones),1)
        last=max(p.events,key=lambda e:e.start)
        self.assertAlmostEqual(tones[0].duration,last.start+last.duration)
        self.assertEqual(p.hardware['fddLegato']['reductions']['FDD_LEGATO_REPEAT_HELD'],7)
        self.assert_feasible(p,r)

    def test_fast_source_is_reduced_without_delayed_onsets_or_new_notes(self):
        r=self.registry(fdd=2)
        p=arrange(self.source([('Riff',0,[(i*.09,i*.09+.06,60+i%5) for i in range(24)])]),r)
        tones=[c for c in self.commands(p) if c.kind=='tone']
        self.assertGreater(len(tones),2)
        self.assertLess(len(tones),24)
        self.assertEqual(len({c.device_id for c in tones}),1)
        self.assertTrue(all(b.time-a.time>=.12-1e-9 for a,b in zip(tones,tones[1:])))
        self.assertTrue(all(e.actual_start==e.start for e in p.events if e.played))
        self.assert_feasible(p,r)

    def test_real_rests_split_phrases_and_no_tone_is_held_through_them(self):
        r=self.registry(fdd=2)
        p=arrange(self.source([('Riff',0,[(0,.08,60),(.3,.38,62),(3,3.08,64),(3.3,3.38,65)])]),r)
        tones=[c for c in self.commands(p) if c.kind=='tone']
        self.assertEqual(sum(c.kind=='stop' for c in self.commands(p)),2)
        self.assertTrue(all(c.time+c.duration<1 for c in tones if c.time<1))
        self.assert_feasible(p,r)

    def test_non_fdd_primaries_extras_and_all_commands_are_exactly_preserved(self):
        r=self.registry(dvd=4)
        s=self.source([('Riff',0,[(i*.2,i*.2+.08,60+i%4) for i in range(16)]),
                       ('Pad',1,[(0,4,n) for n in (45,52,57)])])
        r.document['parameters']['arrangementPreset']='fdd_expressive_solo';a=arrange(s,r)
        r.document['parameters']['arrangementPreset']=PRESET;b=arrange(s,r)
        original_fdd={e.id for e in a.events if e.played and e.device_type=='FDD'}
        self.assertEqual([e for e in a.events if e.id not in original_fdd],
                         [e for e in b.events if e.id not in original_fdd])
        self.assertEqual(a.reinforcements,b.reinforcements)
        non_fdd={d['id'] for d in a.devices if d['type']!='FDD'}
        self.assertEqual([c for c in compile_plan(a).commands if c.device_id in non_fdd],
                         [c for c in compile_plan(b).commands if c.device_id in non_fdd])
        self.assertEqual(compile_plan(b),compile_plan(arrange(s,r)))
        self.assert_feasible(b,r)

    def test_explicit_gate_cap_and_missing_pair_members_are_respected(self):
        r=self.registry(fdd=1)
        r.document['parameters']['maxNoteSeconds']=.3
        p=arrange(self.source([('Riff',0,[(0,.08,60),(.5,.58,62),(1,1.08,64)])]),r)
        tones=[c for c in self.commands(p) if c.kind=='tone']
        self.assertTrue(tones)
        self.assertTrue(all(c.device_id=='fdd-1' and c.duration<=.3+1e-9 for c in tones))
        self.assert_feasible(p,r)

    def test_an_old_long_source_gate_does_not_erase_a_later_voice_rest(self):
        r=self.registry(fdd=2)
        r.document['parameters']['arrangementPreset']='fdd_expressive_solo'
        s=self.source([('Riff',0,[(0,.08,60),(.3,.38,62),(3,3.08,64)])])
        p=arrange(s,r)
        p.events[0]=replace(p.events[0],duration=2.)
        apply(p,r,s)
        tones=[c for c in self.commands(p) if c.kind=='tone']
        self.assertTrue(all(c.time+c.duration<1 for c in tones if c.time<1))

    def test_source_part_change_starts_a_separate_phrase(self):
        r=self.registry(fdd=2)
        r.document['parameters']['arrangementPreset']='fdd_expressive_solo'
        s=self.source([('Riff',0,[(0,.2,60),(.3,.5,62),(.6,.8,64)])])
        p=arrange(s,r)
        p.events[1]=replace(p.events[1],track=99,channel=1,role='bass')
        apply(p,r,s)
        kept=[e for e in p.events if e.played]
        self.assertTrue(any(e.track==99 for e in kept))
        by_phrase={}
        for e in kept:
            by_phrase.setdefault(e.hardware['selection']['legatoPhrase'],set()).add((e.track,e.channel))
        self.assertTrue(all(len(parts)==1 for parts in by_phrase.values()))

    def test_strict_tracks_keeps_previous_fixed_gate(self):
        r=self.registry(fdd=2)
        r.document['routing']={'mode':'STRICT_TRACKS','tracks':[1,None,None,None]}
        p=arrange(self.source([('Riff',0,[(0,.1,60)])]),r)
        self.assertNotIn('fddLegato',p.hardware)
        self.assertEqual(p.events[0].actual_duration,.2)

    def test_compiler_tolerance_is_legato_only_and_keeps_real_release(self):
        r=self.registry(fdd=2)
        p=arrange(self.source([('Riff',0,[(0,.1,60),(.3,.4,62)])]),r)
        events=[e for e in p.events if e.played]
        self.assertEqual(len(events),2)
        ident=events[0].device_id
        p.events=[replace(events[0],actual_start=.1,actual_duration=math.nextafter(.3,math.inf)-.1),
                  replace(events[1],device_id=ident,actual_start=.3,actual_duration=.2)]
        self.assertEqual(sum(c.kind=='stop' for c in self.commands(p)),1)
        p.hardware.pop('fddLegato')
        self.assertEqual(sum(c.kind=='stop' for c in self.commands(p)),1)
        p.internal_context.join_fdd_tones=False
        self.assertEqual(sum(c.kind=='stop' for c in self.commands(p)),2)
        p.internal_context.join_fdd_tones=True
        p.events[0]=replace(p.events[0],actual_duration=.199)
        self.assertEqual(sum(c.kind=='stop' for c in self.commands(p)),2)

    def test_real_virtual_follow_same_timeline_and_play_retunes_without_stop(self):
        r=self.registry(fdd=2);app=Application(r);app.set_preset(PRESET)
        p=arrange(self.source([('Riff',0,[(0,.08,60),(.3,.38,62),(.6,.68,64)])]),r)
        timeline=compile_plan(p);lines,packets=[],[]
        real=RealOutput(r);real.link=SimpleNamespace(controller_status={'atx':'ON'},send_batch=lambda batch:lines.extend(batch))
        virtual=VirtualOutput(packets.append)
        real.dispatch(timeline.commands);virtual.dispatch(timeline.commands,epoch=1)
        self.assertEqual(packets[0]['commands'],[c.as_dict() for c in timeline.commands])
        self.assertEqual(sum(' STOP' in line for line in lines),1)
        self.assertGreater(sum(' PLAY ' in line for line in lines),1)
