"""Offline routing experiment: no transport is opened or played."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import MidiSource
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


    def test_one_fdd_can_be_disabled_without_cross_routing(self):
        plan = allocate_strict(self.source, self.config(), [3, 1, None, 8])
        self.assertEqual(plan.strict_report['fdd-3']['played'], 0)
        self.assertFalse(any(e.device_id == 'fdd-3' for e in plan.events))
        self.assertEqual({e.track for e in plan.events if e.device_id == 'fdd-1'}, {3})




if __name__ == '__main__':
    unittest.main()
