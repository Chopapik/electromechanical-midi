"""Host addressing capacity; all transport is mocked and no actuators are used."""
import copy
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_source import MidiSource
from orchestra_link import OrchestraLink
from playback.hardware import bind_devices
from playback.virtual import VirtualDeviceInstance
from runtime.arranger import arrange
from runtime.compiler import ExecutionCommand, compile_plan
from runtime.outputs import RealOutput
from runtime.registry import DeviceRegistry
import test_orchestra_link
from test_runtime import Link

ROOT = Path(__file__).resolve().parents[2]
EXTRA = {f'fdd-{i}' for i in range(5, 9)} | {f'DVD_STEPPER_{i}' for i in range(5, 7)}
PRESETS = ('balanced', 'fdd_quality', 'dvd_lead_low_fdd', 'fdd_quality_adaptive',
           'instrument_roles', 'instrument_roles_unison', 'instrument_roles_duet','instrument_roles_unison4', 'universal')


class BackendCapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = DeviceRegistry(volume_path=Path(self.temp.name)/'absent-settings.json')

    def registry_for(self, document):
        path = Path(self.temp.name)/'devices.json'
        path.write_text(json.dumps(document))
        return DeviceRegistry(path, volume_path=Path(self.temp.name)/'absent-settings.json')

    def test_catalog_capacity_activity_and_unverified_profiles(self):
        r = self.registry
        self.assertEqual(Counter(d['type'] for d in r.devices), {'FDD':8, 'DVD_SLED':6, 'HDD_VCM':4, 'VHS':2})
        self.assertEqual({d['id'] for d in r.devices if not d['enabled']}, EXTRA)
        self.assertEqual(sum(d['enabled'] for d in r.devices), 14)
        for d in r.catalog():
            with self.subTest(device=d['id']):
                if d['id'] in EXTRA:
                    self.assertIsNotNone(d['reason'])
                    instance = r.profiles.instances[d['lane']]
                    self.assertIs(instance['present'], False)
                    self.assertEqual(instance['quantities'], {})
                else:
                    self.assertIsNone(d['reason'])
        self.assertEqual(r.document['routing']['tracks'], [None]*4)

    def test_registry_still_rejects_duplicates_wrong_ordinals_and_overflow(self):
        for mutation in ('id', 'lane', 'order', 'overflow'):
            doc = copy.deepcopy(self.registry.document)
            if mutation == 'id': doc['devices'][1]['id'] = doc['devices'][0]['id']
            elif mutation == 'lane': doc['devices'][1]['lane'] = doc['devices'][0]['lane']
            elif mutation == 'order': doc['devices'][0], doc['devices'][1] = doc['devices'][1], doc['devices'][0]
            else:
                extra = copy.deepcopy(doc['devices'][0]);extra.update(id='fdd-9', lane='fdd:9')
                doc['devices'].insert(8, extra)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.registry_for(doc)

    def test_binding_full_capacity_and_disabled_ordinals(self):
        config = self.registry.configuration()
        devices = [VirtualDeviceInstance.parse(d) for d in config.devices]
        bound, unmapped = bind_devices(devices, 2)
        self.assertEqual(len(bound), 14);self.assertEqual(unmapped, [])
        self.assertFalse(EXTRA & {d.id for d in bound.values()})
        for d in devices: d.enabled = True
        bound, unmapped = bind_devices(devices, 2)
        self.assertEqual(len(bound), 20);self.assertEqual(unmapped, [])
        for entry in self.registry.devices:
            self.assertEqual(bound[entry['lane']].id, entry['id'])
        for d in devices:
            if d.id in ('fdd-1', 'fdd-7', 'DVD_STEPPER_1', 'DVD_STEPPER_5'): d.enabled = False
        bound, unmapped = bind_devices(devices, 2)
        self.assertEqual(bound['fdd:8'].id, 'fdd-8')
        self.assertEqual(bound['sled:6'].id, 'DVD_STEPPER_6')
        self.assertNotIn('fdd:7', bound);self.assertNotIn('sled:5', bound)
        self.assertEqual(unmapped, [])
        for kind, maximum in [('FDD',8), ('DVD_SLED',6), ('HDD_VCM',4), ('VHS',2)]:
            family = [VirtualDeviceInstance.parse({'id':f'{kind}{i}', 'type':kind, 'mode':'real'}) for i in range(maximum+1)]
            bound, unmapped = bind_devices(family, 2)
            self.assertEqual(len(bound), maximum);self.assertEqual(len(unmapped), 1)
            self.assertEqual(unmapped[0]['reason'], 'NO_HARDWARE_LANE')

    def test_protocol_type_specific_bounds_for_every_method(self):
        link = test_orchestra_link.ProtocolTests().link()
        for method, maximum, args, command in [
            ('fdd_play',8,(220,),'FDD 8 PLAY 220.00'), ('fdd_home',8,(),'FDD 8 HOME'),
            ('fdd_stop',8,(),'FDD 8 STOP'), ('sled_play',6,(330,),'SLED 6 PLAY 330.00'),
            ('sled_stop',6,(),'SLED 6 STOP'), ('hdd_hit',4,(),'HDD 4 HIT'), ('hdd_stop',4,(),'HDD 4 STOP')]:
            fn = getattr(link, method)
            fn(maximum, *args);link.send.assert_called_with(command)
            for invalid in (0, -1, maximum+1, True, False, '1', 1.0, None):
                with self.subTest(method=method, invalid=invalid), self.assertRaises(ValueError): fn(invalid, *args)

    def test_configure_disables_new_channels_and_retains_all_hdd_hits(self):
        link = Link()
        link.controller_status['speaker_fx'] = '1'
        link.device_status = {k:v for k,v in link.device_status.items()
                              if k not in {'FDD:'+str(i) for i in range(5,9)} | {'SLED:5','SLED:6'}}
        output = RealOutput(self.registry)
        output.attach(link)
        output.configure()
        for ident in EXTRA:
            prefix = output.prefix(ident)
            self.assertEqual([s for s in link.sent if s.startswith(prefix+' ')], [prefix+' ENABLE 0'])
        for i in range(1,5): self.assertIn(f'HDD {i} ENABLE 1', link.sent)
        self.assertFalse(any('HOME' in s or 'PLAY' in s for s in link.sent))
        link.sent.clear()
        commands = [ExecutionCommand(0,f'hdd_vcm-{i}','hit') for i in range(1,5)]
        output.ready(commands)
        output.dispatch(commands)
        self.assertEqual(link.sent, [f'HDD {i} HIT' for i in range(1,5)])

    def test_strict_tracks_still_has_four_slots_and_disables_new_channels(self):
        self.registry.document['routing'] = {'mode':'STRICT_TRACKS', 'tracks':[0,1,2,3]}
        link = Link()
        output = RealOutput(self.registry)
        output.attach(link);output.configure()
        self.assertIn('TRACKS SET 0 1 2 3', link.sent)
        for ident in EXTRA:
            prefix = output.prefix(ident)
            self.assertEqual([s for s in link.sent if s.startswith(prefix+' ')], [prefix+' ENABLE 0'])
        self.registry.document['routing']['tracks'] += [4,5,6,7]
        with self.assertRaises(ValueError): arrange(MidiSource(ROOT/'midi/test.mid'), self.registry)

    def test_legacy_status_and_diag_interleaving_keep_twenty_line_guard(self):
        lines = ['STATUS BEGIN', 'STATUS CTRL protocol=2 ready=1']
        for family in ('FDD','HDD','SLED'):
            lines += [f'STATUS {family} {i} enabled=1' for i in range(1,5)]
        lines += ['STATUS VHS enabled=1','STATUS VHS2 enabled=1','STATUS END']
        self.assertEqual(len(lines), 17)
        link = test_orchestra_link.ProtocolTests().link()
        with patch('floppy_link.FloppyLink.poll_lines', return_value=lines): link.poll_lines()
        before = copy.deepcopy(link.device_status)
        self.assertEqual(len(before), 14)
        with patch('floppy_link.FloppyLink.poll_lines', return_value=['DIAG BEGIN','DIAG FDD 8 enabled=0','DIAG SLED 6 enabled=0','DIAG END']): link.poll_lines()
        self.assertEqual(link.device_status, before)
        oversized = lines[:-1] + ['STATUS FDD 8 enabled=1']*5 + ['STATUS END']
        with patch('floppy_link.FloppyLink.poll_lines', return_value=oversized): link.poll_lines()
        self.assertEqual(link.device_status, before)
        self.assertIsNone(link._status_lines)

    def test_disabled_pool_does_not_change_active_plans_or_policy(self):
        source = MidiSource(ROOT/'midi/test.mid')
        for preset in PRESETS:
            with self.subTest(preset=preset):
                full = copy.deepcopy(self.registry.document)
                full['parameters']['arrangementPreset'] = preset
                reduced = copy.deepcopy(full)
                reduced['devices'] = [d for d in reduced['devices'] if d['enabled']]
                a = arrange(source, self.registry_for(full))
                b = arrange(source, self.registry_for(reduced))
                self.assertEqual(a.policy, b.policy)
                self.assertEqual(a.events, b.events)
                self.assertEqual(a.reinforcements, b.reinforcements)
                self.assertEqual(a.execution_articulation, b.execution_articulation)
                self.assertEqual(compile_plan(a), compile_plan(b))
                self.assertFalse(EXTRA & {c.device_id for c in compile_plan(a).commands})
