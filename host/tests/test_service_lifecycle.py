"""Deterministic service races and failures; fake links/builds, no physical I/O."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from runtime.application import Application
from runtime.outputs import OutputError
from test_runtime import Link
from service_traces import capture_service_traces


class ServiceLifecycleTests(unittest.TestCase):
    def test_usb_ble_traces_match_frozen_pre_refactoring_behavior(self):
        path = Path(__file__).parent/'fixtures/service-lifecycle-2026-10-27.json'
        self.assertEqual(capture_service_traces(), json.loads(path.read_text()))

    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.stack.enter_context(patch('runtime.device_service.scan_ports', return_value=[
            SimpleNamespace(device='/dev/cu.usbserial-fake', vid=0x10c4)]))
        self.stack.enter_context(patch('runtime.device_service.platformio', return_value='pio'))
        self.app = Application()
        self.addCleanup(self.app.service.shutdown)
        self.app.service.power_off_delay = 0
        self.app.service.restart_delay = 60
        self.link = Link()
        self.link.supports_ota = True
        self.app.real.attach(self.link)

    def start(self, function):
        results, errors = [], []
        def run():
            try:
                results.append(function())
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, results, errors

    def finish(self, thread, errors):
        thread.join(3)
        self.assertFalse(thread.is_alive(), 'service thread did not finish')
        self.assertEqual(errors, [])

    def test_shutdown_during_power_or_attach_ack_never_installs_late_link(self):
        for phase in ('power', 'attach'):
            with self.subTest(phase=phase):
                app = Application()
                self.addCleanup(app.service.shutdown)
                entered, release = threading.Event(), threading.Event()
                replacement = Link()
                original = replacement.power if phase == 'power' else replacement.all_stop_confirmed
                def delayed(*args):
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError('test ACK gate timed out')
                    return original(*args)
                if phase == 'power':
                    replacement.power = delayed
                else:
                    replacement.all_stop_confirmed = delayed
                app.service.connect_fn = lambda: replacement
                thread, results, errors = self.start(app.service.connect)
                try:
                    self.assertTrue(entered.wait(2))
                    app.service.shutdown()
                finally:
                    release.set()
                    self.finish(thread, errors)
                self.assertEqual(results, [False])
                self.assertIsNone(app.real.link)
                self.assertTrue(replacement.closed)
                self.assertFalse(app.service.connecting)
                self.assertNotIn('POWER ON', replacement.sent)

    def test_old_recovery_cannot_overwrite_new_firmware_build_state(self):
        entered, release = threading.Event(), threading.Event()
        build_entered, finish_build = threading.Event(), threading.Event()
        original_state = self.app.service._state
        def delayed_state(**fields):
            if fields.get('generation') == 0:
                entered.set()
                if not release.wait(3):
                    raise RuntimeError('test recovery gate timed out')
            return original_state(**fields)
        def build(_tool, port=None, **_):
            if port is None:
                build_entered.set()
                if not finish_build.wait(3):
                    raise RuntimeError('test build gate timed out')
        self.app.service.restart_delay = 0
        self.app.service._state = delayed_state
        recovery, _, recovery_errors = self.start(lambda: self.app.service._recover(0))
        upload = None
        upload_errors = []
        try:
            self.assertTrue(entered.wait(2))
            self.app.service.restart_delay = 60
            with patch('runtime.device_service.run_firmware', side_effect=build):
                upload, _, upload_errors = self.start(lambda: self.app.service.run('firmware'))
                try:
                    self.assertTrue(build_entered.wait(2))
                    release.set()
                    self.finish(recovery, recovery_errors)
                    self.assertEqual(self.app.service.firmware_state['stage'], 'build')
                    self.assertFalse(any(event.get('ble') == 'verified' for event in self.app.service.events))
                finally:
                    finish_build.set()
                    self.finish(upload, upload_errors)
        finally:
            release.set()
            finish_build.set()
            self.finish(recovery, recovery_errors)
        self.assertEqual(self.app.service.firmware_state['flash'], 'success')

    def test_prepare_callback_failure_releases_reservation_and_attempts_stop(self):
        self.app.service.emit = Mock(side_effect=[RuntimeError('UI callback failed'), None])
        with patch('runtime.device_service.run_firmware') as build:
            with self.assertRaisesRegex(RuntimeError, 'UI callback failed'):
                self.app.service.run('firmware')
        build.assert_not_called()
        self.assertFalse(self.app.service.busy)
        self.assertIsNone(self.app.service.operation)
        self.assertEqual(self.app.player.owner, 'orchestra')
        self.assertEqual(self.app.service.firmware_state['flash'], 'failed')
        self.assertEqual(self.link.sent[-1], 'ALL STOP token')

    def test_permanently_failed_callback_still_attempts_stop_and_releases(self):
        self.app.service.emit = Mock(side_effect=RuntimeError('closed observer'))
        with self.assertRaisesRegex(RuntimeError, 'closed observer'):
            self.app.service.run('firmware')
        self.assertFalse(self.app.service.busy)
        self.assertIsNone(self.app.service.operation)
        self.assertEqual(self.link.sent[-1], 'ALL STOP token')

    def test_ota_callbacks_are_outside_lock_and_cannot_start_music_or_service(self):
        def observe(_):
            self.assertTrue(self.app.service.lock.acquire(blocking=False))
            self.app.service.lock.release()
            self.app.service.status()
            with self.assertRaisesRegex(OutputError, 'zajęty'):
                self.app.service.run('power_status')
        self.app.service.emit = observe
        def transfer(_image, _key, on_progress):
            self.assertIsNone(self.app.real.link)
            self.assertEqual(self.app.player.owner, 'service')
            for action in (lambda: self.app.play('browser'),
                           lambda: self.app.test_laboratory('browser', 'fdd-1'),
                           lambda: self.app.switch_output('VIRTUAL')):
                with self.assertRaisesRegex(ValueError, 'zajęty'):
                    action()
            self.assertFalse(self.app.service.connect())
            on_progress(50)
        self.link.upload_firmware = Mock(side_effect=transfer)
        directory = self.enterContext(tempfile.TemporaryDirectory())
        image = Path(directory)/'firmware.bin'
        image.write_bytes(b'fake image')
        with patch('runtime.device_service.read_key', return_value=b'k'*32), \
             patch('runtime.device_service.image_path', return_value=image), \
             patch('runtime.device_service.run_firmware'):
            self.assertTrue(self.app.service.run('firmware_ble')['ok'])
        self.assertTrue(self.link.closed)
        self.link.upload_firmware.assert_called_once()
        self.assertEqual(self.app.router.mode, 'REAL')
        self.assertFalse(any('PLAY' in command or 'HOME' in command or command == 'POWER ON'
                             for command in self.link.sent))

    def test_closed_service_refuses_new_work_without_commands(self):
        self.app.service.shutdown()
        before = self.link.sent.copy()
        with self.assertRaisesRegex(OutputError, 'zamknięty'):
            self.app.service.run('power_status')
        self.assertEqual(self.link.sent, before)
        self.assertFalse(self.app.service.connect())

    def test_absent_or_ambiguous_usb_port_never_starts_build(self):
        for ports in ([], [SimpleNamespace(device='/dev/cu.usbserial-a', vid=0x10c4),
                           SimpleNamespace(device='/dev/cu.usbserial-b', vid=0x10c4)]):
            with self.subTest(port_count=len(ports)):
                app = Application()
                self.addCleanup(app.service.shutdown)
                app.service.power_off_delay = 0
                app.service.restart_delay = 60
                link = Link()
                app.real.attach(link)
                with patch('runtime.device_service.scan_ports', return_value=ports), \
                     patch('runtime.device_service.run_firmware') as build:
                    with self.assertRaisesRegex(OutputError, 'dokładnie jeden port'):
                        app.service.run('firmware')
                build.assert_not_called()
                self.assertIn('POWER OFF', link.sent)
                self.assertTrue(link.closed)
                self.assertFalse(app.service.busy)

    def test_recovery_waits_for_non_firmware_operation_without_abandoning_generation(self):
        parked, release = threading.Event(), threading.Event()
        service = self.app.service
        service.restart_delay = 0
        service.firmware_state.update(flash='success', ble='waiting')
        with service.lock:
            service.busy = True

        def wait(delay):
            if delay == 0:
                return False
            parked.set()
            if not release.wait(3):
                raise RuntimeError('test operation gate timed out')
            return service._closed.is_set()

        with patch.object(service._closed, 'wait', side_effect=wait):
            thread, _, errors = self.start(lambda: service._recover(0))
            try:
                self.assertTrue(parked.wait(2))
                self.assertEqual(service.firmware_state['ble'], 'waiting')
                with service.lock:
                    service.busy = False
            finally:
                release.set()
                self.finish(thread, errors)
        self.assertEqual(service.firmware_state['ble'], 'verified')
        self.assertEqual(service.firmware_state['flash'], 'success')
