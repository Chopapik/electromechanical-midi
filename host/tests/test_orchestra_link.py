import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import Mock, patch
from orchestra_link import OrchestraLink, parse_status
from playback.hardware import bind_devices, build_commands
from playback.orchestra import esp32_startup_config
from playback.virtual import VirtualDeviceInstance
from firmware import run_firmware


class ProtocolTests(unittest.TestCase):
    def link(self):
        link = OrchestraLink.__new__(OrchestraLink)
        link.send = Mock()
        link.protocol_version = 2
        link.device_status = {}
        link.controller_status = {}
        link._status_lines = None
        return link

    def test_commands(self):
        l = self.link()
        l.fdd_play(4,220); l.fdd_home(3); l.fdd_stop(2)
        l.hdd_hit(4); l.hdd_stop(2); l.sled_play(3,196); l.sled_stop(1)
        l.tray_pulse(2,'REV',80); l.tray_stop(1)
        l.vhs_amp(200); l.vhs_freq(164.81); l.vhs_stop(); l.ping(); l.status(); l.all_stop()
        self.assertEqual([c.args[0] for c in l.send.call_args_list], [
            'FDD 4 PLAY 220.00','FDD 3 HOME','FDD 2 STOP','HDD 4 HIT','HDD 2 STOP',
            'SLED 3 PLAY 196.00','SLED 1 STOP','TRAY 2 PULSE REV 80','TRAY 1 STOP',
            'VHS AMP 200','VHS FREQ 164.81','VHS STOP','PING','STATUS','ALL STOP'])
        for id in (0,5,True,'1'):
            with self.assertRaises(ValueError): l.fdd_home(id)
        with self.assertRaises(ValueError): l.tray_pulse(1,'oops',10)

    def test_stop_waits_for_matching_execution_ack(self):
        l = self.link()
        l.poll_lines = Mock(side_effect=[['STOPPED 99'], ['STOPPED 42']])
        with patch('orchestra_link.time.monotonic_ns', return_value=42):
            self.assertTrue(l.all_stop_confirmed(timeout=.1))
        l.send.assert_called_once_with('ALL STOP 42')
        self.assertEqual(l.poll_lines.call_count, 2)

    def test_stop_ack_timeout_is_not_a_serial_disconnect(self):
        from orchestra_link import StopConfirmationError
        l = self.link(); l.poll_lines = Mock(return_value=[])
        with self.assertRaises(StopConfirmationError): l.all_stop_confirmed(timeout=.01)

    def test_status_complete_only(self):
        lines = ['STATUS BEGIN','STATUS CTRL board=esp32 ready=1','STATUS FDD 4 enabled=1 homed=1 homing=0',
                 'STATUS HDD 3 enabled=0 busy=0','STATUS VHS enabled=1 amp=38 hz=196','STATUS END']
        parsed = parse_status(lines)
        self.assertEqual(parsed['devices']['FDD:4']['homed'],'1')
        with self.assertRaises(ValueError): parse_status(lines[:-1])
        l = self.link()
        with patch('floppy_link.FloppyLink.poll_lines', side_effect=[lines[:-1],lines[-1:]]):
            l.poll_lines(); self.assertEqual(l.device_status,{})
            l.poll_lines(); self.assertEqual(l.device_status,parsed['devices'])
            self.assertIsNotNone(l.status_observed_at)

    def test_ready_negotiates_v2(self):
        l=self.link();l.protocol_version=1
        with patch('floppy_link.FloppyLink.poll_lines', return_value=['READY protocol=2 board=esp32']):
            l.poll_lines()
        self.assertEqual(l.protocol_version,2)

    def test_preset_and_stable_ids(self):
        config=esp32_startup_config()
        self.assertEqual(len(config['devices']),15)
        devices=[VirtualDeviceInstance.parse(d) for d in config['devices']]
        self.assertTrue(all(not d.enabled for d in devices if d.type in ('DVD_SLED','DVD_TRAY')))
        devices[0].enabled=False
        bound,unmapped=bind_devices(devices,2)
        self.assertNotIn('fdd:1',bound)
        self.assertEqual(bound['fdd:2'].id,devices[1].id)
        self.assertEqual(len(bound),8)
        self.assertEqual(unmapped,[])
        _,unmapped=bind_devices(devices,1)
        self.assertTrue(unmapped)

    def test_build_target(self):
        with patch('firmware.subprocess.run',return_value=Mock(returncode=0,stdout='built')) as run:
            run_firmware('pio',target='esp32')
        self.assertIn('esp32',run.call_args.args[0])
        with self.assertRaises(ValueError): run_firmware('pio',target='bad')

    def test_v2_home_requires_status_not_ready(self):
        l=self.link()
        lines=['STATUS BEGIN','STATUS CTRL board=esp32 ready=1','STATUS FDD 1 enabled=1 homed=1 homing=0','STATUS END']
        with patch('floppy_link.FloppyLink.poll_lines',return_value=lines):
            self.assertTrue(l.wait_homed(timeout=.2,echo=lambda _:None))
        lines[2]='STATUS FDD 1 enabled=1 homed=0 homing=1'
        with patch('floppy_link.FloppyLink.poll_lines',return_value=lines):
            self.assertFalse(l.wait_homed(timeout=.02,echo=lambda _:None))

    def test_dispatch_and_global_stop(self):
        from playback.engine import PlaybackEngine
        from playback.timeline import Command
        e=PlaybackEngine(wait_ready=False);l=self.link();e._transport=l
        e._hardware.connected=True;e._hardware.homed=True
        self.assertTrue(e._send_locked(Command(0,'play',hz=220,lane='fdd:4')))
        self.assertTrue(e._send_locked(Command(0,'hit',lane='hdd:3')))
        self.assertTrue(e._send_locked(Command(0,'tray_pulse',hz=80,lane='tray:2')))
        self.assertEqual([c.args[0] for c in l.send.call_args_list],['FDD 4 PLAY 220.00','HDD 3 HIT','TRAY 2 PULSE FWD 80'])
        e._virtual_mode=False;e._reset_instruments_locked()
        self.assertEqual(l.send.call_args.args[0],'ALL STOP')
        e._hardware.homed=False
        with patch.object(e,'_start_home_locked'):
            self.assertFalse(e._send_locked(Command(0,'play',hz=220,lane='fdd:2')))
        self.assertTrue(e._hardware.connected)

    def test_connect_v2_syncs_then_homes_and_preserves_transport(self):
        from playback.engine import PlaybackEngine
        l=self.link();l.wait_ready=Mock(return_value=True);l.wait_boot=Mock(return_value=True)
        l.wait_homed=Mock(return_value=True);l.close=Mock();l.port='fake-cp2102'
        e=PlaybackEngine(connect_fn=lambda _:l,wait_ready=True)
        self.assertTrue(e.connect('fake-cp2102'))
        sent=[c.args[0] for c in l.send.call_args_list]
        self.assertIn('FDD ALL HOME',sent)
        self.assertLess(sent.index('FDD 1 ENABLE 0'),sent.index('FDD ALL HOME'))
        self.assertTrue(e.snapshot()['hardware']['connected'])
        self.assertTrue(e.snapshot()['hardware']['ready'])
        l.wait_homed.return_value=False
        self.assertFalse(e.home())
        self.assertTrue(e.snapshot()['hardware']['connected'])
        self.assertFalse(e.snapshot()['hardware']['ready'])

    def test_incomplete_status_cannot_confirm_homing(self):
        l=self.link()
        with patch('floppy_link.FloppyLink.poll_lines',return_value=['STATUS BEGIN','STATUS CTRL ready=1','STATUS END']):
            self.assertFalse(l.wait_homed(timeout=.02,echo=lambda _:None))

    def test_upload_v2_keeps_target_and_reconnect_handshake(self):
        from firmware import flash_engine
        e=Mock()
        with patch('firmware.run_firmware',return_value='ok') as run, patch('firmware.wait_upload_port',return_value='/dev/cp2102'):
            self.assertTrue(flash_engine(e,'pio','/dev/cp2102',target='esp32')['ready'])
        self.assertEqual([c.kwargs for c in run.call_args_list],[{'target':'esp32'},{'target':'esp32'}])
        e.connect.assert_called_once_with('/dev/cp2102')

    def test_hardware_event_ids_and_disabled_filter(self):
        from types import SimpleNamespace
        a=VirtualDeviceInstance.parse({'id':'fdd1','type':'FDD','mode':'real','enabled':False})
        b=VirtualDeviceInstance.parse({'id':'fdd2','type':'FDD','mode':'real'})
        h=VirtualDeviceInstance.parse({'id':'hdd1','type':'HDD_VCM','mode':'real'})
        bound,_=bind_devices([a,b,h],2)
        event=lambda id: SimpleNamespace(device=id,time=0,duration=.2,hz=220)
        commands=build_commands(SimpleNamespace(events=[event('fdd1'),event('fdd2'),event('hdd1')]),bound)
        self.assertEqual([(c.kind,c.lane) for c in commands],[('play','fdd:2'),('stop','fdd:2'),('hit','hdd:1')])
