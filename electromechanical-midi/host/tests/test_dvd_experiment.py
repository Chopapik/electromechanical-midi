"""Four quiet virtual DVD voices extend accompaniment without taking the lead."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import MidiSource  # noqa: E402
from playback import allocator  # noqa: E402
from playback.analysis import MidiAnalysis  # noqa: E402
from playback.engine import PlaybackEngine  # noqa: E402
from playback.orchestra import default_orchestra, parse_orchestra  # noqa: E402
from playback.virtual import VirtualOrchestra, WavePreview  # noqa: E402
from test_allocator import write_drums, write_tracks  # noqa: E402


class DvdExperimentTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / 'song.mid'

    def tearDown(self):
        self.temporary.cleanup()

    def harmony_source(self, notes):
        return MidiSource(write_tracks(self.path, [('Harmony', 0, notes)]))

    @staticmethod
    def harmony_analysis(source):
        roles = {f'{track.index}:{note.order}': 'harmony'
                 for track in source.tracks for note in source.notes(track.index)}
        return MidiAnalysis([], None, 0.0, None, 0.0, roles)

    def test_four_distinct_virtual_dvd_survive_round_trip(self):
        config = default_orchestra()
        dvd = [device for device in config.devices if device['type'] == 'DVD_SLED']
        self.assertEqual(len(config.devices), 11)
        self.assertEqual(len(dvd), 4)
        self.assertEqual(len({device['id'] for device in dvd}), 4)
        self.assertTrue(all(device['mode'] == 'virtual' and device['volume'] == .2
                            and device['profile'] == 'DVD_REFERENCE' for device in dvd))
        self.assertEqual(parse_orchestra(config.as_dict()).as_dict(), config.as_dict())

    def test_fdd_preferred_and_dvd_used_when_three_fdd_busy(self):
        source = self.harmony_source([(0, 1, 60), (0, 1, 64), (0, 1, 67),
                                      (.1, .5, 72)])
        analysis = self.harmony_analysis(source)
        config = default_orchestra()
        plan = allocator.allocate(source, config, midi_analysis=analysis)
        by_id = {event.id: event for event in plan.events}
        self.assertEqual([by_id[f'1:{i}'].device_type for i in range(3)], ['FDD'] * 3)
        self.assertEqual(by_id['1:3'].device_type, 'DVD_SLED')
        self.assertEqual(by_id['1:3'].device_id, 'dvd_sled-1')
        self.assertEqual(plan.report()['tonal']['dropped'], 0)
        self.assertEqual(plan.as_dict(), allocator.allocate(source, config, midi_analysis=analysis).as_dict())

    def test_all_seven_accompaniment_slots_are_dynamic(self):
        source = self.harmony_source([(0, .5, note) for note in (60, 62, 64, 65, 67, 69, 71)])
        plan = allocator.allocate(source, default_orchestra(),
                                  midi_analysis=self.harmony_analysis(source))
        self.assertEqual(plan.report()['tonal']['dropped'], 0)
        self.assertEqual({event.device_id for event in plan.events
                          if event.device_type == 'DVD_SLED'},
                         {f'dvd_sled-{number}' for number in range(1, 5)})

    def test_dvd_is_accompaniment_only_and_hdd_percussion_only(self):
        source = self.harmony_source([(0, .5, 60), (0, .5, 64),
                                      (0, .5, 67), (0, .5, 72)])
        analysis = self.harmony_analysis(source)
        analysis.roles['1:0'] = 'lead'
        plan = allocator.allocate(source, default_orchestra(), midi_analysis=analysis)
        self.assertEqual(next(event.device_type for event in plan.events if event.role == 'lead'), 'VHS')
        self.assertTrue(all(event.role != 'lead' for event in plan.events
                            if event.device_type == 'DVD_SLED'))
        self.assertTrue(all(event.device_type != 'HDD_VCM' for event in plan.events
                            if event.role != 'percussion'))

        drums = MidiSource(write_drums(self.path, [(0, .05, 36)]))
        drum_plan = allocator.allocate(drums, default_orchestra())
        self.assertTrue(all(event.device_type == 'HDD_VCM' for event in drum_plan.events
                            if event.played))

    def test_dvd_counts_toward_accompaniment_continuity(self):
        source = self.harmony_source([(0, .5, 60)])
        config = default_orchestra()
        config.devices = [device for device in config.devices if device['type'] == 'DVD_SLED']
        plan = allocator.allocate(source, config, midi_analysis=self.harmony_analysis(source))
        self.assertEqual(plan.events[0].device_type, 'DVD_SLED')
        self.assertGreater(plan.report()['continuity']['accompanimentContinuity'], .9)

    def test_virtual_preview_renders_four_dvd_without_audio_hardware(self):
        source = self.harmony_source([(0, .2, note) for note in (60, 62, 64, 65, 67, 69, 71)])
        plan = allocator.allocate(source, default_orchestra(),
                                  midi_analysis=self.harmony_analysis(source))
        orchestra = VirtualOrchestra().load_plan(plan)
        preview = WavePreview()
        try:
            orchestra.render_plan(plan)
            preview.render(orchestra, plan.duration)
            self.assertIsNotNone(preview.path)
            self.assertGreater(preview.path.stat().st_size, 44)
        finally:
            preview.close()

    def test_ui_configuration_add_and_remove_rebuilds_allocator(self):
        source = self.harmony_source([(0, .5, 60), (0, .5, 64),
                                      (0, .5, 67), (0, .5, 72)])
        engine = PlaybackEngine(auto_arrange=True)
        try:
            engine.load_file(source.path)
            seven = default_orchestra(dvd_count=0).as_dict()
            engine.configure_virtual({**seven, 'enabled': True})
            self.assertEqual(len(engine.arrangement_view()['orchestra']['devices']), 7)
            engine.configure_virtual({'name': 'Empty', 'devices': [], 'enabled': True})
            self.assertEqual(engine.arrangement_view()['orchestra']['devices'], [])
            eleven = default_orchestra().as_dict()
            engine.configure_virtual({**eleven, 'enabled': True})
            view = engine.arrangement_view()
            self.assertEqual(len(view['orchestra']['devices']), 11)
            self.assertEqual(len([item for item in view['report']['devices']
                                  if item['type'] == 'DVD_SLED']), 4)
            engine.configure_virtual({**seven, 'enabled': True})
            self.assertEqual(len(engine.arrangement_view()['orchestra']['devices']), 7)
        finally:
            engine.shutdown()
