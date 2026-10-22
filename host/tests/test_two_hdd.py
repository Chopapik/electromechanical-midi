"""Two active percussion voices, retained four-channel hardware capacity."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import test_mechanical_arrangement as helpers
from test_backend_capacity import PRESETS
from test_runtime import Link
from runtime.arranger import arrange
from runtime.compiler import ExecutionCommand,compile_plan
from runtime.outputs import RealOutput
from runtime.registry import DeviceRegistry
from runtime.router import Router
from playback.percussion_routing import peak_hits,Rhythm
from playback.hardware_profiles import HardwareDeviceState,HardwareNote,evaluate

ACTIVE={'hdd_vcm-1','hdd_vcm-2'}
INACTIVE={'hdd_vcm-3','hdd_vcm-4'}


class TwoHddTests(unittest.TestCase):
    setUp=helpers.MechanicalArrangementTests.setUp
    source=helpers.MechanicalArrangementTests.source
    assert_feasible=helpers.MechanicalArrangementTests.assert_feasible

    def test_catalog_retains_four_channels_and_profiles_but_enables_only_two(self):
        r=DeviceRegistry()
        self.assertEqual(len(r.devices),18)
        self.assertEqual(sum(d['enabled'] for d in r.devices),16)
        self.assertEqual({d['id'] for d in r.devices if d['type']=='HDD_VCM' and d['enabled']},ACTIVE)
        for ident in INACTIVE:
            self.assertIsNotNone(r.profile(ident))
        output=RealOutput(r);link=Link();link.controller_status['speaker_fx']='1'
        output.attach(link);output.configure()
        for n in (1,2):self.assertIn(f'HDD {n} ENABLE 1',link.sent)
        for n in (3,4):
            self.assertEqual([line for line in link.sent if line.startswith(f'HDD {n} ')],[f'HDD {n} ENABLE 0'])

    def test_router_ignores_inactive_hits_in_readiness_and_both_outputs_but_keeps_stop(self):
        r=DeviceRegistry();real,virtual=Mock(),Mock();router=Router(r,real,virtual)
        commands=[ExecutionCommand(0,f'hdd_vcm-{i}','hit') for i in range(1,5)]
        stops=[ExecutionCommand(1,ident,'stop') for ident in sorted(INACTIVE)]
        for mode,output in [('REAL',real),('VIRTUAL',virtual)]:
            with self.subTest(mode=mode):
                router.mode=mode
                router.ready(commands)
                self.assertEqual(output.ready.call_args.args[0],commands[:2])
                router.dispatch(commands+stops,epoch=7)
                self.assertEqual(output.dispatch.call_args.args[0],commands[:2]+stops)
                output.reset_mock()
                router.dispatch(commands[2:])
                output.dispatch.assert_not_called()

    def test_every_preset_uses_only_two_hdd_and_respects_physical_and_global_limits(self):
        source=self.source([('Drums',9,[(i*.1,i*.1+.02,n) for i in range(50) for n in (36,38,42,54,70)])])
        for preset in PRESETS:
            with self.subTest(preset=preset):
                r=DeviceRegistry();r.document['parameters']['arrangementPreset']=preset
                plan=arrange(source,r);self.assert_feasible(plan,r)
                hits=[c for c in compile_plan(plan).commands if c.kind=='hit']
                self.assertTrue(hits)
                self.assertLessEqual({c.device_id for c in hits},ACTIVE)
                self.assertLessEqual(peak_hits(c.time for c in hits),12)
                self.assertFalse(any(e.device_id in INACTIVE for e in plan.reinforcements))

    def test_dense_hats_do_not_block_upcoming_kick_or_snare_on_their_owner(self):
        notes=[(i*.1,i*.1+.02,42) for i in range(30)]
        notes += [(i*.5+.19,i*.5+.21,36) for i in range(5)]
        notes += [(i*.5+.44,i*.5+.46,38) for i in range(5)]
        source=self.source([('Drums',9,notes)])
        for preset in ('balanced','instrument_roles_unison4','universal'):
            with self.subTest(preset=preset):
                r=DeviceRegistry();r.document['parameters']['arrangementPreset']=preset
                plan=arrange(source,r);self.assert_feasible(plan,r)
                for note,owner in [(36,'hdd_vcm-1'),(38,'hdd_vcm-2')]:
                    backbone=[e for e in plan.events if e.note==note]
                    self.assertEqual(len(backbone),5)
                    self.assertTrue(all(e.played and e.device_id==owner and abs(e.actual_start-e.start)<1e-9 for e in backbone))
                self.assertTrue(any(e.played and e.note==42 for e in plan.events))

    def test_without_kick_and_snare_both_hdd_can_play_existing_percussion(self):
        source=self.source([('Drums',9,[(i*.25,i*.25+.02,n) for i in range(8) for n in (42,49)])])
        plan=arrange(source,DeviceRegistry());self.assert_feasible(plan,DeviceRegistry())
        hits=[c for c in compile_plan(plan).commands if c.kind=='hit']
        self.assertEqual({c.device_id for c in hits},ACTIVE)
        self.assertEqual(len(hits),16)

    def test_live_snare_can_borrow_kick_lane_even_before_a_future_kick(self):
        r=DeviceRegistry()
        kick={'role':'percussion','span':SimpleNamespace(start=.25,note=36,channel=9)}
        snare={'role':'percussion','span':SimpleNamespace(start=.1,note=38,channel=9)}
        slots=[SimpleNamespace(device=SimpleNamespace(id=ident)) for ident in sorted(ACTIVE)]
        rhythm=Rhythm([kick],slots,{ident:r.by_id[ident]['lane'] for ident in ACTIVE})
        profile=r.profile('hdd_vcm-1');state=HardwareDeviceState();note=HardwareNote(None,.084,.1)
        self.assertTrue(rhythm.preserves_backbeat(snare,'hdd_vcm-1',profile,state,note,evaluate(profile,note,state)))


if __name__=='__main__':unittest.main()
