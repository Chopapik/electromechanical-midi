"""Jeden dokument aranzacji dla dwoch wyjsc: symulacji i fizycznego sprzetu.

Sprawdzaja, ze tryb instancji ('virtual'/'real'/'hybrid') decyduje o tym,
co idzie na Serial, a co tylko do podgladu audio - i ze komendy sprzetowe
powstaja z tych samych zaakceptowanych zdarzen co symulacja.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import MidiSource  # noqa: E402
from playback.arrangement import Arrangement, midi_identity  # noqa: E402
from playback.hardware import bind_devices, build_commands  # noqa: E402
from playback.timeline import LANE_DRUM, LANE_FDD, LANE_HDD, MIN_NOTE_S  # noqa: E402
from playback.virtual import MODES, VirtualDeviceInstance, VirtualOrchestra  # noqa: E402
from test_arrangement import write_song  # noqa: E402


def device(ident, kind, mode='virtual', **fields):
    return {'id': ident, 'type': kind, 'mode': mode, **fields}


def rule(ident, track, target, **source_fields):
    return {'id': ident, 'source': {'track': track, **source_fields},
            'destination': {'deviceId': target}, 'transform': {}}


class ModeParsingTest(unittest.TestCase):
    def test_all_modes_and_aliases_are_accepted(self):
        for mode in MODES:
            self.assertEqual(VirtualDeviceInstance.parse(device('d', 'FDD', mode)).mode, mode)
        self.assertEqual(VirtualDeviceInstance.parse(device('d', 'FDD', 'hardware')).mode, 'real')
        self.assertEqual(VirtualDeviceInstance.parse(device('d', 'FDD', 'HYBRID')).mode, 'hybrid')
        # Brak trybu = zachowanie sprzed aranzacji: czysta wirtualizacja.
        self.assertEqual(VirtualDeviceInstance.parse(device('d', 'FDD')).mode, 'virtual')

    def test_unknown_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'invalid mode'):
            VirtualDeviceInstance.parse(device('d', 'FDD', 'analog'))

    def test_mode_decides_about_hardware_and_preview(self):
        cases = {'virtual': (False, True), 'real': (True, False), 'hybrid': (True, True)}
        for mode, (hardware, preview) in cases.items():
            parsed = VirtualDeviceInstance.parse(device('d', 'FDD', mode))
            self.assertEqual(parsed.drives_hardware, hardware, mode)
            self.assertEqual(parsed.in_preview, preview, mode)

    def test_mode_survives_json_round_trip(self):
        import dataclasses
        parsed = VirtualDeviceInstance.parse(device('d', 'FDD', 'hybrid'))
        copy = VirtualDeviceInstance.parse(dataclasses.asdict(parsed))
        self.assertEqual(copy.mode, 'hybrid')


class BindingTest(unittest.TestCase):
    def test_virtual_devices_never_touch_hardware(self):
        devices = [VirtualDeviceInstance.parse(device('a', 'FDD')), VirtualDeviceInstance.parse(device('b', 'HDD_VCM'))]
        bound, unmapped = bind_devices(devices)
        self.assertEqual(bound, {})
        self.assertEqual(unmapped, [])

    def test_each_lane_gets_the_first_hardware_instance(self):
        devices = [VirtualDeviceInstance.parse(device('fdd-1', 'FDD', 'virtual')),
                   VirtualDeviceInstance.parse(device('fdd-2', 'FDD', 'real')),
                   VirtualDeviceInstance.parse(device('vhs', 'VHS', 'hybrid')),
                   VirtualDeviceInstance.parse(device('hdd', 'HDD_VCM', 'real'))]
        bound, unmapped = bind_devices(devices)
        self.assertEqual({lane: d.id for lane, d in bound.items()},
                         {LANE_FDD: 'fdd-2', LANE_DRUM: 'vhs', LANE_HDD: 'hdd'})
        self.assertEqual(unmapped, [])

    def test_second_hardware_instance_on_a_taken_lane_is_reported(self):
        devices = [VirtualDeviceInstance.parse(device('fdd-1', 'FDD', 'real')),
                   VirtualDeviceInstance.parse(device('fdd-2', 'FDD', 'hybrid')),
                   VirtualDeviceInstance.parse(device('vd', 'DVD_SLED', 'real'))]
        bound, unmapped = bind_devices(devices)
        self.assertEqual(bound[LANE_FDD].id, 'fdd-1')
        self.assertEqual([item['deviceId'] for item in unmapped], ['fdd-2', 'vd'])
        self.assertTrue(all(item['reason'] == 'LANE_TAKEN' for item in unmapped))
        self.assertEqual(unmapped[0]['boundTo'], 'fdd-1')


class HardwareCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / 'song.mid'
        write_song(path)
        self.source = MidiSource(path)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, devices, rules):
        document = {'schemaVersion': 1, 'midi': midi_identity(self.source), 'name': 'Test',
                    'devices': devices, 'rules': rules}
        arrangement = Arrangement.parse(document, self.source)
        routes, _ = arrangement.route(self.source)
        orchestra = VirtualOrchestra(arrangement.devices, 'Test')
        orchestra.simulate(self.source, routes)
        bound, unmapped = bind_devices(arrangement.devices)
        return orchestra, build_commands(orchestra, bound), unmapped

    def test_virtual_only_arrangement_produces_no_serial_commands(self):
        devices = [device('fdd', 'FDD', 'virtual'), device('hdd', 'HDD_VCM', 'virtual')]
        _, commands, _ = self.build(devices, [rule('a', 0, 'fdd'), rule('b', 2, 'hdd')])
        self.assertEqual(commands, [])

    def test_real_devices_map_onto_their_physical_lanes(self):
        devices = [device('fdd', 'FDD', 'real'), device('vhs', 'VHS', 'real'),
                   device('hdd', 'HDD_VCM', 'real')]
        _, commands, _ = self.build(devices, [rule('a', 0, 'fdd'), rule('b', 1, 'vhs'), rule('c', 2, 'hdd')])
        self.assertEqual({command.lane for command in commands}, {LANE_FDD, LANE_DRUM, LANE_HDD})
        self.assertTrue(any(command.kind == 'hit' for command in commands))
        self.assertTrue(any(command.kind == 'play' for command in commands))
        self.assertTrue(any(command.kind == 'drum_on' for command in commands))

    def test_every_play_is_closed_by_a_stop(self):
        devices = [device('fdd', 'FDD', 'real')]
        _, commands, _ = self.build(devices, [rule('a', 0, 'fdd')])
        plays = [c for c in commands if c.kind == 'play']
        stops = [c for c in commands if c.kind == 'stop']
        self.assertTrue(plays)
        self.assertEqual(len(plays), len(stops))
        self.assertLessEqual(plays[0].time, stops[0].time)

    def test_hardware_commands_come_from_accepted_events_only(self):
        """Sprzet nie moze zagrac niczego, czego symulacja nie zaakceptowala."""
        devices = [device('fdd', 'FDD', 'real')]
        orchestra, commands, _ = self.build(devices, [rule('a', 0, 'fdd')])
        accepted = [event for event in orchestra.events
                    if event.device == 'fdd' and event.kind == 'tone']
        plays = [command for command in commands if command.kind == 'play']
        playable = [event for event in accepted if event.duration >= MIN_NOTE_S]

        self.assertTrue(playable)
        self.assertEqual([command.time for command in plays], [event.time for event in playable])
        self.assertEqual([command.hz for command in plays], [event.hz for event in playable])
        # Zdarzenia odrzucone mechanicznie nie istnieja w ogole jako eventy.
        self.assertEqual(len(accepted), orchestra.report['fdd']['accepted'])

    def test_muted_hardware_device_stays_silent(self):
        devices = [device('fdd', 'FDD', 'real', mute=True)]
        _, commands, _ = self.build(devices, [rule('a', 0, 'fdd')])
        self.assertEqual(commands, [])

    def test_hybrid_device_drives_hardware_and_preview(self):
        orchestra, commands, _ = self.build([device('fdd', 'FDD', 'hybrid')], [rule('a', 0, 'fdd')])
        self.assertTrue(orchestra.events)
        self.assertTrue(commands)
        self.assertTrue(orchestra.devices[0].in_preview)


if __name__ == '__main__':
    unittest.main()
