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
from orchestra_link import OrchestraLink, parse_status
from playback.hardware import bind_devices
from playback.virtual import VirtualDeviceInstance
from runtime.arranger import arrange
from runtime.compiler import ExecutionCommand, compile_plan
from runtime.outputs import RealOutput
from runtime.registry import DeviceRegistry
import test_orchestra_link
from test_runtime import Link

ROOT = Path(__file__).resolve().parents[2]
EXTENDED_FDD = {f'fdd-{i}' for i in range(5, 9)}
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

    def test_catalog_capacity_activity_and_profiles(self):
        r = self.registry
        self.assertEqual(Counter(d['type'] for d in r.devices), {'FDD':8, 'DVD_SLED':4, 'HDD_VCM':4, 'VHS':2})
        self.assertEqual({d['id'] for d in r.devices if not d['enabled']},{'hdd_vcm-3','hdd_vcm-4'})
        self.assertEqual(sum(d['enabled'] for d in r.devices), 16)
        for d in r.catalog():
            with self.subTest(device=d['id']):
                self.assertEqual(d['reason'] is None,d['enabled'])
                if d['id'] in EXTENDED_FDD:
                    instance = r.profiles.instances[d['lane']]
                    self.assertIs(instance['present'], True)
                    self.assertEqual(instance['quantities']['travelSteps']['value'],72)
                    self.assertEqual(instance['quantities']['executionMinStepUs']['value'],2439)
                    self.assertEqual(instance['quantities']['travelSteps']['confidence'],'LOW')
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
        self.assertEqual(len(bound), 16);self.assertEqual(unmapped, [])
        for d in devices: d.enabled = True
        bound, unmapped = bind_devices(devices, 2)
        self.assertEqual(len(bound), 18);self.assertEqual(unmapped, [])
        for entry in self.registry.devices:
            self.assertEqual(bound[entry['lane']].id, entry['id'])
        for d in devices:
            if d.id in ('fdd-1', 'fdd-7', 'DVD_STEPPER_1', 'DVD_STEPPER_3'): d.enabled = False
        bound, unmapped = bind_devices(devices, 2)
        self.assertEqual(bound['fdd:8'].id, 'fdd-8')
        self.assertEqual(bound['sled:4'].id, 'DVD_STEPPER_4')
        self.assertNotIn('fdd:7', bound);self.assertNotIn('sled:3', bound)
        self.assertEqual(unmapped, [])
        for kind, maximum in [('FDD',8), ('DVD_SLED',4), ('HDD_VCM',4), ('VHS',2)]:
            family = [VirtualDeviceInstance.parse({'id':f'{kind}{i}', 'type':kind, 'mode':'real'}) for i in range(maximum+1)]
            bound, unmapped = bind_devices(family, 2)
            self.assertEqual(len(bound), maximum);self.assertEqual(len(unmapped), 1)
            self.assertEqual(unmapped[0]['reason'], 'NO_HARDWARE_LANE')

    def test_protocol_type_specific_bounds_for_every_method(self):
        link = test_orchestra_link.ProtocolTests().link()
        for method, maximum, args, command in [
            ('fdd_play',8,(220,),'FDD 8 PLAY 220.00'), ('fdd_home',8,(),'FDD 8 HOME'),
            ('fdd_stop',8,(),'FDD 8 STOP'), ('sled_play',4,(330,),'SLED 4 PLAY 330.00'),
            ('sled_stop',4,(),'SLED 4 STOP'), ('hdd_hit',4,(),'HDD 4 HIT'), ('hdd_stop',4,(),'HDD 4 STOP')]:
            fn = getattr(link, method)
            fn(maximum, *args);link.send.assert_called_with(command)
            for invalid in (0, -1, maximum+1, True, False, '1', 1.0, None):
                with self.subTest(method=method, invalid=invalid), self.assertRaises(ValueError): fn(invalid, *args)

    def test_configure_enables_extended_fdd_and_retains_all_hdd_hits(self):
        # Capacity remains four; this test explicitly opts into all physical HDD.
        for d in self.registry.devices:
            if d['type']=='HDD_VCM':d['enabled']=True
        link = Link()
        link.controller_status['speaker_fx'] = '1'
        link.device_status = {k:v for k,v in link.device_status.items()
                              if k not in {'FDD:'+str(i) for i in range(5,9)}}
        output = RealOutput(self.registry)
        output.attach(link)
        output.configure()
        for ident in EXTENDED_FDD:
            prefix = output.prefix(ident)
            self.assertIn(prefix+' ENABLE 1',link.sent)
        self.assertEqual({line.split()[1] for line in link.sent if line.startswith('SLED ')}, {'1','2','3','4'})
        for i in range(1,5): self.assertIn(f'HDD {i} ENABLE 1', link.sent)
        self.assertFalse(any('HOME' in s or 'PLAY' in s for s in link.sent))
        self.assertEqual(link.extended_status_generation, 1)
        link.sent.clear()
        commands = [ExecutionCommand(0,f'hdd_vcm-{i}','hit') for i in range(1,5)]
        output.ready(commands)
        output.dispatch(commands)
        self.assertEqual(link.sent, [f'HDD {i} HIT' for i in range(1,5)])

    def test_extended_fdd_configure_status_home_and_play_lifecycle(self):
        registry=self.registry
        link=Link()
        output=RealOutput(registry)
        output.attach(link);output.configure()
        for ident in EXTENDED_FDD:
            self.assertIn(output.prefix(ident)+' ENABLE 1',link.sent)
        self.assertEqual(link.extended_status_generation,1)
        command=ExecutionCommand(0,'fdd-8','tone',.1,220)
        link.device_status['FDD:8'].update(homed='0',homing='0')
        self.assertFalse(output.ready([command],auto_home=True))
        self.assertIn('FDD 8 HOME',link.sent)
        self.assertFalse(output.homing_ready())
        link.device_status['FDD:8'].update(homed='1',homing='0')
        link.poll_lines()
        self.assertTrue(output.homing_ready())
        output.dispatch([command])
        self.assertIn('FDD 8 PLAY 220.00',link.sent)

    def test_strict_tracks_still_has_four_slots_and_disables_new_channels(self):
        self.registry.document['routing'] = {'mode':'STRICT_TRACKS', 'tracks':[0,1,2,3]}
        link = Link()
        output = RealOutput(self.registry)
        output.attach(link);output.configure()
        self.assertIn('TRACKS SET 0 1 2 3', link.sent)
        for ident in EXTENDED_FDD | {d['id'] for d in self.registry.devices if d['type']=='DVD_SLED'}:
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
        with patch('floppy_link.FloppyLink.poll_lines', return_value=['DIAG BEGIN','DIAG FDD 8 enabled=0','DIAG END']): link.poll_lines()
        self.assertEqual(link.device_status, before)
        oversized = lines[:-1] + ['STATUS FDD 8 enabled=1']*5 + ['STATUS END']
        with patch('floppy_link.FloppyLink.poll_lines', return_value=oversized): link.poll_lines()
        self.assertEqual(link.device_status, before)
        self.assertIsNone(link._status_lines)

    def test_all_presets_use_only_existing_catalog_lanes(self):
        source = MidiSource(ROOT/'midi/test.mid')
        for preset in PRESETS:
            with self.subTest(preset=preset):
                full = copy.deepcopy(self.registry.document)
                full['parameters']['arrangementPreset'] = preset
                a = arrange(source, self.registry_for(full))
                self.assertEqual(a.policy['arrangementPreset'],preset)
                self.assertEqual(len(a.devices),18)
                self.assertEqual({d['id'] for d in a.devices if d['type']=='DVD_SLED'},
                                 {f'DVD_STEPPER_{i}' for i in range(1,5)})
                self.assertLessEqual({c.device_id for c in compile_plan(a).commands},set(self.registry.by_id))

    def test_registry_rejects_an_additional_sled(self):
        doc=copy.deepcopy(self.registry.document)
        extra=copy.deepcopy(next(d for d in doc['devices'] if d['type']=='DVD_SLED'))
        count=sum(d['type']=='DVD_SLED' for d in doc['devices'])
        extra.update(id='unsupported-sled',lane=f'sled:{count+1}')
        doc['devices'].insert(8+count,extra)
        with self.assertRaises(ValueError):self.registry_for(doc)

    def test_status_rejects_out_of_range_sled_ordinals(self):
        count=sum(d['type']=='DVD_SLED' for d in self.registry.devices)
        for ordinal in (0,count+1,count+2):
            with self.subTest(ordinal=ordinal),self.assertRaises(ValueError):
                parse_status(['STATUS BEGIN',f'STATUS SLED {ordinal} enabled=1','STATUS END'])
