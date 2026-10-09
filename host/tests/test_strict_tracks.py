"""Offline routing experiment: no transport is opened or played."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import MidiSource
from playback.engine import PlaybackEngine
from playback.hardware import bind_devices, build_plan_commands
from playback.hardware_profiles import HardwareContext
from playback.orchestra import default_orchestra
from playback.strict_tracks import allocate_strict
from playback.timeline import Command

SONG = Path(__file__).resolve().parents[2] / 'midi/Every breath you take.mid'
ROUTES = [3, 1, 4, 8]


class StrictTracksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MidiSource(SONG)

    def config(self, mode='virtual'):
        config = default_orchestra()
        config.devices = [d for d in config.devices if d['type'] == 'FDD']
        for d in config.devices:
            d['mode'] = mode
        return config

    def test_police_mapping_is_exclusive_and_monophonic(self):
        plan = allocate_strict(self.source, self.config(), ROUTES)
        for index, device in enumerate(plan.devices):
            notes = sorted((e for e in plan.events if e.device_id == device['id']),
                           key=lambda e: e.actual_start)
            self.assertTrue(notes)
            self.assertEqual({e.track for e in notes}, {ROUTES[index]})
            self.assertTrue(all(e.actual_start == e.start for e in notes))
            self.assertTrue(all((e.played_note - e.note) % 12 == 0 for e in notes))
            self.assertTrue(all(a.end <= b.actual_start + 1e-8 for a, b in zip(notes, notes[1:])))
        self.assertFalse(plan.reinforcements)
        self.assertFalse(plan.tray_events)
        self.assertTrue(all(e.outcome not in ('ARPEGGIATED', 'REASSIGNED') for e in plan.events))
        self.assertGreater(plan.strict_report['fdd-3']['chordRejected'], 0)

    def test_physical_plan_uses_only_four_fdd_lanes(self):
        config = self.config('real')
        plan = allocate_strict(self.source, config, ROUTES, HardwareContext(True))
        bound, _ = bind_devices(config.instances(), 2)
        commands = build_plan_commands(plan, bound)
        self.assertEqual(set(plan.hardware['physicalLanes'].values()),
                         {'fdd:1', 'fdd:2', 'fdd:3', 'fdd:4'})
        self.assertTrue(commands)
        self.assertTrue(all(command.lane.startswith('fdd:') for command in commands))
        self.assertTrue(all(command.track == ROUTES[int(command.lane[-1]) - 1]
                            for command in commands if command.kind == 'play'))
        for index, device in enumerate(plan.devices):
            self.assertEqual({e.track for e in plan.events if e.device_id == device['id']},
                             {ROUTES[index]})

    def test_engine_switches_auto_four_fdd_strict_and_restores(self):
        engine = PlaybackEngine(auto_arrange=True, preview_mode=False)
        self.addCleanup(engine.shutdown)
        engine.load_file(SONG)
        original_source = engine._source
        original_orchestra = engine._orchestra.as_dict()
        engine.set_track_routing('AUTO', True, ROUTES)
        baseline = engine.snapshot()['trackRouting']
        self.assertEqual(baseline['mode'], 'AUTO')
        self.assertEqual(baseline['output']['plannedPlayed'], baseline['output']['enabledPlayed'])
        self.assertEqual({d['type'] for d in engine._plan.devices}, {'FDD'})
        self.assertFalse(engine._plan.reinforcements)
        self.assertFalse(engine._plan.tray_events)
        self.assertIs(engine._source, original_source)
        engine.set_track_routing('STRICT_TRACKS', True, ROUTES)
        strict = engine.snapshot()['trackRouting']
        self.assertEqual(strict['output']['enabledPlayed'], sum(r['played'] for r in strict['report'].values()))
        self.assertEqual(strict['output']['disabledReservations'], 0)
        self.assertEqual(strict['report']['fdd-1']['track'], 3)
        engine.set_track_routing('AUTO', False, ROUTES)
        self.assertFalse(engine.snapshot()['trackRouting']['fourFddOnly'])
        self.assertEqual(engine._orchestra.as_dict(), original_orchestra)

    def test_one_fdd_can_be_disabled_without_cross_routing(self):
        plan = allocate_strict(self.source, self.config(), [3, 1, None, 8])
        self.assertEqual(plan.strict_report['fdd-3']['played'], 0)
        self.assertFalse(any(e.device_id == 'fdd-3' for e in plan.events))
        self.assertEqual({e.track for e in plan.events if e.device_id == 'fdd-1'}, {3})

    def test_disabled_output_is_not_reported_as_played(self):
        engine = PlaybackEngine(auto_arrange=True, preview_mode=False)
        self.addCleanup(engine.shutdown)
        engine.load_file(SONG)
        config = default_orchestra()
        config.devices[0]['enabled'] = False
        engine.set_orchestra(config.as_dict())
        engine.set_track_routing('STRICT_TRACKS', True, ROUTES)
        report = engine.snapshot()['trackRouting']
        self.assertEqual(report['report']['fdd-1']['played'], 0)
        self.assertEqual(report['report']['fdd-1']['dropped'], 219)
        self.assertEqual(report['output']['byDevice'].get('fdd-1'), None)
        self.assertEqual(report['output']['plannedPlayed'], report['output']['enabledPlayed'])

    def test_esp32_packet_carries_track_provenance(self):
        engine = PlaybackEngine(auto_arrange=True, preview_mode=False)
        self.addCleanup(engine.shutdown)
        engine.load_file(SONG)
        engine.set_track_routing('STRICT_TRACKS', True, ROUTES)
        self.assertEqual(engine._v2_lines_locked(Command(1, 'play', hz=220, lane='fdd:1', track=3)),
                         ['FDD 1 PLAY 220.00 TRACK 3'])
        self.assertFalse(engine._v2_lines_locked(Command(1, 'play', hz=220, lane='fdd:1', track=1)))


if __name__ == '__main__':
    unittest.main()
