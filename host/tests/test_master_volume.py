import math
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playback.engine import PlaybackEngine
from playback.virtual import VirtualOrchestra, WavePreview


class MasterVolumeTest(unittest.TestCase):
    def test_config_roundtrip_and_validation(self):
        orchestra = VirtualOrchestra()
        self.assertEqual(orchestra.config()['masterVolume'], 1)
        orchestra.set_config({'devices': [], 'masterVolume': 8})
        self.assertEqual(orchestra.config()['masterVolume'], 8)
        for value in (-1, 21, math.nan, math.inf):
            with self.assertRaises(ValueError):
                orchestra.set_config({'devices': [], 'masterVolume': value})

    def test_master_gain_reaches_audio_player(self):
        with tempfile.TemporaryDirectory() as folder:
            preview = WavePreview()
            preview.path = Path(folder) / 'sound.wav'
            with wave.open(str(preview.path), 'wb') as wav:
                wav.setparams((2, 2, 22050, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\x00' * 400)
            preview.master_volume = 8
            with patch('playback.virtual.subprocess.Popen') as player:
                preview.play(0)
                self.assertEqual(player.call_args.args[0][:3], ['afplay', '-v', '8'])
                preview.close()

    def test_master_change_keeps_plan_clock_and_cached_audio(self):
        engine = PlaybackEngine()
        try:
            engine.load_file(Path(__file__).resolve().parents[2] / 'midi/test.mid')
            engine.configure_virtual({'enabled': True, 'devices': [{'id': 'fdd', 'type': 'FDD', 'track': engine.snapshot()['track']}]})
            preview = engine._preview
            with patch.object(preview, 'render'), patch.object(preview, 'play') as play:
                engine.play()
                plan, origin, revision = engine._plan, engine._origin, engine._arrangement_revision
                payload = {**engine._virtual.config(), 'enabled': True, 'masterVolume': 12}
                with patch.object(engine, '_rebuild_locked') as rebuild:
                    engine.configure_virtual(payload)
                    rebuild.assert_not_called()
                self.assertIs(engine._plan, plan)
                self.assertIs(engine._preview, preview)
                self.assertEqual(engine._origin, origin)
                self.assertEqual(engine._arrangement_revision, revision)
                self.assertEqual(engine.snapshot()['state'], 'playing')
                self.assertEqual(preview.master_volume, 12)
                self.assertEqual(engine.snapshot()['virtual']['config']['masterVolume'], 12)
                self.assertGreaterEqual(play.call_args.args[0], 0)
        finally:
            engine.shutdown()
