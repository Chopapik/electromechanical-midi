"""Enabled inventory and startup-owned output mode, without physical hardware."""
import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_source import MidiSource
from playback.allocator import allocate, ManualPin
from playback.hardware import bind_devices, build_commands
from playback.orchestra import default_orchestra, parse_orchestra, web_startup_config
from playback.virtual import VirtualDeviceInstance, VirtualOrchestra
from test_allocator import write_tracks


class EnabledDevicesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = write_tracks(Path(self.tmp.name) / 'test.mid', [
            ('Guitar', 0, [(0, .5, 60), (.6, 1.1, 64)]),
            ('Drums', 9, [(0, .1, 36), (.6, .7, 49)])])
        self.source = MidiSource(self.path)

    def config(self, mode='virtual'):
        config = default_orchestra(dvd_mode='reinforcement')
        for device in config.devices:
            device['enabled'] = device['id'] in ('fdd-1', 'hdd_vcm-1')
            device['mode'] = mode if device['type'] != 'DVD_TRAY' else 'virtual'
        config.idle_reinforcement['enabled'] = True
        config.idle_reinforcement['minScore'] = 0
        return config

    def test_legacy_defaults_and_disabled_round_trip(self):
        device = VirtualDeviceInstance.parse({'id': 'fdd', 'type': 'FDD'})
        self.assertTrue(device.enabled)
        payload = {'devices': [{**dataclasses.asdict(device), 'enabled': False}]}
        restored = parse_orchestra(parse_orchestra(payload).as_dict())
        self.assertFalse(restored.instances()[0].enabled)
        self.assertEqual(restored.allocation_devices()[0], [])

    def test_only_enabled_inventory_gets_allocation_reinforcement_and_acoustics(self):
        config = self.config()
        plan = allocate(self.source, config)
        expected = {'fdd-1', 'hdd_vcm-1'}
        self.assertEqual({d['id'] for d in plan.devices}, expected)
        self.assertTrue(any(e.played for e in plan.events))
        self.assertTrue(all(e.device_id in expected for e in plan.events if e.played))
        self.assertTrue(all(e.device_id in expected for e in plan.reinforcements + plan.tray_events))
        orchestra = VirtualOrchestra()
        orchestra.render_plan(plan)
        self.assertTrue(all(e.device in expected for e in orchestra.events))
        disabled = VirtualOrchestra([VirtualDeviceInstance.parse({
            'id': 'off', 'type': 'FDD', 'track': 1, 'enabled': False, 'solo': True})])
        disabled.simulate(self.source)
        self.assertEqual(disabled.events, [])

    def test_disabled_manual_destination_is_not_allocated_and_reenable_restores_capacity(self):
        config = self.config()
        off = next(d for d in config.devices if d['id'] == 'DVD_STEPPER_1')
        self.assertFalse(off['enabled'])
        plan = allocate(self.source, config)
        pins = {e.id: ManualPin(device_id=off['id'], rule_id='off') for e in plan.events}
        pinned = allocate(self.source, config, pins=pins)
        self.assertNotIn(off['id'], {e.device_id for e in pinned.events})
        off['enabled'] = True
        restored = allocate(self.source, config, pins=pins)
        self.assertIn(off['id'], {d['id'] for d in restored.devices})
        self.assertIn(off['id'], {e.device_id for e in restored.events if e.played})

    def test_arrangement_does_not_route_to_disabled_devices(self):
        from playback.arrangement import Arrangement
        disabled = VirtualDeviceInstance.parse({'id': 'off', 'type': 'FDD', 'track': 1, 'enabled': False})
        arrangement = Arrangement.default(self.source, [disabled])
        routes, notes = arrangement.route(self.source)
        self.assertEqual(routes['off'], [])
        self.assertTrue(all(not n['routes'] for n in notes))

    def test_disabled_devices_never_bind_or_generate_hardware_commands(self):
        config = self.config('real')
        orchestra = VirtualOrchestra()
        orchestra.render_plan(allocate(self.source, config))
        bound, _ = bind_devices(config.instances())
        self.assertEqual({d.id for d in bound.values()}, {'fdd-1', 'hdd_vcm-1'})
        commands = build_commands(orchestra, bound)
        self.assertTrue(commands)
        self.assertEqual({c.lane for c in commands}, {'fdd', 'hdd'})
        for d in config.devices:
            d['enabled'] = False
        orchestra.render_plan(allocate(self.source, config))
        bound, _ = bind_devices(config.instances())
        self.assertEqual(build_commands(orchestra, bound), [])
