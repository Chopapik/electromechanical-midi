"""Mechanical contract tests. No audio device or subprocess is required."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_source import NoteSpan
from playback.virtual import VirtualDeviceInstance, VirtualOrchestra, WavePreview

class Source:
    tracks = [object()]
    def __init__(self, spans): self.spans = spans
    def notes(self, track): return self.spans

def device(kind='FDD', **extra):
    return VirtualDeviceInstance.parse({'id': extra.pop('id', 'one'), 'type': kind,
                                         'track': 0, **extra})

def span(start, end, note=69):
    return NoteSpan(start, end, note, 100, 0)

class VirtualMechanicsTest(unittest.TestCase):
    def test_fdd_reversals_do_not_add_knocks_to_preview_pcm(self):
        orchestra = VirtualOrchestra([device()])
        orchestra.simulate(Source([span(0, 2, 69)]))
        events = list(orchestra.events)
        reversals = orchestra.report['one']['reversals']
        self.assertGreater(reversals, 10)
        preview = WavePreview()
        n = int(2.25 * preview.RATE)
        rows = preview._plan(orchestra, n)
        self.assertTrue(rows)
        self.assertTrue(all(row[2].kind != 'reversal' for row in rows))
        actual = preview._render_python(rows, n, 1)
        orchestra.events = [e for e in events if e.kind != 'reversal']
        expected = preview._render_python(preview._plan(orchestra, n), n, 1)
        self.assertEqual(actual, expected)
        orchestra.events = events
        self.assertEqual(orchestra.report['one']['reversals'], reversals)
        self.assertEqual(sum(e.kind == 'reversal' for e in orchestra.events), reversals)

    def test_fdd_sustain_reverses_and_updates_position(self):
        orchestra = VirtualOrchestra([device()])
        orchestra.simulate(Source([span(0, 2, 69)]))
        result = orchestra.report['one']
        self.assertEqual(result['steps'], 880)
        self.assertGreater(result['reversals'], 10)
        self.assertEqual(result['reversals'], sum(e.kind == 'reversal' for e in orchestra.events))
        self.assertTrue(4 <= result['state']['position'] <= 72)
        self.assertEqual(result['travel'], 880)
        self.assertEqual(orchestra.active_at(1), {'one': True})
        self.assertEqual(orchestra.active_at(2), {'one': False})

    def test_instance_boundaries_and_provenance_survive_preset(self):
        orchestra = VirtualOrchestra()
        orchestra.set_config({'devices': [{'id': 'a', 'type': 'FDD', 'track': 0,
            'overrides': {'minPosition': {'value': 0, 'provenance': 'MEASURED', 'source': 'bench'},
                          'maxPosition': {'value': 2, 'provenance': 'MEASURED', 'source': 'bench'}}}]})
        restored = VirtualOrchestra()
        restored.set_config(orchestra.config())
        restored.simulate(Source([span(0, .1)]))
        self.assertGreater(restored.report['a']['reversals'], 10)
        self.assertEqual(restored.config()['devices'][0]['overrides']['maxPosition']['provenance'], 'MEASURED')

    def test_fold_and_drop(self):
        orchestra = VirtualOrchestra([device()])
        orchestra.simulate(Source([span(0, .1, 100)]))
        self.assertEqual(orchestra.report['one']['folded'], 1)
        # Narrow, no octave candidate: explicit out of range.
        from playback.virtual import DeviceProfile, PROFILES, Parameter
        PROFILES['TEST_NARROW'] = DeviceProfile('TEST_NARROW', 'FDD', {
            'minHz': Parameter(400, 'ESTIMATED'), 'maxHz': Parameter(410, 'ESTIMATED')}, overflow='drop')
        try:
            orchestra.devices[0].profile = 'TEST_NARROW'
            orchestra.simulate(Source([span(0, .1, 69)]))
            self.assertEqual(orchestra.report['one']['dropped'], 1)
        finally:
            del PROFILES['TEST_NARROW']

    def test_hdd_busy_and_independent_instances(self):
        orchestra = VirtualOrchestra([device('HDD_VCM', id='a'), device('HDD_VCM', id='b')])
        orchestra.simulate(Source([span(0, .02), span(.05, .07), span(.2, .22)]))
        for ident in ('a', 'b'):
            report = orchestra.report[ident]
            self.assertEqual(report['requestedHits'], 3)
            self.assertEqual(report['acceptedHits'], 2)
            self.assertEqual(report['droppedWhileBusy'], 1)
            self.assertEqual(report['busyTime'], .21)
        self.assertAlmostEqual(next(e.time for e in orchestra.events if e.device == 'a'), .08)
        self.assertTrue(orchestra.active_at(.02)['a'])  # PARK: working before the strike sounds
        self.assertFalse(orchestra.active_at(.5)['a'])
        self.assertTrue(orchestra.active_at(.5, visual_hold=.25)['a'])

    def test_stepper_has_no_boundaries(self):
        orchestra = VirtualOrchestra([device('STEPPER_FREE')])
        orchestra.simulate(Source([span(0, 2)]))
        self.assertEqual(orchestra.report['one']['reversals'], 0)
        self.assertEqual(orchestra.report['one']['steps'], 880)

    def test_configured_busy_policy_delays_hits(self):
        from playback.virtual import DeviceProfile, PROFILES, Parameter
        PROFILES['TEST_QUEUE'] = DeviceProfile('TEST_QUEUE', 'HDD_VCM', {
            'parkMs': Parameter(40, 'ESTIMATED'),
            'settleMs': Parameter(40, 'ESTIMATED'),
            'strikeMs': Parameter(25, 'ESTIMATED'),
        }, busy_policy='queue')
        try:
            orchestra = VirtualOrchestra([device('HDD_VCM', profile='TEST_QUEUE')])
            orchestra.simulate(Source([span(0, .01), span(.05, .06)]))
            self.assertEqual(orchestra.report['one']['delayed'], 1)
            self.assertAlmostEqual(orchestra.events[-1].time, .185)
        finally:
            del PROFILES['TEST_QUEUE']

    def test_solenoid_retrigger_uses_instance_override(self):
        solenoid = device('SOLENOID_RESONATOR', overrides={
            'minRetriggerMs': {'value': 100, 'provenance': 'MEASURED', 'source': 'bench'}})
        orchestra = VirtualOrchestra([solenoid])
        orchestra.simulate(Source([span(0, .01), span(.05, .06)]))
        self.assertEqual(orchestra.report['one']['reasons']['NOTE_DROPPED_RETRIGGER'], 1)

    def test_solo_mute_and_serialization(self):
        config = {'name': 'Test', 'devices': [
            {'id': 'a', 'type': 'FDD', 'track': 0, 'solo': True},
            {'id': 'b', 'type': 'FDD', 'track': 0},
        ]}
        orchestra = VirtualOrchestra()
        orchestra.set_config(config)
        restored = VirtualOrchestra()
        restored.set_config(orchestra.config())
        restored.simulate(Source([span(0, .1)]))
        self.assertTrue(restored.events)
        self.assertEqual({e.device for e in restored.events}, {'a'})
        with self.assertRaises(ValueError):
            restored.set_config({'devices': [config['devices'][0]] * 2})

    def test_accepted_steps_render_to_audio_without_output_device(self):
        import wave
        from playback.virtual import WavePreview
        orchestra = VirtualOrchestra([device()])
        timeline = orchestra.simulate(Source([span(0, .1, 69)]))
        preview = WavePreview()
        try:
            preview.render(orchestra, timeline.duration)
            with wave.open(str(preview.path), 'rb') as output:
                self.assertEqual(output.getnchannels(), 2)
                self.assertGreater(output.getnframes(), 2000)
                self.assertNotEqual(output.readframes(1000), b'\0' * 4000)
        finally:
            preview.close()

if __name__ == '__main__': unittest.main()

class VirtualEngineTest(unittest.TestCase):
    def test_playback_without_arduino_uses_existing_engine(self):
        from unittest.mock import patch
        from playback.engine import PlaybackEngine
        engine = PlaybackEngine()
        path = Path(__file__).resolve().parents[2] / 'midi' / 'test.mid'
        engine.load_file(path)
        track = engine.snapshot()['track']
        engine.configure_virtual({'enabled': True, 'devices': [{'id': 'fdd', 'type': 'FDD', 'track': track}]})
        self.assertFalse(engine.snapshot()['hardware']['connected'])
        with patch.object(engine._preview, 'render'), patch.object(engine._preview, 'play'):
            engine.play()
            self.assertEqual(engine.snapshot()['state'], 'playing')
            with patch.object(engine, '_position_locked', return_value=.2):
                self.assertTrue(engine.snapshot()['virtual']['activity']['fdd'])
            engine.pause()
            self.assertEqual(engine.snapshot()['state'], 'paused')
            self.assertFalse(engine.snapshot()['virtual']['activity']['fdd'])
            engine.seek(0)
            engine.resume()
            engine.stop()
            self.assertEqual(engine.snapshot()['state'], 'stopped')
        engine.shutdown()

    def test_device_and_arrangement_edits_keep_playback_running(self):
        from unittest.mock import patch
        from playback.arrangement import Arrangement
        from playback.engine import PlaybackEngine
        engine = PlaybackEngine()
        engine.load_file(Path(__file__).resolve().parents[2] / 'midi' / 'test.mid')
        track = engine.snapshot()['track']
        config = {'enabled': True, 'devices': [{'id': 'fdd', 'type': 'FDD', 'track': track}]}
        engine.configure_virtual(config)
        old_preview = engine._preview
        try:
            with patch.object(old_preview, 'render'), patch.object(old_preview, 'play'), \
                 patch.object(engine, '_request_preview_locked') as refresh:
                engine.play()
                origin = engine._origin
                config['devices'][0]['volume'] = .4
                engine.configure_virtual(config)
                self.assertEqual(engine.snapshot()['state'], 'playing')
                self.assertEqual(engine._origin, origin)
                self.assertIs(engine._preview, old_preview)
                arrangement = Arrangement.default(engine._source, engine._virtual.devices)
                engine.set_arrangement(arrangement.as_dict())
                self.assertEqual(engine.snapshot()['state'], 'playing')
                self.assertEqual(engine._origin, origin)
                self.assertGreaterEqual(refresh.call_count, 2)
        finally:
            engine.stop()
            engine.shutdown()

    def test_preview_swap_waits_for_render_without_stopping_playhead(self):
        import threading
        import time
        from unittest.mock import patch
        from playback.engine import PlaybackEngine
        from playback.virtual import WavePreview
        engine = PlaybackEngine()
        engine.load_file(Path(__file__).resolve().parents[2] / 'midi' / 'test.mid')
        track = engine.snapshot()['track']
        config = {'enabled': True, 'devices': [{'id': 'fdd', 'type': 'FDD', 'track': track}]}
        engine.configure_virtual(config)
        old_preview = engine._preview
        started, release = threading.Event(), threading.Event()

        def slow_render(_preview, _orchestra, _duration):
            started.set()
            release.wait(2)

        try:
            with patch.object(old_preview, 'render'), patch.object(old_preview, 'play'), \
                 patch.object(WavePreview, 'render', slow_render), patch.object(WavePreview, 'play'):
                engine.play()
                origin = engine._origin
                config['devices'][0]['volume'] = .4
                engine.configure_virtual(config)
                self.assertTrue(started.wait(1))
                self.assertIs(engine._preview, old_preview)
                self.assertEqual(engine.snapshot()['state'], 'playing')
                release.set()
                deadline = time.monotonic() + 1
                while engine._preview is old_preview and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertIsNot(engine._preview, old_preview)
                self.assertEqual(engine.snapshot()['state'], 'playing')
                self.assertEqual(engine._origin, origin)
        finally:
            release.set()
            engine.stop()
            engine.shutdown()
