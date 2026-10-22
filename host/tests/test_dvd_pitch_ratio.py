"""Acoustic Hz is converted to steps/s once, by the profile executor."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime.registry import DeviceRegistry
from runtime.application import Application
from runtime.compiler import ExecutionCommand
from playback.hardware_profiles import HardwareNote, HardwareDeviceState, evaluate, advance_state, execution_command
from playback.hardware_arranger import fold_for_profile
from test_runtime import Link

class DvdPitchRatioTests(unittest.TestCase):
    def test_individual_hypothesis_not_global_change(self):
        r=DeviceRegistry()
        for i in range(1,5):
            p=r.profile(f'DVD_STEPPER_{i}');q=p.quantities['pitchRatio']
            self.assertEqual(q.value,.5);self.assertEqual(q.evidence_type,'HYPOTHESIS');self.assertEqual(q.confidence,'LOW')
            self.assertTrue(p.get('continuousRotation'))
        self.assertEqual({d['lane'] for d in r.devices if d['type']=='DVD_SLED'},
                         {f'sled:{i}' for i in range(1,5)})
        self.assertEqual(r.profile('fdd-1').get('pitchRatio'),1.)
    def test_planner_and_projection_use_acoustic_hz(self):
        r=DeviceRegistry()
        for i in range(1,5):
            p=r.profile(f'DVD_STEPPER_{i}')
            for hz,steps in ((200,400),(440,880),(500,1000)):
                with self.subTest(device=i,hz=hz):
                    state=HardwareDeviceState(position=139.)
                    n=HardwareNote(hz,1.,0);ev=evaluate(p,n,state)
                    self.assertTrue(ev.authorized);self.assertEqual(ev.audio_frequency,hz);self.assertEqual(ev.step_rate,steps)
                    advance_state(state,p,n,ev)
                    self.assertEqual(state.current_step_rate,steps);self.assertEqual(state.current_frequency,hz)
                    self.assertGreater(state.position,140);self.assertEqual(state.travel_reversals,0)
            self.assertTrue(evaluate(p,HardwareNote(5000,1,0)).authorized)
            self.assertFalse(evaluate(p,HardwareNote(5001,1,0)).authorized)
            fold=fold_for_profile(69,0.001,5000,'auto',p)
            self.assertEqual(fold.hz,440);self.assertEqual(fold.octave_shift,0)
    def test_profile_sent_separately_from_unscaled_play_command(self):
        app=Application();link=Link();app.real.attach(link);app.real.configure()
        for i in range(1,5):
            ident=f'DVD_STEPPER_{i}';p=app.registry.profile(ident)
            self.assertIn(execution_command(p,f'sled:{i}'),link.sent)
            self.assertTrue(execution_command(p,f'sled:{i}').endswith(' 0.5'))
            for hz in (200,440,500):
                app.real.dispatch([ExecutionCommand(0,ident,'tone',1,hz)])
                self.assertIn(f'SLED {i} PLAY {hz:.2f}',link.sent)
                with patch.object(app.virtual,'emit') as emit:
                    app.virtual.owner='fake-browser';app.virtual.dispatch([ExecutionCommand(0,ident,'tone',1,hz)],epoch=1)
                    self.assertEqual(emit.call_args.args[0]['commands'][0]['hz'],hz)

    def test_dvd4_correction_is_individual_low_confidence_observation(self):
        r=DeviceRegistry()
        q=r.profile('DVD_STEPPER_4').quantities['pitchRatio']
        self.assertIn('2026-10-19',q.source)
        self.assertIn('220 Hz',q.source)
        self.assertIsNone(q.uncertainty['quantitativeError'])
        self.assertEqual(r.profiles.effective('DVD_SLED').get('pitchRatio'),1.)
        self.assertEqual(execution_command(r.profile('DVD_STEPPER_4'),'sled:4'),'SLED 4 PROFILE 0 5000 0.5')
