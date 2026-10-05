"""Virtual output-clock synchronization; no physical hardware required."""
import io
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playback.virtual import WavePreview
from playback.engine import PlaybackEngine, PlaybackState
from playback.timeline import Command, Timeline

class AudioClockTest(unittest.TestCase):
    def test_start_waits_for_actual_audio_clock(self):
        player = WavePreview(clocked=True)
        player._audio_start = 3
        player._audio_end = 20
        player.process = Mock()
        player.process.poll.return_value = None
        with patch('playback.virtual.time.monotonic', return_value=999):
            self.assertEqual(player.clock_position(), 3)
            self.assertFalse(player.clock_running)

    def test_parses_output_clock_and_bounds_extrapolation(self):
        player = WavePreview(clocked=True)
        player._audio_start = 2
        player._audio_end = 20
        process = Mock(stderr=io.BytesIO(b'Input WAV metadata\n nan M-A: nan\r   2.31 M-A: 0.000 fd=0\r'))
        process.poll.return_value = None
        player.process = process
        with patch('playback.virtual.time.monotonic', return_value=100):
            player._read_audio_clock(process)
            self.assertEqual(player.clock_position(), 2.31)
            self.assertTrue(player.clock_running)
        with patch('playback.virtual.time.monotonic', return_value=105):
            self.assertAlmostEqual(player.clock_position(), 2.43)
        process.poll.return_value = 0
        self.assertEqual(player.clock_position(), 20)

    def test_old_process_cannot_move_clock_after_seek(self):
        player = WavePreview(clocked=True)
        player._audio_start = 10
        player._audio_end = 20
        player.process = Mock()
        old = Mock(stderr=io.BytesIO(b' 2.31 M-A: 0.000\r'))
        player._read_audio_clock(old)
        self.assertIsNone(player._audio_anchor)

    def test_virtual_transport_uses_audio_clock_without_altering_plan(self):
        engine = PlaybackEngine()
        try:
            engine._timeline = Timeline.from_commands([Command(20, 'virtual', lane='virtual')])
            engine._virtual_mode = True
            engine._state = PlaybackState.PLAYING
            engine._origin = time.monotonic() - 9
            with patch.object(engine._preview, 'clock_position', return_value=2.31):
                self.assertAlmostEqual(engine.snapshot()['position'], 2.31)
                self.assertAlmostEqual(engine.snapshot()['virtual']['audioPosition'], 2.31)
                engine.pause()
                self.assertAlmostEqual(engine.snapshot()['position'], 2.31)
            self.assertIsNone(engine._plan)
        finally:
            engine.shutdown()

    def test_renderer_exports_actual_release_and_not_mechanical_gate(self):
        from playback.orchestra import web_startup_config
        engine = PlaybackEngine()
        try:
            engine.configure_virtual(web_startup_config())
            engine.load_file(Path(__file__).resolve().parents[2] / 'midi/test.mid')
            plan = engine._plan
            engine._preview.render(engine._virtual, engine._timeline.duration)
            view = engine.telemetry_view()
            tones = [e for e in view['audioEvents'] if e['kind'] == 'tone']
            self.assertTrue(tones)
            actual = engine._preview.tonal_stats['events']
            for event in tones:
                row = next(r for r in actual if r['deviceId'] == event['deviceId'] and r['start'] == event['start'])
                self.assertAlmostEqual(event['duration'], row['audioDuration'])
            self.assertIs(engine._plan, plan)
        finally:
            engine.shutdown()
