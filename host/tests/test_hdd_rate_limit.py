"""Shared musical HDD budget; synthetic MIDI and execution commands, no hardware."""
from dataclasses import replace
from types import SimpleNamespace
import copy
import random
import unittest
import mido

import test_mechanical_arrangement as helpers
from playback.allocator import allocate
from playback.percussion_routing import source_drops, limit_plan, family, RATE_LIMIT_REASON
from playback.performance import PerformanceEvent, PerformancePlan, ReinforcementEvent
from runtime.arranger import arrange
from runtime.compiler import compile_plan

PRESETS = ('balanced','fdd_quality','dvd_lead_low_fdd','fdd_quality_adaptive',
           'instrument_roles','instrument_roles_unison','instrument_roles_duet',
           'instrument_roles_unison4','universal')


def item(ident,time,note=70,velocity=45):
    return dict(id=str(ident),track=0,order=ident,role='percussion',
                span=SimpleNamespace(start=time,note=note,channel=9,velocity=velocity))


def event(ident,time,note=70,velocity=45,device='hdd-1'):
    return PerformanceEvent(str(ident),0,'Drums',note,None,velocity,9,time,.02,
        device,'HDD_VCM',None,None,time,.084,'ACCEPTED',role='percussion')


def assert_budget(test,times):
    # Independent check at every possible left endpoint, including simultaneous hits.
    for start in times:
        test.assertLessEqual(sum(start<=t<start+1. for t in times),8)


class HddSelectionTests(unittest.TestCase):
    def test_half_open_windows_and_boundary_burst(self):
        exact=[item(i,0 if i<8 else 1) for i in range(16)]
        self.assertEqual(source_drops(exact,{}, {'hdd-1'}),set())
        burst=[item(i,.99 if i<8 else 1.01) for i in range(16)]
        omitted=source_drops(burst,{}, {'hdd-1'})
        self.assertEqual(len(omitted),8)
        assert_budget(self,[n['span'].start for n in burst if n['id'] not in omitted])

    def test_later_kick_and_snare_displace_weak_auxiliary_hits(self):
        notes=[item(i,i*.01) for i in range(8)]+[item(8,.5,36,106),item(9,.75,38,90)]
        omitted=source_drops(notes,{}, {'hdd-1'})
        self.assertEqual(len(omitted),2)
        self.assertNotIn('8',omitted);self.assertNotIn('9',omitted)
        self.assertEqual(family(54,9),'aux');self.assertEqual(family(70,9),'aux')
        self.assertEqual(family(82,9),'aux');self.assertEqual(family(41,9),'tom')

    def test_all_kicks_still_cannot_bypass_limit_or_shift_onsets(self):
        notes=[item(i,i*.02,36,127) for i in range(200)]
        before=copy.deepcopy(notes)
        omitted=source_drops(notes,{}, {'hdd-1'})
        assert_budget(self,[n['span'].start for n in notes if n['id'] not in omitted])
        self.assertEqual(notes,before)
        self.assertEqual(omitted,source_drops(list(reversed(notes)),{}, {'hdd-1'}))

    def test_sparse_offbeat_pattern_is_unchanged_and_manual_drops_use_no_budget(self):
        notes=[item(i,i*.137) for i in range(40)]
        self.assertFalse(source_drops(notes,{}, {'hdd-1'}))
        notes=[item(i,0) for i in range(24)]
        pins={str(i):SimpleNamespace(device_id=None) for i in range(16)}
        self.assertFalse(source_drops(notes,pins,{'hdd-1'}))
        self.assertFalse(source_drops(notes,{},set()))

    def test_random_polyphony_has_a_global_budget_and_deterministic_selection(self):
        rng=random.Random(854)
        notes=[item(i,rng.randrange(400)/20,rng.choice((36,38,42,49,54,70)),rng.randint(1,127)) for i in range(2000)]
        omitted=source_drops(notes,{}, {'hdd-1','hdd-2','hdd-3','hdd-4'})
        assert_budget(self,[n['span'].start for n in notes if n['id'] not in omitted])
        rng.shuffle(notes)
        self.assertEqual(omitted,source_drops(notes,{}, {'hdd-1','hdd-2','hdd-3','hdd-4'}))

    def test_final_plan_covers_reinforcement_preserves_tones_and_remaps_sidecars(self):
        hits=[event(i,.01*i) for i in range(8)]
        tone=replace(event('tone',.3),device_id='fdd-1',device_type='FDD',role='harmony',played_hz=220.)
        plan=PerformancePlan('fixture',hits+[tone],[{'id':'hdd-1','type':'HDD_VCM'},{'id':'hdd-2','type':'HDD_VCM'},{'id':'fdd-1','type':'FDD'}],{})
        plan.reinforcements=[ReinforcementEvent('0','hdd-2',.5,.084,0,127,kind='hit'),ReinforcementEvent('tone','fdd-1',2,.1,220,90)]
        plan.execution_articulation={'extra:0':{'kind':'HARD_HIT'},'extra:1':{'retained':True},'tone':{'retained':True}}
        limit_plan(plan)
        self.assertEqual(plan.events[-1],tone)
        self.assertEqual(len(plan.reinforcements),1)
        self.assertEqual(plan.execution_articulation['extra:0'],{'retained':True})
        self.assertEqual(plan.execution_articulation['tone'],{'retained':True})
        self.assertEqual(plan.articulation['hddRateLimit']['reinforcementDrops'],1)
        before=copy.deepcopy(plan)
        limit_plan(plan)
        self.assertEqual(plan,before)
        assert_budget(self,[c.time for c in compile_plan(plan).commands if c.kind=='hit'])

    def test_compiler_rejects_ninth_hit_and_accepts_eight_without_retiming(self):
        events=[event(i,i*.05,36,127) for i in range(9)]
        plan=PerformancePlan('eight-hit-boundary',events,[{'id':'hdd-1','type':'HDD_VCM'}],{})
        with self.assertRaisesRegex(ValueError,'at most 8 HIT'):
            compile_plan(plan)
        plan.events=events[:8]
        self.assertEqual([c.time for c in compile_plan(plan).commands if c.kind=='hit'],
                         [e.start for e in events[:8]])

    def test_manual_and_shifted_final_hits_are_limited_and_compiler_rejects_bypass(self):
        events=[event(i,.9 if i<8 else 1.1,36,127) for i in range(16)]
        plan=PerformancePlan('manual',events,[{'id':'hdd-1','type':'HDD_VCM'}],{})
        with self.assertRaisesRegex(ValueError,'HDD rate limit'):
            compile_plan(plan)
        limit_plan(plan)
        self.assertEqual(sum(e.played for e in plan.events),8)
        self.assertTrue(all(e.reason==RATE_LIMIT_REASON for e in plan.events if not e.played))
        assert_budget(self,[c.time for c in compile_plan(plan).commands if c.kind=='hit'])


class HddPresetTests(unittest.TestCase):
    setUp=helpers.MechanicalArrangementTests.setUp
    source=helpers.MechanicalArrangementTests.source
    registry=helpers.MechanicalArrangementTests.registry
    assert_feasible=helpers.MechanicalArrangementTests.assert_feasible

    def test_every_preset_obeys_shared_compiled_budget_and_keeps_source_timing(self):
        source=self.source([('Drums',9,[(i*.05,i*.05+.01,n) for i in range(80) for n in (36,38,42,54,70)])])
        for preset in PRESETS:
            with self.subTest(preset=preset):
                r=self.registry(fdd=0,dvd=0)
                for d in r.devices:
                    d['enabled']=d['type']=='HDD_VCM'
                r.document['parameters']['arrangementPreset']=preset
                plan=arrange(source,r)
                self.assert_feasible(plan,r)
                hits=[c for c in compile_plan(plan).commands if c.kind=='hit']
                self.assertTrue(hits)
                assert_budget(self,[c.time for c in hits])
                self.assertTrue(any(e.reason==RATE_LIMIT_REASON for e in plan.events))
                originals={e.id:e.start for e in plan.events}
                self.assertTrue(all(abs(c.time-originals[c.source_id])<1e-9 for c in hits))

    def test_legacy_allocator_with_idle_hdd_copies_obeys_same_budget(self):
        r=self.registry(fdd=0,dvd=0)
        for d in r.devices:d['enabled']=d['type']=='HDD_VCM'
        config=r.configuration()
        for d in config.devices:d['mode']='virtual'
        config.idle_reinforcement.update(enabled=True,deviceTypes=['HDD_VCM'],minScore=0,maxCopiesPerEvent=2,percussionCooldownMs=0)
        source=self.source([('Drums',9,[(i*.1,i*.1+.01,36) for i in range(40)])])
        midi=mido.MidiFile(source.path)
        for track in midi.tracks:
            for message in track:
                if message.type=='note_on':message.velocity=127
        midi.save(source.path)
        source=type(source)(source.path)
        plan=allocate(source,config)
        hits=[c for c in compile_plan(plan).commands if c.kind=='hit']
        self.assertTrue(hits)
        self.assertGreater(plan.articulation['hddRateLimit']['reinforcementDrops'],0)
        assert_budget(self,[c.time for c in hits])


if __name__=='__main__':unittest.main()
