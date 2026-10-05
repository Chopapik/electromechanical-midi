import subprocess
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firmware import flash_engine, run_firmware, PROJECT


class FirmwareTest(unittest.TestCase):
    def setUp(self):
        port_wait = patch('firmware.wait_upload_port', side_effect=lambda port: port)
        port_wait.start()
        self.addCleanup(port_wait.stop)

    def test_endpoint_calls_fixed_uploader_and_reports_failure(self):
        from fastapi.testclient import TestClient
        from playback.engine import PlaybackEngine
        from web.server import create_app
        with tempfile.TemporaryDirectory() as directory:
            engine = PlaybackEngine()
            app = create_app(midi_dir=Path(directory), engine=engine, connect_on_start=False)
            with TestClient(app) as client, patch('web.server.platformio', return_value='pio'), \
                    patch('floppy_link.resolve_port', return_value=Mock(device='/dev/uno')), \
                    patch('web.server.flash_engine', return_value={'uploaded': True, 'ready': True}) as flash:
                response = client.post('/api/firmware/upload')
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['ready'])
                flash.assert_called_once_with(engine, 'pio', '/dev/uno')
                flash.side_effect = RuntimeError('upload failed')
                self.assertEqual(client.post('/api/firmware/upload').status_code, 500)
                flash.side_effect = None
                self.assertEqual(client.post('/api/firmware/upload').status_code, 200)

    def test_fixed_uno_project_and_explicit_port(self):
        with patch('firmware.subprocess.run', return_value=Mock(returncode=0, stdout='ok')) as run:
            run_firmware('/tool/pio', '/dev/uno')
        self.assertEqual(run.call_args.args[0], ['/tool/pio', 'run', '-d', str(PROJECT),
                         '-e', 'uno', '--target', 'upload', '--upload-port', '/dev/uno'])

    def test_upload_releases_port_and_reconnects(self):
        calls = []
        engine = Mock()
        for method in ('stop', 'disconnect', 'connect'):
            getattr(engine, method).side_effect = lambda *args, m=method: calls.append(m) or True
        def run(tool, port=None):
            calls.append('upload' if port else 'build')
            return 'ok'
        with patch('firmware.run_firmware', side_effect=run):
            self.assertTrue(flash_engine(engine, 'pio', '/dev/uno')['ready'])
        self.assertEqual(calls, ['build', 'stop', 'disconnect', 'upload', 'connect'])

    def test_failed_build_does_not_disconnect(self):
        engine = Mock()
        with patch('firmware.run_firmware', side_effect=RuntimeError('build failed')):
            with self.assertRaises(RuntimeError):
                flash_engine(engine, 'pio', '/dev/uno')
        engine.disconnect.assert_not_called()

    def test_failed_flash_still_reconnects(self):
        engine = Mock()
        with patch('firmware.run_firmware', side_effect=['built', RuntimeError('flash failed')]):
            with self.assertRaises(RuntimeError):
                flash_engine(engine, 'pio', '/dev/uno')
        engine.connect.assert_called_once_with('/dev/uno')

    def test_timeout_reported(self):
        with patch('firmware.subprocess.run', side_effect=subprocess.TimeoutExpired('pio', 180)):
            with self.assertRaisesRegex(RuntimeError, '180 s'):
                run_firmware('pio')
