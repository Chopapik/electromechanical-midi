"""Four real source voices and discrete attack envelopes, without physical I/O."""
import copy
import unittest
from collections import defaultdict
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import test_mechanical_arrangement as helpers
from playback.allocator import allocate, ManualPin
from playback.fdd_expression import PRESET, SOLO_PRESET, Phrases, finalize, without_accents
from playback.performance import ReinforcementEvent
from playback.orchestra import parse_policy
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.registry import PlanningProfiles
from runtime.application import Application
from runtime.outputs import RealOutput, VirtualOutput


class ExpressiveTests(unittest.TestCase):
    setUp = helpers.MechanicalArrangementTests.setUp
    source = helpers.MechanicalArrangementTests.source
    assert_feasible = helpers.MechanicalArrangementTests.assert_feasible

    def registry(self, fdd=8, dvd=0):
        r = helpers.MechanicalArrangementTests.registry(self, fdd=fdd, dvd=dvd)
        r.document['parameters'].update(arrangementPreset=PRESET, fddFixedToneMs=200.,
            mechanicalSustain=True, sourceContinuity=True)
        return r

    def tones(self, plan):
        return [c for c in compile_plan(plan).commands if c.kind == 'tone' and c.device_id.startswith('fdd-')]

    def test_four_independent_parts_receive_stable_pairs_and_real_pitches(self):
        source = self.source([(name, i, [(j*.3, j*.3+.12, note+j%2) for j in range(8)])
            for i, (name, note) in enumerate(zip(('A','B','C','D'), (60,64,67,71)))])
        r = self.registry()
        p = arrange(source, r)
        groups = p.hardware['fddExpressive']['groups']
        self.assertEqual(groups, [['fdd-1','fdd-2'], ['fdd-3','fdd-4'], ['fdd-5','fdd-6'], ['fdd-7','fdd-8']])
        for start in (0., .3, .6):
            events = [e for e in p.events if e.played and abs(e.actual_start-start)<1e-6]
            self.assertEqual(len(events), 4)
            self.assertEqual(len({e.track for e in events}), 4)
            self.assertEqual(len({next(i for i,g in enumerate(groups) if e.device_id in g) for e in events}), 4)
        self.assertTrue(all(e.actual_start == e.start and (e.played_note-e.note)%12 == 0
                            for e in p.events if e.played))
        self.assertEqual(p.policy['fddFixedToneMs'], 0)
        self.assertEqual(r.document['parameters']['fddFixedToneMs'], 200)
        self.assert_feasible(p, r)

    def test_rhythmic_gates_preserve_short_long_difference_and_rests(self):
        r = self.registry(fdd=2)
        source = self.source([('Riff',0,[(0,.07,60),(.3,.46,62),(.6,.69,64),(3,4,65)])])
        p = arrange(source, r)
        events = [e for e in p.events if e.played]
        self.assertEqual(len(events), 4)
        for e in events[:3]:self.assertAlmostEqual(e.actual_duration,e.duration)
        self.assertGreater(events[1].actual_duration,events[0].actual_duration)
        self.assertLessEqual(events[3].actual_duration,.18)
        self.assertTrue(all(e.end < 1 for e in events if e.start < 3))
        self.assert_feasible(p,r)

    def test_new_bass_entry_has_priority_over_four_accompaniment_owners(self):
        from playback.analysis import analyze
        r=self.registry()
        s=self.source([(name,i,[(j*.25,j*.25+.15,n) for j in range(6)])
            for i,(name,n) in enumerate(zip(('A','B','C','D'),(60,64,67,70)))]+
            [('Bass',4,[(.5,.65,35)])])
        analysis=analyze(s)
        analysis=replace(analysis,roles={f'{t.index}:{n.order}':('bass' if t.name=='Bass' else 'harmony')
            for t in s.tracks for n in s.notes(t.index)})
        p=allocate(s,r.configuration(),hardware_context=PlanningProfiles(r),midi_analysis=analysis)
        bass=next(e for e in p.events if e.track_name=='Bass')
        self.assertTrue(bass.played)
        self.assertEqual(bass.actual_start,bass.start)
        self.assertLessEqual(sum(e.played and e.device_type=='FDD' and abs(e.start-.5)<1e-6
                                 for e in p.events),4)
        self.assert_feasible(p,r)

    def test_accents_reinforce_source_attack_then_decay_to_one_drive(self):
        r = self.registry(fdd=2)
        p = arrange(self.source([('Riff',0,[(i*.25,i*.25+.15,60+i%3) for i in range(12)])]),r)
        copies = [e for e in p.reinforcements if e.kind == 'FDD_ACCENT']
        self.assertGreater(len(copies),0)
        self.assertLess(len(copies),sum(e.played for e in p.events))
        sources={e.id:e for e in p.events}
        for extra in copies:
            e=sources[extra.source_id]
            self.assertEqual((extra.start,extra.hz),(e.actual_start,e.played_hz))
            self.assertLess(extra.duration,e.actual_duration)
            self.assertNotEqual(extra.device_id,e.device_id)
            art=p.execution_articulation['extra:'+str(p.reinforcements.index(extra))]
            self.assertAlmostEqual(art['gate'],extra.duration)
        self.assertGreater(p.hardware['fddExpressive']['singleDriveNotes'],0)
        self.assert_feasible(p,r)

    def test_fast_riff_rotates_attacks_without_weakening_per_drive_interval(self):
        r=self.registry()
        p=arrange(self.source([('Riff',0,[(i*.09,i*.09+.07,60+i%4) for i in range(24)])]),r)
        self.assertEqual(sum(e.played for e in p.events),24)
        lanes=defaultdict(list)
        for c in self.tones(p):lanes[c.device_id].append(c)
        for notes in lanes.values():
            self.assertTrue(all(b.time-a.time>=.12-1e-9 for a,b in zip(notes,notes[1:])))
        self.assertTrue(all(e.start==e.actual_start for e in p.events if e.played))
        self.assert_feasible(p,r)

    def test_missing_pair_members_keep_physical_group_ids_and_single_notes(self):
        r=self.registry()
        for ident in ('fdd-2','fdd-3','fdd-4','fdd-5','fdd-6','fdd-7','fdd-8'):
            r.by_id[ident]['enabled']=False
        p=arrange(self.source([('Riff',0,[(i*.3,i*.3+.1,60+i%3) for i in range(5)])]),r)
        self.assertTrue(all(e.played for e in p.events))
        self.assertEqual(p.hardware['fddExpressive']['groups'],[['fdd-1'],[],[],[]])
        self.assertFalse(p.reinforcements)
        self.assertEqual({c.device_id for c in self.tones(p)},{'fdd-1'})

    def test_optional_copy_can_be_rejected_without_losing_primary(self):
        r=self.registry(fdd=2)
        from playback.hardware_profiles import evaluate as original
        def evaluate(profile,note,state):
            result=original(profile,note,state)
            return replace(result,authorized=False) if note.duration<.1 else result
        with patch('playback.fdd_pairs.evaluate',side_effect=evaluate):
            p=arrange(self.source([('Riff',0,[(0,.15,60)])]),r)
        self.assertTrue(p.events[0].played)
        self.assertEqual(p.hardware['fddExpressive']['accentCopies'],0)
        self.assert_feasible(p,r)

    def test_finalize_removes_orphan_accents_and_preserves_other_sidecars(self):
        r=self.registry(fdd=2)
        p=arrange(self.source([('Riff',0,[(0,.15,60)])]),r)
        source=p.events[0]
        p.reinforcements.append(ReinforcementEvent(source.id,'DVD_STEPPER_1',1,.3,300,80))
        key='extra:'+str(len(p.reinforcements)-1)
        p.execution_articulation[key]={'gate':.3,'sentinel':'DVD'}
        p.events=[replace(source,device_id=None,device_type=None,outcome='DROPPED')]
        finalize(p)
        self.assertEqual(len(p.reinforcements),1)
        self.assertEqual(p.execution_articulation['extra:0'],{'gate':.3,'sentinel':'DVD'})

    def test_manual_fdd_reservations_require_explicitly_leaving_auto_experiment(self):
        r=self.registry(fdd=2)
        s=self.source([('Riff',0,[(0,.1,60)])])
        with self.assertRaisesRegex(ValueError,'ręczne przypisania'):
            allocate(s,r.configuration(),hardware_context=PlanningProfiles(r),
                     pins={'1:0':ManualPin('fdd-1','manual')})

    def test_non_fdd_backbone_is_preserved_during_revoicing(self):
        r=self.registry(dvd=4)
        s=self.source([('Riff',0,[(i*.2,i*.2+.1,60+i%3) for i in range(8)]),
                       ('Pad',1,[(0,3,n) for n in (45,52,57)])])
        from playback.fdd_pairs import arrange as revoice
        def check(plan,*args,**kwargs):
            before=copy.deepcopy(plan)
            result=revoice(plan,*args,**kwargs)
            types={d['id']:d['type'] for d in plan.devices}
            self.assertEqual([e for e in before.events if e.played and e.device_type!='FDD'],
                             [e for e in result.events if e.played and e.device_type!='FDD'])
            self.assertEqual([e for e in before.reinforcements if types[e.device_id]!='FDD'],
                             [e for e in result.reinforcements if types[e.device_id]!='FDD'])
            return result
        with patch('playback.fdd_pairs.arrange',side_effect=check):p=arrange(s,r)
        self.assertTrue(any(e.device_type=='DVD_SLED' and e.actual_duration>=2.9 for e in p.events if e.played))
        self.assert_feasible(p,r)

    def test_no_future_fdd_recovery_breaks_pair_budget_and_results_are_deterministic(self):
        r=self.registry(dvd=2)
        s=self.source([(str(i),i,[(j*.13,j*.13+.11,48+i+j%7) for j in range(16)]) for i in range(6)])
        a,b=arrange(s,r),arrange(s,r)
        self.assertEqual(compile_plan(a),compile_plan(b))
        self.assertEqual(a.hardware['fddExpressive'],b.hardware['fddExpressive'])
        for e in a.reinforcements:
            if e.device_id.startswith('fdd-'):self.assertEqual(e.kind,'FDD_ACCENT')
        self.assert_feasible(a,r)

    def test_real_virtual_and_application_selection_share_the_same_timeline(self):
        r=self.registry(fdd=2)
        app=Application(r);app.set_preset(PRESET)
        p=arrange(self.source([('Riff',0,[(0,.15,60),(.25,.35,62)])]),r)
        timeline=compile_plan(p)
        lines,packets=[],[]
        real=RealOutput(r);real.link=SimpleNamespace(controller_status={'atx':'ON'},send_batch=lambda batch:lines.extend(batch))
        virtual=VirtualOutput(packets.append)
        real.dispatch(timeline.commands);virtual.dispatch(timeline.commands,epoch=1)
        self.assertEqual(packets[0]['commands'],[c.as_dict() for c in timeline.commands])
        self.assertEqual(sum(' PLAY ' in line for line in lines),sum(c.kind=='tone' for c in timeline.commands))

    def test_strict_tracks_keeps_existing_200_ms_experiment(self):
        r=self.registry()
        r.document['routing']={'mode':'STRICT_TRACKS','tracks':[1,None,None,None]}
        p=arrange(self.source([('Riff',0,[(0,.1,60)])]),r)
        self.assertNotIn('fddExpressive',p.hardware)
        self.assertEqual(p.events[0].actual_duration,.2)

    def test_relative_velocity_changes_and_tempo_affect_articulation(self):
        r=self.registry(fdd=2)
        s=self.source([('Riff',0,[(i*.25,i*.25+.2,60) for i in range(5)])])
        p=arrange(s,r)
        events=[replace(e,velocity=115 if i==1 else 80) for i,e in enumerate(p.events)]
        phr=Phrases(events,s,parse_policy({}))
        self.assertTrue(phr.accent(events[1]))
        self.assertFalse(phr.accent(events[3]))
        slow=phr.gate(events[0],130.,r.profile('fdd-1'),.01,False,.003)
        fast_source=SimpleNamespace(tempo=SimpleNamespace(_segments=[SimpleNamespace(tick=0,seconds=0,tempo=250000)]),
            _midi=s._midi,ticks_per_beat=s.ticks_per_beat)
        fast=Phrases(events,fast_source,parse_policy({})).gate(events[0],130.,r.profile('fdd-1'),.01,False,.003)
        self.assertLess(fast,slow)

    def test_solo_only_mutes_final_copies_without_reallocating_dense_voices(self):
        r=self.registry(dvd=4)
        s=self.source([(str(i),i,[(j*.09,j*.09+.07,48+i+j%7) for j in range(32)])
                       for i in range(6)])
        a=arrange(s,r)
        self.assertTrue(any(e.kind=='FDD_ACCENT' for e in a.reinforcements))
        r.document['parameters']['arrangementPreset']=SOLO_PRESET
        b=arrange(s,r)
        self.assertEqual(b.policy['arrangementPreset'],SOLO_PRESET)
        self.assertEqual(r.document['parameters']['arrangementPreset'],SOLO_PRESET)
        self.assertEqual(a.events,b.events)
        self.assertEqual([e for e in a.reinforcements if e.kind!='FDD_ACCENT'],b.reinforcements)
        self.assertEqual({e.id:a.execution_articulation.get(e.id) for e in a.events},
                         {e.id:b.execution_articulation.get(e.id) for e in b.events})
        for e in b.reinforcements:
            old=a.reinforcements.index(e);new=b.reinforcements.index(e)
            self.assertEqual(a.execution_articulation.get('extra:'+str(old)),
                             b.execution_articulation.get('extra:'+str(new)))
        non_fdd={d['id'] for d in a.devices if d['type']!='FDD'}
        self.assertEqual([c for c in compile_plan(a).commands if c.device_id in non_fdd],
                         [c for c in compile_plan(b).commands if c.device_id in non_fdd])
        self.assertEqual(b.hardware['fddExpressive']['accentCopies'],0)
        self.assertEqual(b.hardware['fddExpressive']['singleDriveNotes'],
                         a.hardware['fddExpressive']['primaryNotes'])
        self.assertEqual(b.hardware['fddExpressive']['suppressedAccentCopies'],
                         a.hardware['fddExpressive']['accentCopies'])
        self.assertEqual(b.hardware['fddExpressive']['gateRangeMs'],a.hardware['fddExpressive']['gateRangeMs'])
        self.assertEqual(len(self.tones(b)),len(self.tones(a))-a.hardware['fddExpressive']['accentCopies'])
        self.assertEqual(compile_plan(b),compile_plan(arrange(s,r)))
        self.assert_feasible(b,r)

    def test_solo_reindexes_held_dvd_and_speaker_sidecars(self):
        r=self.registry(fdd=2)
        p=arrange(self.source([('Riff',0,[(0,.15,60)])]),r)
        self.assertTrue(p.reinforcements)
        for ident in ('DVD_STEPPER_1','vhs-1'):
            p.reinforcements.append(ReinforcementEvent(p.events[0].id,ident,1,.3,300,80))
            p.execution_articulation['extra:'+str(len(p.reinforcements)-1)]={'sentinel':ident}
        without_accents(p,r)
        self.assertEqual([e.device_id for e in p.reinforcements],['DVD_STEPPER_1','vhs-1'])
        self.assertEqual({k:v for k,v in p.execution_articulation.items() if k.startswith('extra:')},
                         {'extra:0':{'sentinel':'DVD_STEPPER_1'},'extra:1':{'sentinel':'vhs-1'}})

    def test_solo_respects_missing_devices_and_strict_tracks(self):
        r=self.registry()
        for d in r.devices:d['enabled']=d['id']=='fdd-1'
        r.document['parameters']['arrangementPreset']=SOLO_PRESET
        s=self.source([('Riff',0,[(0,.1,60)])])
        p=arrange(s,r)
        self.assertTrue(p.events[0].played)
        self.assertEqual(p.hardware['fddExpressive']['accentCopies'],0)
        r.document['routing']={'mode':'STRICT_TRACKS','tracks':[1,None,None,None]}
        p=arrange(s,r)
        self.assertEqual(p.events[0].actual_duration,.2)
        self.assertNotIn('fddExpressive',p.hardware)
        self.assertEqual(p.policy['arrangementPreset'],SOLO_PRESET)

    def test_solo_does_not_drop_notes_to_hide_a_chronology_failure(self):
        r=self.registry(fdd=2)
        p=arrange(self.source([('Riff',0,[(0,.15,60)])]),r)
        before=copy.deepcopy(p)
        with patch('playback.mechanical_arrangement.ChronologyCache.check',return_value=None):
            with self.assertRaisesRegex(ValueError,'niewykonalna chronologia'):
                without_accents(p,r)
        self.assertEqual(p,before)

    def test_solo_selection_and_outputs_share_the_same_timeline(self):
        r=self.registry(fdd=2)
        app=Application(r);app.set_preset(SOLO_PRESET)
        p=arrange(self.source([('Riff',0,[(0,.15,60),(.25,.35,62)])]),r)
        lines,packets=[],[]
        real=RealOutput(r);real.link=SimpleNamespace(controller_status={'atx':'ON'},send_batch=lambda batch:lines.extend(batch))
        virtual=VirtualOutput(packets.append)
        timeline=compile_plan(p)
        real.dispatch(timeline.commands);virtual.dispatch(timeline.commands,epoch=1)
        self.assertEqual(packets[0]['commands'],[c.as_dict() for c in timeline.commands])
        self.assertEqual(sum(' PLAY ' in line for line in lines),len(self.tones(p)))
        self.assertFalse(any(e.kind=='FDD_ACCENT' for e in p.reinforcements))
