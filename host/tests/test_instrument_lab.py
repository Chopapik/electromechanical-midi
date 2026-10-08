import threading
import unittest
from unittest.mock import patch
from playback.engine import PlaybackEngine, PlaybackState
from playback.orchestra import default_orchestra


class Transport:
    protocol_version=2
    def __init__(self):
        self.commands=[]
        self.device_status={f'{family}:{i}': {'enabled':'1','homed':'1','homing':'0','busy':'0','playing':'0'} for family in ('SLED','FDD','HDD') for i in range(1,5)}
        self.device_status['VHS']={'enabled':'1','amp':'0','hz':'0'}
    def send(self,command):self.commands.append(command)
    def send_batch(self,commands):self.commands.extend(commands)


class InstrumentLabTests(unittest.TestCase):
    def setUp(self):
        self.engine=PlaybackEngine()
        self.engine._orchestra=default_orchestra()
        for device in self.engine._orchestra.devices:device['mode']='real'
        self.engine._controller_target='esp32'
        self.engine._hardware.connected=True
        self.engine._transport=Transport()
        self.lab=self.engine._lab
        self.clock=patch('playback.instrument_lab.time.monotonic',return_value=100)
        self.now=self.clock.start();self.addCleanup(self.clock.stop)
        self.lab.enter('session')

    def start(self,**overrides):
        self.lab.start('session',dict(device='sled:1',hz=392,duration=3,**overrides))

    def test_392_three_seconds_backend_stop_and_confirmation(self):
        self.start();self.assertEqual(self.lab.state,'starting')
        self.assertIn('SLED 1 PLAY 392.000000',self.engine._transport.commands)
        self.engine._transport.device_status['SLED:1'].update(playing='1',hz='392.00')
        self.lab.on_lines(['STATUS END']);self.assertEqual(self.lab.state,'playing')
        self.now.return_value=102.99;self.lab.tick();self.assertTrue(self.lab.active)
        self.now.return_value=103;self.lab.tick()
        self.assertEqual(self.engine._transport.commands[-1],'ALL STOP')
        self.assertFalse(self.lab.active)

    def test_early_stop_and_reentry_no_play(self):
        self.start();self.lab.leave('session')
        self.assertEqual(self.engine._transport.commands[-1],'ALL STOP')
        before=list(self.engine._transport.commands);self.lab.enter('session')
        self.assertEqual(before,self.engine._transport.commands)
        self.assertFalse(self.lab.active)

    def test_invalid_frequency_and_parameters_send_nothing(self):
        for hz in (150,220,250,320,490,float('nan')):
            with self.subTest(hz=hz),self.assertRaises(ValueError):self.lab.start('session',{'device':'sled:1','hz':hz})
        for params in ({'device':'sled:99'},{'device':'sled:1','hz':392,'duration':0},{'device':'sled:1','hz':392,'duration':float('inf')}):
            with self.assertRaises(ValueError):self.lab.start('session',params)
        self.assertEqual(self.engine._transport.commands,[])

    def test_disconnected_and_midi_rejected(self):
        self.engine._hardware.connected=False
        with self.assertRaises(ValueError):self.start()
        self.engine._hardware.connected=True;self.engine._state=PlaybackState.PLAYING
        with self.assertRaises(ValueError):self.start()
        self.assertEqual(self.engine._transport.commands,[])

    def test_hdd_single_hit(self):
        self.lab.start('session',{'device':'hdd:1'})
        self.assertEqual(self.engine._transport.commands,['HDD 1 HIT','STATUS'])
        self.now.return_value=103;self.lab.tick()
        self.assertEqual(self.engine._transport.commands.count('HDD 1 HIT'),1)
        self.assertFalse(self.lab.active)

    def test_disconnect_lease_and_owner_safety(self):
        self.start()
        with self.assertRaises(ValueError):self.lab.enter('second')
        with self.assertRaises(ValueError):self.start()
        self.lab.leave('second');self.assertTrue(self.lab.active)
        self.now.return_value=106;self.lab.tick()
        self.assertIsNone(self.lab.owner);self.assertFalse(self.lab.active)
        self.assertEqual(self.engine._transport.commands[-1],'ALL STOP')

    def test_controller_loss_sends_stop(self):
        self.start();self.engine._hardware.connected=False;self.lab.tick()
        self.assertFalse(self.lab.active)
        self.assertEqual(self.engine._transport.commands[-1],'ALL STOP')

    def test_disabled_and_unhomed_do_not_play(self):
        self.engine._transport.device_status['FDD:1']['homed']='0'
        with self.assertRaises(ValueError):self.lab.start('session',{'device':'fdd:1','hz':392})
        next(d for d in self.engine._orchestra.devices if d['type']=='DVD_SLED')['enabled']=False
        with self.assertRaises(ValueError):self.start()
        self.assertEqual(self.engine._transport.commands,[])

    def test_failed_stop_can_be_retried_without_reconnect(self):
        self.start()
        with patch.object(self.engine,'_safe_send_stop_locked',return_value=False):
            self.lab.stop()
        self.assertEqual(self.lab.state,'error')
        self.assertTrue(self.lab.needs_stop)
        self.engine.lab_command('lab_stop','session')
        self.assertFalse(self.lab.needs_stop)
        self.assertEqual(self.lab.state,'stopped')

    def test_global_stop_updates_lab_and_stops_hardware(self):
        self.start();self.engine.stop()
        self.assertFalse(self.lab.active)
        self.assertIn('ALL STOP',self.engine._transport.commands)

    def test_finite_hit_can_confirm_after_firmware_already_finished(self):
        self.lab.start('session',{'device':'hdd:1'})
        self.now.return_value=100.2
        self.lab.on_lines(['STATUS END'])
        self.assertTrue(self.lab.confirmed)
        self.assertEqual(self.lab.state,'stopped')

    def test_midi_cannot_begin_in_lab(self):
        with self.assertRaises(Exception):self.engine._begin_locked(0)

class LabSessionTests(unittest.TestCase):
    def test_websocket_disconnect_releases_lab_and_stops_hardware(self):
        import tempfile
        from pathlib import Path
        from fastapi.testclient import TestClient
        from web.server import create_app
        e=PlaybackEngine()
        e._controller_target='esp32';e._hardware.connected=True
        e._orchestra=default_orchestra()
        for device in e._orchestra.devices:device['mode']='real'
        transport=Transport();transport.poll_lines=lambda:[];transport.close=lambda:None
        e._transport=transport
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(midi_dir=Path(directory),engine=e,connect_on_start=False)) as client:
                with client.websocket_connect('/ws') as socket:
                    socket.receive_json()
                    socket.send_json({'action':'lab_enter'})
                    while not socket.receive_json().get('state',{}).get('lab',{}).get('enabled'):pass
                    socket.send_json({'action':'lab_start','device':'sled:1','hz':392,'duration':3})
                    while not e._lab.active:socket.receive_json()
                    # Receive a worker-driven update, without a client action.
                    for _ in range(10):
                        update=socket.receive_json()
                        if not update.get('completedAction') and update['state']['lab']['state']=='starting':break
                    else:self.fail('Lab updates must remain subscribed to broadcasts')
                # Synchronize through HTTP after the ASGI websocket finalizer.
                import time
                for _ in range(100):
                    if e._lab.owner is None:break
                    time.sleep(.01)
                self.assertIsNone(e._lab.owner)
                self.assertFalse(e._lab.active)
                self.assertEqual(transport.commands[-1],'ALL STOP')
