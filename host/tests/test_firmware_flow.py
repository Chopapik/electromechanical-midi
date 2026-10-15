"""Firmware UI transport through WebSocket with controlled USB, PlatformIO and BLE."""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from runtime.application import Application
from web.server import create_app

class Link:
    def __init__(self, valid=True):
        self.valid=valid; self.closed=False; self.status_generation=0
        self.controller_status={'board':'esp32','protocol':'2','ready':'1','stop_ack':'1','hardware_profiles':'1','strict_tracks':'1'}
        if not valid: self.controller_status['protocol']='1'
    def wait_boot(self,**_): return True
    def status(self): self.status_generation+=1
    def ping(self): pass
    def poll_lines(self): return ['STATUS END']
    def all_stop_confirmed(self): return True
    def close(self): self.closed=True

class FirmwareFlowTests(unittest.TestCase):
    def port(self): return [SimpleNamespace(vid=0x10c4,device='/dev/cu.usbserial-test')]
    def test_websocket_upload_logs_progress_flash_and_verified_ble(self):
        link=Link(); runtime=Application(connect=lambda:link)
        runtime.service.restart_delay=.01
        def upload(_tool,port=None,*,target,on_line):
            self.assertEqual(target,'esp32')
            if port:
                self.assertIsNone(runtime.real.link)
                on_line('Writing at 0x00001000... (37 %)')
                on_line('Writing at 0x00002000... (100 %)')
            else: on_line('BUILD SUCCESSFUL')
            return 'ok'
        with patch('runtime.device_service.scan_ports',side_effect=self.port),patch('runtime.device_service.platformio',return_value='pio'),patch('runtime.device_service.run_firmware',side_effect=upload),tempfile.TemporaryDirectory() as directory,TestClient(create_app(midi_dir=directory,runtime=runtime,connect_on_start=False)) as client:
            with client.websocket_connect('/ws') as ws:
                self.assertEqual(ws.receive_json()['type'],'hello')
                self.assertTrue(client.get('/api/state').json()['service']['firmware']['available'])
                ws.send_json({'action':'service','operation':'firmware','requestId':'flash'})
                seen=[]
                while True:
                    message=ws.receive_json()
                    if message.get('type')=='firmware_event': seen.append(message)
                    if message.get('type')=='ack' and message.get('requestId')=='flash': break
                deadline=time.monotonic()+2
                while not any(event.get('ble')=='verified' for event in seen) and time.monotonic()<deadline:
                    message=ws.receive_json()
                    if message.get('type')=='firmware_event': seen.append(message)
                self.assertTrue(any(event.get('stage')=='prepare' for event in seen))
                self.assertTrue(any(event.get('stage')=='build' for event in seen))
                self.assertTrue(any(event.get('stage')=='upload' for event in seen))
                self.assertTrue(any(event.get('progress')==37 for event in seen))
                self.assertTrue(any(event.get('flash')=='success' for event in seen))
                self.assertTrue(any(event.get('ble')=='verified' for event in seen))
                self.assertIn('BUILD SUCCESSFUL',[event.get('line') for event in seen])
                self.assertTrue(client.get('/api/state').json()['output']['connected'])
                self.assertEqual(client.get('/api/state').json()['state'],'stopped')
                self.assertEqual(client.get('/api/firmware/events').json()[-1]['ble'],'verified')
    def test_failed_upload_never_reports_flash_success(self):
        runtime=Application(connect=lambda:Link())
        runtime.service.restart_delay=.01
        def upload(_tool,port=None,*,target,on_line):
            on_line('Port busy')
            if port: raise RuntimeError('Port busy')
            return 'ok'
        with patch('runtime.device_service.scan_ports',side_effect=self.port),patch('runtime.device_service.platformio',return_value='pio'),patch('runtime.device_service.run_firmware',side_effect=upload):
            with self.assertRaisesRegex(RuntimeError,'Port busy'): runtime.service.run('firmware')
        self.assertEqual(runtime.service.status()['firmware']['flash'],'failed')
        self.assertFalse(any(event.get('flash')=='success' for event in runtime.service.events))
        runtime.service.shutdown()
    def test_handshake_rejection_retries_without_false_connected(self):
        attempts=[Link(valid=False),Link(valid=True)]
        runtime=Application(connect=lambda:attempts.pop(0))
        runtime.service.restart_delay=.01; runtime.service.retry_delay=.01
        with patch('runtime.device_service.scan_ports',side_effect=self.port),patch('runtime.device_service.platformio',return_value='pio'),patch('runtime.device_service.run_firmware',return_value='ok'):
            runtime.service.run('firmware')
            deadline=time.monotonic()+2
            while runtime.service.status()['firmware']['ble']!='verified' and time.monotonic()<deadline: time.sleep(.01)
        self.assertTrue(any(event.get('ble')=='retrying' for event in runtime.service.events))
        self.assertTrue(attempts==[])
        self.assertTrue(runtime.real.status()['connected'])
        runtime.service.shutdown()
    def test_usb_absence_multiple_ports_and_missing_platformio(self):
        runtime=Application(connect=lambda:Link())
        with patch('runtime.device_service.scan_ports',return_value=[]):
            runtime.service.refresh()
            self.assertFalse(runtime.service.status()['firmware']['available'])
            with self.assertRaisesRegex(Exception,'USB'): runtime.service.run('firmware')
        with patch('runtime.device_service.scan_ports',return_value=self.port()*2):
            runtime.service.refresh()
            self.assertFalse(runtime.service.status()['firmware']['available'])
            self.assertEqual(len(runtime.service.status()['firmware']['ports']),2)
        with patch('runtime.device_service.scan_ports',side_effect=self.port),patch('runtime.device_service.platformio',side_effect=RuntimeError('Brak PlatformIO')):
            runtime.service.refresh()
            self.assertIn('Brak PlatformIO',runtime.service.status()['firmware']['reason'])
        runtime.service.shutdown()
    def test_disconnect_before_upload_reports_failure(self):
        runtime=Application(connect=lambda:Link())
        scans=iter([self.port(),[]])
        with patch('runtime.device_service.scan_ports',side_effect=lambda:next(scans)),patch('runtime.device_service.platformio',return_value='pio'),patch('runtime.device_service.run_firmware',return_value='ok') as upload:
            with self.assertRaisesRegex(Exception,'odłączony'): runtime.service.run('firmware')
        self.assertEqual(upload.call_count,1)
        self.assertEqual(runtime.service.status()['firmware']['flash'],'failed')
        runtime.service.shutdown()
    def test_flash_success_remains_success_while_ble_retries(self):
        runtime=Application(connect=lambda:(_ for _ in ()).throw(RuntimeError('BLE unavailable')))
        runtime.service.restart_delay=.01; runtime.service.retry_delay=.1
        with patch('runtime.device_service.scan_ports',side_effect=self.port),patch('runtime.device_service.platformio',return_value='pio'),patch('runtime.device_service.run_firmware',return_value='ok'):
            runtime.service.run('firmware')
            deadline=time.monotonic()+2
            while runtime.service.status()['firmware']['ble']!='retrying' and time.monotonic()<deadline: time.sleep(.01)
        status=runtime.service.status()['firmware']
        self.assertEqual(status['flash'],'success')
        self.assertEqual(status['ble'],'retrying')
        self.assertFalse(runtime.real.status()['connected'])
        runtime.service.shutdown()
    def test_inflight_background_connect_finishes_before_upload(self):
        entered=threading.Event(); release=threading.Event(); uploaded=threading.Event()
        old=Link()
        def connect():
            entered.set(); release.wait(2); return old
        runtime=Application(connect=connect)
        runtime.service.restart_delay=1
        thread=threading.Thread(target=runtime.service.connect)
        thread.start(); self.assertTrue(entered.wait(1))
        def upload(*args,**kwargs):
            uploaded.set(); return 'ok'
        errors=[]
        def flash():
            try: runtime.service.run('firmware')
            except Exception as exc: errors.append(exc)
        with patch('runtime.device_service.scan_ports',side_effect=self.port),patch('runtime.device_service.platformio',return_value='pio'),patch('runtime.device_service.run_firmware',side_effect=upload):
            worker=threading.Thread(target=flash); worker.start()
            self.assertFalse(uploaded.wait(.05))
            release.set(); worker.join(2); thread.join(2)
        self.assertFalse(errors)
        self.assertTrue(uploaded.is_set())
        self.assertTrue(old.closed)
        self.assertFalse(runtime.service.connecting)
        runtime.service.shutdown()
