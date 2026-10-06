"""Tray copies never consume the ordinary allocator's voices."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_source import MidiSource
from playback.allocator import allocate, ManualPin
from playback.orchestra import default_orchestra
from playback.virtual import VirtualOrchestra, VirtualDeviceInstance, effective_profile, WavePreview
from playback.tray import motion_duration, tray_sound
from playback.engine import PlaybackEngine
from test_allocator import write_drums, write_tracks


class TrayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.mid'

    def tearDown(self):
        self.tmp.cleanup()

    def drums(self, notes, **kwargs):
        return allocate(MidiSource(write_drums(self.path, notes)), default_orchestra(**kwargs))

    def test_default_and_variable_inventory(self):
        config = default_orchestra()
        self.assertEqual(len(config.devices), 15)
        self.assertEqual([d['id'] for d in config.devices if d['type'] == 'DVD_SLED'],
                         [f'DVD_STEPPER_{i}' for i in range(1, 5)])
        self.assertEqual([d['id'] for d in config.devices if d['type'] == 'DVD_TRAY'],
                         ['DVD_TRAY_1', 'DVD_TRAY_2'])
        self.assertEqual(len(default_orchestra(dvd_count=5, tray_count=3).devices), 17)

    def test_hdd_decisions_identical_with_and_without_trays(self):
        notes = [(i * .1, i * .1 + .05, [49, 55, 57, 46, 59][i % 5]) for i in range(50)]
        on = self.drums(notes)
        off = self.drums(notes, tray_enabled=False)
        absent = self.drums(notes, tray_count=0)
        self.assertEqual([e.as_dict() for e in on.events], [e.as_dict() for e in off.events])
        self.assertEqual([e.as_dict() for e in on.events], [e.as_dict() for e in absent.events])
        self.assertTrue(on.tray_events)
        self.assertFalse(off.tray_events)
        self.assertTrue(all(e.device_type == 'HDD_VCM' for e in on.events if e.played))
        for device in ('DVD_TRAY_1', 'DVD_TRAY_2'):
            events = [e for e in on.tray_events if e.device_id == device]
            self.assertTrue(events)
            for a, b in zip(events, events[1:]):
                self.assertGreaterEqual(b.start + 1e-9, a.start + a.duration + a.cooldown)

    def test_second_tray_and_priority(self):
        plan = self.drums([(0, .05, 46), (0, .05, 49), (.12, .17, 55), (.15, .20, 57)])
        self.assertEqual([e.note for e in plan.tray_events], [49, 55])
        self.assertEqual({e.device_id for e in plan.tray_events}, {'DVD_TRAY_1', 'DVD_TRAY_2'})
        self.assertGreater(plan.tray_report['skippedBusyCooldown'], 0)

    def test_dense_hats_are_sampled_and_crash_reserved(self):
        notes = [(i * .1, i * .1 + .04, 46) for i in range(40)] + [(1.05, 1.1, 57)]
        plan = self.drums(notes)
        hats = [e for e in plan.tray_events if e.note == 46]
        self.assertLessEqual(len(hats), 4)
        self.assertTrue(any(e.note == 57 for e in plan.tray_events))
        self.assertGreater(plan.tray_report['skippedSampled'], 20)

    def test_renderer_sound_duration_and_virtual_only(self):
        plan = self.drums([(0, .05, 49), (.12, .17, 55)])
        renderer = VirtualOrchestra().load_plan(plan)
        renderer.render_plan(plan)
        self.assertEqual(len([e for e in renderer.events if e.kind == 'tray']), 2)
        self.assertEqual(renderer.tray_state_at(.01)['DVD_TRAY_1']['phase'], 'moving')
        self.assertEqual(renderer.tray_state_at(.3)['DVD_TRAY_1']['phase'], 'recovery')
        device = VirtualDeviceInstance.parse(next(d for d in plan.devices if d['type'] == 'DVD_TRAY'))
        profile = effective_profile(device)
        self.assertEqual(motion_duration(profile, 127), ('STRONG', .3))
        self.assertLess(motion_duration(profile, 40)[1], motion_duration(profile, 80)[1])
        a = [tray_sound(i / 8000, .3, 100, profile, 'DVD_TRAY_1', 1) for i in range(2400)]
        b = [tray_sound(i / 8000, .3, 100, profile, 'DVD_TRAY_2', 1) for i in range(2400)]
        self.assertNotEqual(a, b)
        self.assertGreater(max(abs(v) for v in a), .1)
        hardware_tray = VirtualDeviceInstance.parse({**next(d for d in plan.devices if d['type'] == 'DVD_TRAY'), 'mode': 'real'})
        self.assertTrue(hardware_tray.drives_hardware)
        preview = WavePreview()
        try:
            preview.render(renderer, plan.duration)
            self.assertGreater(preview.path.stat().st_size, 44)
        finally:
            preview.close()

    def test_four_normal_dvd_and_fourth_reinforcement(self):
        source = MidiSource(write_tracks(self.path, [('Harmony', 0, [(0, .5, n) for n in (60, 64, 67, 72)])]))
        config = default_orchestra(dvd_mode='reinforcement')
        pins = {f'1:{i}': ManualPin(device_id=f'DVD_STEPPER_{i+1}', rule_id=str(i)) for i in range(4)}
        plan = allocate(source, config, pins=pins)
        self.assertEqual({e.device_id for e in plan.events if e.played}, {f'DVD_STEPPER_{i}' for i in range(1, 5)})
        self.assertFalse(plan.reinforcements)
        source = MidiSource(write_tracks(self.path, [('Harmony', 0, [(0, .5, n) for n in (60, 64, 67)])]))
        plan = allocate(source, config, pins={k: v for k, v in pins.items() if k != '1:3'})
        self.assertTrue(any(e.device_id == 'DVD_STEPPER_4' for e in plan.reinforcements))

    def test_five_dvd_need_only_configuration(self):
        source = MidiSource(write_tracks(self.path, [('Harmony', 0, [(0, .5, n) for n in (60, 64, 67, 72, 76)])]))
        config = default_orchestra(dvd_count=5, dvd_mode='reinforcement')
        pins = {f'1:{i}': ManualPin(device_id=f'DVD_STEPPER_{i+1}', rule_id=str(i)) for i in range(5)}
        plan = allocate(source, config, pins=pins)
        self.assertEqual(len({e.device_id for e in plan.events if e.played}), 5)
        self.assertEqual(plan.report()['tonal']['dropped'], 0)

    def test_engine_keeps_tray_notes_separate_and_persists_toggle(self):
        write_drums(self.path, [(0, .05, 49), (.12, .17, 55)])
        engine = PlaybackEngine(auto_arrange=True)
        try:
            engine.load_file(self.path)
            view = engine.arrangement_view()
            self.assertEqual(len(view['notes']), 2)
            self.assertEqual(len(view['trayNotes']), 2)
            self.assertTrue(all(n['reinforcement'] and n['routes'][0]['deviceId'].startswith('DVD_TRAY_')
                                for n in view['trayNotes']))
            engine.configure_virtual({**default_orchestra(tray_enabled=False).as_dict(), 'enabled': True})
            off = engine.arrangement_view()
            self.assertFalse(off['trayNotes'])
            self.assertEqual(view['notes'], off['notes'])
            self.assertFalse(off['arrangement']['trayEnabled'])
        finally:
            engine.shutdown()


if __name__ == '__main__':
    unittest.main()
