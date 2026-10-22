"""Continuous DVD rotation uses protocol timing, never measured musical bands."""
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'host'))
from playback.hardware_profiles import HardwareDeviceState, HardwareNote, evaluate, advance_sled, execution_command
from runtime.application import Application
from runtime.arranger import arrange
from runtime.registry import DeviceRegistry
from runtime.outputs import OutputError
from midi_source import MidiSource
from test_allocator import write_tracks
from test_runtime import Link

class ContinuousDvdTests(unittest.TestCase):
    def setUp(self): self.registry=DeviceRegistry()
    def test_all_four_dvds_accept_previously_blocked_frequencies(self):
        for ident in range(1,5):
            profile=self.registry.profile(f'DVD_STEPPER_{ident}')
            self.assertTrue(profile.get('continuousRotation'))
            self.assertIn('PROFILE 0 ',execution_command(profile,f'sled:{ident}'))
            maximum=10000*profile.get('pitchRatio')
            for hz in (10,49,150,220,490,1200,maximum):
                with self.subTest(ident=ident,hz=hz):
                    self.assertTrue(evaluate(profile,HardwareNote(hz,.5,0)).authorized)
            self.assertFalse(evaluate(profile,HardwareNote(maximum+1,.5,0)).authorized)
    def test_projection_moves_past_old_travel_limit_without_reversing(self):
        state=HardwareDeviceState(position=139.)
        advance_sled(state,self.registry.profile('DVD_STEPPER_1'),1000,2)
        self.assertGreater(state.position,1000)
        self.assertEqual(state.direction,1)
        self.assertEqual(state.travel_reversals,0)
    def test_catalog_and_real_configuration_expose_continuous_mode(self):
        catalog=[d for d in self.registry.catalog() if d['type']=='DVD_SLED']
        self.assertEqual(len(catalog),4)
        self.assertEqual([d['id'] for d in catalog if d['enabled']], [f'DVD_STEPPER_{i}' for i in range(1,5)])
        self.assertTrue(all(d['enabled'] and d['reason'] is None for d in catalog))
        self.assertTrue(all(d['continuousRotation'] and d['bands']==[] for d in catalog))
        app=Application(); link=Link();app.real.attach(link);app.real.configure()
        self.assertTrue(app.registry.by_id['DVD_STEPPER_4']['enabled'])
        for ident in range(1,5):
            self.assertTrue(any(line.startswith(f'SLED {ident} PROFILE 0 ') for line in link.sent))
            self.assertIn(f'SLED {ident} DIR FWD',link.sent)
        self.assertFalse(any(' PLAY ' in line for line in link.sent))
    def test_old_firmware_requires_update_before_dvd_play(self):
        app=Application();link=Link();link.controller_status.pop('dvd_continuous')
        app.real.attach(link)
        with self.assertRaisesRegex(OutputError,'Wgraj nowe firmware'): app.real.configure()
        self.assertFalse(any(' PLAY ' in line for line in link.sent))
    def test_arranger_lowers_high_dvd_note_by_octaves_to_600_hz(self):
        registry=DeviceRegistry()
        for d in registry.devices: d['enabled']=d['id']=='DVD_STEPPER_1'
        with tempfile.TemporaryDirectory() as directory:
            source=MidiSource(write_tracks(Path(directory)/'high.mid',[('Guitar',0,[(0,.5,84)])]))
            plan=arrange(source,registry)
        event=next(event for event in plan.events if event.played)
        self.assertEqual(event.device_id,'DVD_STEPPER_1')
        self.assertEqual(event.played_note,72)
        self.assertLessEqual(event.played_hz,600)
        self.assertEqual(event.note,84)
        self.assertEqual(event.actual_start,0)

    def test_dvd_ceiling_all_auto_presets_and_multiple_octaves(self):
        for preset in ('balanced','fdd_quality','dvd_lead_low_fdd','fdd_quality_adaptive','instrument_roles','instrument_roles_unison','instrument_roles_duet', 'universal'):
            with self.subTest(preset=preset):
                registry=DeviceRegistry()
                for d in registry.devices: d['enabled']=d['id']=='DVD_STEPPER_1'
                registry.document['parameters']['arrangementPreset']=preset
                notes=[(i,.5,n) for i,n in enumerate((69,74,75,84,96))]
                with tempfile.TemporaryDirectory() as directory:
                    source=MidiSource(write_tracks(Path(directory)/'ceiling.mid',[('Guitar',0,notes)]))
                    plan=arrange(source,registry)
                events=[e for e in plan.events if e.played]
                self.assertEqual(len(events),5)
                self.assertEqual([e.played_note for e in events],[69,74,63,72,72])
                self.assertEqual([e.note for e in events],[69,74,75,84,96])
                self.assertEqual([e.actual_start for e in events],[0,1,2,3,4])
                from runtime.compiler import compile_plan
                self.assertTrue(all(c.hz<=600 for c in compile_plan(plan).commands))
