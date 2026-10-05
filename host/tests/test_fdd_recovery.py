"""Serial connectivity and FDD position are independent states."""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playback.engine import PlaybackEngine, PlaybackState, EngineError
from test_engine import FakeTransport, write_midi
from floppy_link import FloppyLink, SerialLinkError

class PositionTransport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.finish = threading.Event()
        self.finish.set()
        self.success = True
        self.entered = threading.Event()
    def wait_ready(self, **kwargs):
        return True
    def wait_boot(self, **kwargs):
        self.send('BOOT_HANDSHAKE')
        return True
    def wait_homed(self, **kwargs):
        self.entered.set()
        self.finish.wait(2)
        self.send('STATUS')
        return self.success

class FddRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.transport = PositionTransport()
        self.engine = PlaybackEngine(connect_fn=lambda port: self.transport, wait_ready=True)
        self.addCleanup(self.engine.shutdown)
        self.assertTrue(self.engine.connect())
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.engine.load_file(write_midi(Path(tmp.name)/'song.mid', [(0, 10, 60)]))
    def feed(self, line):
        self.transport.queue_line(line)
        with self.engine._lock:
            self.engine._poll_lines_locked()
    def wait_recovery(self):
        deadline=time.monotonic()+3
        while self.engine.snapshot()['hardware']['connecting'] and time.monotonic()<deadline:
            time.sleep(.005)
        return self.engine.snapshot()['hardware']
    def test_connect_handshake_then_explicit_home(self):
        commands=self.transport.raw_texts()
        self.assertLess(commands.index('BOOT_HANDSHAKE'), commands.index('HOME'))
        self.assertTrue(self.engine.snapshot()['hardware']['ready'])
    def test_position_errors_preserve_serial_and_recover_without_connect(self):
        for error in ('ERR NOT_HOMED', 'ERR POS_LOST'):
            with self.subTest(error=error), patch.object(self.engine, 'connect') as connect:
                self.transport.finish.clear()
                self.feed(error)
                state=self.engine.snapshot()['hardware']
                self.assertTrue(state['connected'])
                self.assertFalse(state['homed'])
                self.assertTrue(state['connecting'])
                self.transport.finish.set()
                self.assertTrue(self.wait_recovery()['ready'])
                connect.assert_not_called()
    def test_home_failed_keeps_serial_and_blocks_play_until_retry(self):
        self.feed('ERR HOME_FAILED')
        state=self.engine.snapshot()['hardware']
        self.assertTrue(state['connected'])
        self.assertFalse(state['homed'])
        self.assertEqual(state['fddStatus'], 'error')
        with self.assertRaises(EngineError): self.engine.play()
        self.assertTrue(self.engine.home())
        self.assertTrue(self.engine.snapshot()['hardware']['ready'])
    def test_host_timeout_pauses_without_losing_homing_or_serial(self):
        self.engine.play()
        self.feed('ERR HOST_TIMEOUT')
        state=self.engine.snapshot()['hardware']
        self.assertTrue(state['connected'])
        self.assertTrue(state['homed'])
        self.assertEqual(self.engine.state, PlaybackState.PAUSED)
    def test_position_resync_is_diagnostic_and_keeps_playing(self):
        self.engine.play()
        with patch.object(self.engine, 'home') as home, patch.object(self.engine, 'connect') as connect:
            self.feed('POSITION_RESYNC old=19 new=0 dir=TOWARD_TRACK0 hz=398.00')
            self.assertEqual(self.engine.state, PlaybackState.PLAYING)
            state=self.engine.snapshot()['hardware']
            self.assertTrue(state['connected'])
            self.assertTrue(state['homed'])
            self.assertTrue(state['ready'])
            self.assertEqual(state['positionResyncs'], 1)
            self.assertIn('old=19', state['lastPositionResync'])
            home.assert_not_called()
            connect.assert_not_called()
    def test_stuck_track0_stays_connected_and_requires_retry_home(self):
        self.engine.play()
        self.feed('ERR TRACK0_STUCK')
        state=self.engine.snapshot()['hardware']
        self.assertTrue(state['connected'])
        self.assertFalse(state['homed'])
        self.assertEqual(state['fddStatus'], 'error')
        self.assertEqual(self.engine.state, PlaybackState.PAUSED)
    def test_real_read_exception_disconnects(self):
        with patch.object(self.transport, 'poll_lines', side_effect=OSError('USB gone')):
            with self.engine._lock: self.engine._poll_lines_locked()
        self.assertFalse(self.engine.snapshot()['hardware']['connected'])
    def test_real_write_exception_disconnects(self):
        with patch.object(self.transport, 'send', side_effect=OSError('USB gone')):
            with self.engine._lock: self.engine._send_raw_locked('PING')
        self.assertFalse(self.engine.snapshot()['hardware']['connected'])
    def test_firmware_upload_handshakes_then_homes(self):
        from firmware import flash_engine
        before=len(self.transport.raw_texts())
        with patch('firmware.run_firmware', return_value='SUCCESS'), patch('firmware.wait_upload_port',return_value='/dev/uno'):
            result=flash_engine(self.engine, 'pio', '/dev/uno')
        commands=self.transport.raw_texts()[before:]
        self.assertLess(commands.index('BOOT_HANDSHAKE'),commands.index('HOME'))
        self.assertTrue(result['ready'])
        self.assertTrue(self.engine.snapshot()['hardware']['homed'])
    def test_play_waits_for_homing(self):
        self.transport.finish.clear()
        self.engine._hardware.homed=False
        before=len(self.transport.raw_texts())
        self.engine.play()
        self.assertNotEqual(self.engine.state, PlaybackState.PLAYING)
        self.assertTrue(self.engine.snapshot()['hardware']['pendingPlay'])
        self.assertFalse(any(c.startswith('PLAY') for c in self.transport.raw_texts()[before:]))
        self.transport.finish.set()
        self.wait_recovery()
        deadline=time.monotonic()+1
        while self.engine.state != PlaybackState.PLAYING and time.monotonic()<deadline: time.sleep(.005)
        self.assertEqual(self.engine.state, PlaybackState.PLAYING)
    def test_reset_ready_recovers_but_does_not_autoresume(self):
        self.engine.play()
        self.feed('READY')
        self.assertTrue(self.wait_recovery()['ready'])
        self.assertEqual(self.engine.state, PlaybackState.PAUSED)
    def test_failed_auto_home_keeps_connected(self):
        self.transport.success=False
        self.feed('ERR POS_LOST')
        state=self.wait_recovery()
        self.assertTrue(state['connected'])
        self.assertFalse(state['ready'])
        self.assertEqual(state['fddStatus'], 'error')
    def test_ready_alone_is_not_position_confirmation(self):
        link=FloppyLink.__new__(FloppyLink)
        with patch.object(link,'wait_boot',return_value=True), patch.object(link,'send') as send, patch.object(link,'wait_for',return_value='STATUS homed=0'):
            self.assertFalse(link.wait_homed())
            send.assert_called_once_with('STATUS')
    def test_dispatch_never_sends_play_with_known_unknown_position(self):
        self.transport.finish.clear()
        self.engine._hardware.homed=False
        before=len(self.transport.raw_texts())
        command=next(c for c in self.engine._timeline.commands if c.kind=='play')
        with self.engine._lock:
            self.assertFalse(self.engine._send_locked(command))
        self.assertFalse(any(c.startswith('PLAY') for c in self.transport.raw_texts()[before:]))
        self.transport.finish.set()
        self.assertTrue(self.wait_recovery()['ready'])
    def test_protocol_home_failed_is_not_serial_exception(self):
        link=FloppyLink.__new__(FloppyLink)
        with patch.object(link,'wait_ready',side_effect=SerialLinkError('Arduino zgloszil blad: ERR HOME_FAILED')):
            self.assertFalse(link.wait_boot())
