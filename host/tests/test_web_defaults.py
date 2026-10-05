"""The normal web entry point starts with the user's selected audition defaults."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playback.engine import PlaybackEngine
from playback.orchestra import web_startup_config
from web import server


class WebDefaultsTest(unittest.TestCase):
    def test_defaults_reach_virtual_config_and_allocation_policy(self):
        engine=PlaybackEngine(auto_arrange=True)
        try:
            engine.configure_virtual(web_startup_config())
            state=engine.snapshot()['virtual'];config=state['config']
            self.assertTrue(state['enabled'])
            self.assertEqual(config['masterVolume'],19.5)
            self.assertEqual(config['tonalMode'],'extreme_v15')
            self.assertEqual(config['hddMode'],'articulated')
            self.assertEqual(config['dvdMode'],'reinforcement')
            self.assertTrue(config['sourceContinuity'])
            self.assertEqual(config['sourceContinuityAmount'],1.)
            self.assertTrue(config['trayEnabled'])
            self.assertFalse(config['idleReinforcement']['enabled'])
            self.assertTrue(engine._orchestra.policy['sourceContinuity'])
            self.assertEqual(engine._orchestra.policy['sourceContinuityAmount'],1.)
            self.assertEqual(sum(d['type']=='DVD_SLED' for d in config['devices']),4)
            engine.configure_virtual({**config,'enabled':True,'tonalMode':'raw',
                'sourceContinuity':False,'dvdMode':'independent','masterVolume':1})
            changed=engine.snapshot()['virtual']['config']
            self.assertEqual(changed['tonalMode'],'raw')
            self.assertFalse(changed['sourceContinuity'])
            self.assertEqual(changed['dvdMode'],'independent')
            self.assertEqual(changed['masterVolume'],1)
        finally:engine.shutdown()

    def test_main_applies_defaults_before_serving(self):
        with patch.object(server,'PlaybackEngine') as engine, patch.object(server,'create_app'), patch('uvicorn.run') as run:
            self.assertEqual(server.main(['--no-hardware']),0)
            engine.return_value.configure_virtual.assert_called_once_with(web_startup_config())
            run.assert_called_once()

if __name__=='__main__':unittest.main()
