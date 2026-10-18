"""Auto-homing preparation before REAL orchestra playback; no physical I/O."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_runtime import Link
from runtime.application import Application
from runtime.registry import DeviceRegistry
from runtime.player import Player
from runtime.compiler import ExecutionCommand as C,ExecutionTimeline as T
from runtime.outputs import OutputError

class AutoHomingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=Application(DeviceRegistry(volume_path=Path(self.temp.name)/'settings.json'))
        self.now=100.
        self.player=Player(self.app.router,clock=lambda:self.now)
        self.app.player=self.player;self.app.service.player=self.player;self.app.lab.player=self.player
        self.link=Link();self.app.real.attach(self.link);self.app.real.configured=True
        self.player.load(T((C(0,'fdd-1','tone',1,220),C(1,'fdd-1','stop')),1))
        self.link.sent.clear();self.link.device_status['FDD:1'].update(homed='0',homing='0')
    def tearDown(self):self.temp.cleanup()
    def complete_home(self):
        self.player.tick() # Request one STATUS transaction.
        self.link.device_status['FDD:1'].update(homed='1',homing='0')
        self.player.tick() # Consume complete STATUS, then arm song clock.
    def test_starts_only_required_drives_and_song_clock_waits(self):
        self.link.device_status['FDD:2']['homed']='0'
        self.player.play()
        self.assertTrue(self.player.homing);self.assertNotEqual(self.player.state,'playing')
        self.assertEqual([c for c in self.link.sent if c.endswith(' HOME')],['FDD 1 HOME'])
        self.now+=4
        self.assertEqual(self.player.position(),0)
        self.complete_home()
        self.assertFalse(self.player.homing);self.assertEqual(self.player.state,'playing');self.assertEqual(self.player.position(),0)
        self.player.tick();self.assertIn('FDD 1 PLAY 220.00',self.link.sent);self.assertEqual(self.player.dropped,0)
    def test_already_homed_does_not_home_again(self):
        self.link.device_status['FDD:1']['homed']='1'
        self.player.play();self.player.tick()
        self.assertFalse(self.player.homing);self.assertFalse(any(' HOME' in s for s in self.link.sent))
        self.assertIn('FDD 1 PLAY 220.00',self.link.sent)
    def test_stop_cancels_preparation_without_later_auto_play(self):
        self.player.play();self.player.play() # Duplicate PLAY must not restart HOME.
        self.assertEqual(self.link.sent.count('FDD 1 HOME'),1)
        self.player.stop();self.now+=10
        self.link.device_status['FDD:1']['homed']='1';self.player.tick()
        self.assertFalse(self.player.homing);self.assertEqual(self.player.state,'stopped')
        self.assertEqual(self.app.real.homing_devices,())
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))
    def test_muted_drive_and_virtual_never_home(self):
        self.player.mute('fdd-1',True);self.link.sent.clear();self.player.play()
        self.assertFalse(self.player.homing);self.assertFalse(any(' HOME' in s for s in self.link.sent))
        self.player.stop();self.player.switch('VIRTUAL');self.app.virtual.owner='browser';self.link.sent.clear()
        self.player.play();self.assertFalse(self.player.homing);self.assertEqual(self.link.sent,[])
    def test_lab_keeps_explicit_home_requirement(self):
        self.app.lab.enter('test')
        with self.assertRaisesRegex(OutputError,'homing TRACK0'):self.app.lab.test('test','fdd-1',220,1)
        self.assertFalse(any(' HOME' in s for s in self.link.sent))
    def test_no_home_or_auto_power_on_when_atx_off(self):
        self.link.controller_status['atx']='OFF'
        with self.assertRaisesRegex(OutputError,'ATX OFF'):self.player.play()
        self.assertEqual(self.link.sent,[]);self.assertFalse(self.player.homing)
    def test_home_failed_aborts_without_notes_or_reconnect_resume(self):
        self.player.play();self.link.lines.append('ERR HOME_FAILED FDD=1');self.player.tick()
        self.assertFalse(self.player.homing);self.assertEqual(self.player.state,'paused');self.assertIn('HOME_FAILED',self.player.error)
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))
        fresh=Link();self.app.real.attach(fresh);self.player.tick()
        self.assertEqual(self.player.state,'paused');self.assertFalse(any(' PLAY ' in s for s in fresh.sent))
    def test_timeout_stops_homing_and_reports_error(self):
        self.player.play()
        with patch('runtime.outputs.time.monotonic',return_value=self.app.real.homing_deadline+1):self.player.tick()
        self.assertFalse(self.player.homing);self.assertEqual(self.player.state,'paused')
        self.assertIn('Homing TRACK0',self.player.error);self.assertFalse(any(' PLAY ' in s for s in self.link.sent))
    def test_complete_fresh_status_required_and_requests_do_not_overlap(self):
        self.player.play();self.player.tick();self.link.lines.clear()
        generation=self.link.status_generation
        self.link.device_status['FDD:1'].update(homed='1',homing='0')
        for _ in range(4):self.player.tick()
        self.assertTrue(self.player.homing);self.assertEqual(self.link.status_generation,generation);self.assertEqual(self.link.lines,[])
        self.link.lines.append('STATUS END');self.player.tick()
        self.assertFalse(self.player.homing);self.assertEqual(self.player.state,'playing')
    def test_mute_during_preparation_cancels_start(self):
        self.player.play();self.player.mute('fdd-1',True)
        self.assertFalse(self.player.homing);self.assertEqual(self.player.state,'stopped')
    def test_power_cycle_requires_home_again(self):
        self.link.device_status['FDD:1']['homed']='1'
        self.app.service.run('power_off');self.app.service.run('power_on',confirmed=True)
        self.link.sent.clear();self.player.play()
        self.assertTrue(self.player.homing);self.assertIn('FDD 1 HOME',self.link.sent)
    def test_configuration_enables_dvd_before_direction_on_fresh_boot(self):
        self.app.real.configured=False;self.app.real.configure()
        for i in range(1,5):
            self.assertLess(self.link.sent.index(f'SLED {i} ENABLE 1'),self.link.sent.index(f'SLED {i} DIR FWD'))

    def test_missing_stop_ack_never_starts_home(self):
        self.link.fail_stop=True
        with self.assertRaisesRegex(OutputError,'STOP'):self.player.play()
        self.assertFalse(self.player.homing);self.assertTrue(self.app.real.unknown)
        self.assertFalse(any(' HOME' in s for s in self.link.sent))

    def test_ble_loss_while_homing_aborts(self):
        self.player.play()
        self.link.poll_lines=lambda:(_ for _ in ()).throw(OSError('BLE disconnected'))
        self.player.tick()
        self.assertFalse(self.player.homing);self.assertEqual(self.player.state,'paused')
        self.assertIn('BLE disconnected',self.player.error)
        self.assertFalse(any(' PLAY ' in s for s in self.link.sent))
