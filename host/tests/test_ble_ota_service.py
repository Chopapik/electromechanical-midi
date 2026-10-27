"""Shared STOP/OFF barrier, exclusivity and no USB dependency for BLE OTA."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from runtime.application import Application
from test_firmware_flow import Link
from fastapi.testclient import TestClient
from web.server import create_app


class OtaServiceTests(unittest.TestCase):
    def test_websocket_ble_upload_requires_matching_local_origin(self):
        app,link=self.app()
        with tempfile.TemporaryDirectory() as tmp,TestClient(create_app(midi_dir=tmp,runtime=app,connect_on_start=False),base_url='http://localhost',headers={'Host':'localhost'}) as client:
            with patch.object(app.service,'run') as run:
                with client.websocket_connect('/ws',headers={'Origin':'https://evil.example'}) as ws:
                    ws.send_json({'action':'service','operation':'firmware_ble','requestId':'ota'})
                    while True:
                        message=ws.receive_json()
                        if message.get('requestId')=='ota':break
                self.assertEqual(message['type'],'error');run.assert_not_called()
    def app(self):
        app=Application();app.service.power_off_delay=0;app.service.restart_delay=60
        self.addCleanup(app.service.shutdown)
        link=Link();link.supports_ota=True;app.real.attach(link)
        return app,link

    def test_ble_upload_uses_shared_barrier_and_blocks_playback_without_usb(self):
        app,link=self.app();order=[]
        def power(action):order.append('POWER '+action);return 'OFF'
        link.power=Mock(side_effect=power)
        def transfer(image,key,on_progress):
            self.assertEqual(image,b'firmware');self.assertEqual(key,b'k'*32)
            self.assertTrue(app.service.busy);self.assertIsNone(app.real.link)
            self.assertEqual(app.player.owner,'service');self.assertEqual(app.player.state,'stopped')
            self.assertFalse(link.closed)
            with self.assertRaisesRegex(ValueError,'zajęty'):app.play('browser')
            with self.assertRaisesRegex(Exception,'zajęty'):app.service.run('power_on',confirmed=True)
            order.append('transfer');on_progress(50);on_progress(100)
        link.upload_firmware=Mock(side_effect=transfer)
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'firmware.bin';binary.write_bytes(b'firmware')
            with patch('runtime.device_service.read_key',return_value=b'k'*32),patch('runtime.device_service.image_path',return_value=binary),patch('runtime.device_service.platformio',return_value='pio'),patch('runtime.device_service.run_firmware',side_effect=lambda *a,**k:order.append('build')) as build,patch('runtime.device_service.scan_ports',side_effect=AssertionError('BLE must not require USB')):
                result=app.service.run('firmware_ble')
        self.assertEqual(result['transport'],'BLE');self.assertEqual(order,['POWER OFF','build','transfer'])
        self.assertEqual(build.call_count,1);self.assertTrue(link.closed)
        self.assertEqual(app.service.firmware_state['flash'],'success')
        self.assertEqual(app.service.firmware_state['transport'],'BLE')
        self.assertTrue(any(e.get('progress')==50 for e in app.service.events))
        self.assertFalse(app.service.busy)

    def test_missing_stop_or_off_ack_prevents_build_and_transfer(self):
        for failure in ('stop','off'):
            with self.subTest(failure=failure):
                app,link=self.app();link.upload_firmware=Mock()
                if failure=='stop':link.all_stop_confirmed=Mock(return_value=False)
                else:link.power=Mock(side_effect=RuntimeError('Missing OFF ACK'))
                with patch('runtime.device_service.read_key',return_value=b'k'*32),patch('runtime.device_service.run_firmware') as build:
                    with self.assertRaises(Exception):app.service.run('firmware_ble')
                    build.assert_not_called();link.upload_firmware.assert_not_called()
                self.assertEqual(app.service.firmware_state['flash'],'failed')

    def test_old_firmware_or_missing_private_key_does_not_build_or_generate_a_key(self):
        for missing in ('capability','key'):
            app,link=self.app();link.supports_ota=missing!='capability';link.upload_firmware=Mock()
            with patch('runtime.device_service.read_key',side_effect=FileNotFoundError()),patch('runtime.device_service.run_firmware') as build:
                with self.assertRaisesRegex(Exception,'USB'):app.service.run('firmware_ble')
                build.assert_not_called();link.upload_firmware.assert_not_called()

    def test_transfer_failure_closes_session_without_success_or_automatic_retry(self):
        app,link=self.app();link.upload_firmware=Mock(side_effect=RuntimeError('BLE OTA disconnected'))
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'firmware.bin';binary.write_bytes(b'firmware')
            with patch('runtime.device_service.read_key',return_value=b'k'*32),patch('runtime.device_service.image_path',return_value=binary),patch('runtime.device_service.platformio',return_value='pio'),patch('runtime.device_service.run_firmware'):
                with self.assertRaisesRegex(RuntimeError,'disconnected'):app.service.run('firmware_ble')
        self.assertTrue(link.closed);link.upload_firmware.assert_called_once()
        self.assertEqual(app.service.firmware_state['flash'],'failed')
        self.assertFalse(any(e.get('flash')=='success' for e in app.service.events))

    def test_status_explains_initial_usb_install_and_private_key_requirement(self):
        app,link=self.app()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'key'
            with patch('runtime.device_service.key_path',return_value=path):
                self.assertFalse(app.service.status()['firmware']['bleAvailable'])
                path.write_bytes(b'k'*32)
                self.assertTrue(app.service.status()['firmware']['bleAvailable'])
                link.supports_ota=False
                self.assertIn('USB',app.service.status()['firmware']['bleReason'])
