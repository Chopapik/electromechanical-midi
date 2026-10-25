"""Rhythmic source selection and VCM roles; software-only actuator contracts."""
from dataclasses import asdict
from types import SimpleNamespace
import unittest
import test_mechanical_arrangement as helpers
from playback.percussion_routing import Rhythm,family
from playback.hdd_articulation import classify,adapt
from runtime.arranger import arrange
from runtime.compiler import compile_plan

class PercussionRoutingTests(unittest.TestCase):
    setUp=helpers.MechanicalArrangementTests.setUp
    tearDown=helpers.MechanicalArrangementTests.tearDown
    source=helpers.MechanicalArrangementTests.source
    registry=helpers.MechanicalArrangementTests.registry
    assert_feasible=helpers.MechanicalArrangementTests.assert_feasible

    def plan(self,tracks):
        registry=self.registry(fdd=8,dvd=4)
        registry.document['parameters']['arrangementPreset']='instrument_roles_unison4'
        for d in registry.devices:
            if d['type']=='HDD_VCM':d['enabled']=True
        plan=arrange(self.source(tracks),registry)
        self.assert_feasible(plan,registry)
        return plan,registry

    def test_overloaded_chord_preserves_kick_and_snare_before_hats(self):
        plan,_=self.plan([('Drums',9,[(0,.02,n) for n in (42,46,49,41,38,36)])])
        hits=[e for e in plan.events if e.played]
        self.assertEqual(len(hits),4)
        self.assertLessEqual({36,38},{e.note for e in hits})
        self.assertTrue(all(e.actual_start==e.start for e in hits))
        self.assertTrue(all(e.device_type=='HDD_VCM' for e in hits))

    def test_kick_snare_and_hat_prefer_stable_different_lanes(self):
        # Keep this lane-preference fixture below the shared eight-hit budget.
        plan,_=self.plan([('Drums',9,[(i*.5,i*.5+.02,n) for i in range(8) for n in (36,38,42)])])
        by_note={n:{e.device_id for e in plan.events if e.played and e.note==n} for n in (36,38,42)}
        self.assertTrue(all(len(ids)==1 for ids in by_note.values()))
        self.assertEqual(len(set.union(*by_note.values())),3)
        self.assertEqual(sum(e.played for e in plan.events),24)

    def test_ordinal_lane_mapping_is_independent_of_device_labels(self):
        slots=[SimpleNamespace(device=SimpleNamespace(id=i)) for i in ('a','z')]
        rhythm=Rhythm([],slots,{'z':'hdd:1','a':'hdd:2'})
        self.assertEqual(rhythm.roles,{'z':'kick','a':'snare'})
        self.assertEqual(family(36,0),'tom')
        self.assertEqual(family(36,9),'kick')

    def test_dense_drums_obey_full_chronology_and_have_no_generated_hits(self):
        tracks=[('Drums',9,[(i*.025,i*.025+.01,n) for i in range(80) for n in (36,38,42,49)])]
        plan,registry=self.plan(tracks)
        commands=[c for c in compile_plan(plan).commands if c.kind=='hit']
        sources={e.id:e for e in plan.events}
        self.assertTrue(commands)
        self.assertEqual(len(commands),len({c.source_id for c in commands}))
        self.assertTrue(all(c.source_id in sources for c in commands))
        self.assertTrue(all(abs(c.time-sources[c.source_id].start)<=.03+1e-8 for c in commands))
        for event in plan.events:
            if event.played:
                neighbors=[abs(other.actual_start-event.actual_start) for other in plan.events
                           if other.played and other.device_id==event.device_id and other.id!=event.id]
                expected=adapt(classify(event.note,event.channel,event.velocity,event.articulation),min(neighbors,default=float('inf')))
                self.assertEqual(plan.execution_articulation[event.id],asdict(expected))
