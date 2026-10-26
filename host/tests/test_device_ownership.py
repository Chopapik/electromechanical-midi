"""Device state ownership and service lock order; fake links, no hardware."""
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime.application import Application
from runtime.outputs import OutputError
from test_runtime import Link
from test_orchestra_link import ProtocolTests


class DeviceOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.app=Application()
        self.addCleanup(self.app.service.shutdown)
        self.app.service.power_off_delay=0
        self.link=Link()
        self.app.real.attach(self.link)

    def test_confirmed_off_is_owned_by_output_and_invalidates_fdd_reference(self):
        real=self.app.real
        real.active=True;real.unknown=True;real.error='previous error'
        real.active_speakers.add('vhs-1');real.speaker_frequencies['vhs-1']=440
        self.assertEqual(real.power('OFF'),'OFF')
        self.assertFalse(real.active or real.unknown)
        self.assertIsNone(real.error)
        self.assertFalse(real.active_speakers or real.speaker_frequencies)
        self.assertTrue(all(state['homed']=='0' and state['homing']=='0' and state['playing']=='0'
                            for key,state in self.link.device_status.items() if key.startswith('FDD:')))
        self.assertEqual(real.power_state(),'OFF')
        self.assertNotIn('POWER ON',self.link.sent)

    def test_missing_power_ack_marks_logical_state_unknown(self):
        for outcome in ('wrong_ack','transport_failure'):
            with self.subTest(outcome=outcome):
                self.link.controller_status['atx']='ON'
                with patch.object(self.link,'power',return_value='ON',
                                  side_effect=OSError('BLE lost') if outcome=='transport_failure' else None):
                    with self.assertRaises(OutputError):self.app.real.power('OFF')
                self.assertEqual(self.app.real.power_state(),'UNKNOWN')

    def test_detach_does_not_falsely_clear_unknown_or_restore_power(self):
        real=self.app.real;real.active=True;real.unknown=True;real.configured=True
        real.detach()
        self.assertTrue(self.link.closed)
        self.assertIsNone(real.link)
        self.assertFalse(real.configured)
        self.assertTrue(real.unknown)
        self.assertEqual(real.power_state(),'UNKNOWN')
        self.assertNotIn('POWER ON',self.link.sent)

    def test_link_state_operations_invalidate_only_intended_fields(self):
        link=ProtocolTests().link()
        link.controller_status={'atx':'ON','ready':'1'}
        link.device_status={'FDD:1':{'homed':'1','homing':'1','playing':'1','track0':'1'},
                            'SLED:1':{'playing':'1'}}
        link.invalidate_power_state();link.invalidate_fdd_reference()
        self.assertEqual(link.controller_status,{'atx':'UNKNOWN','ready':'1'})
        self.assertEqual(link.device_status['FDD:1'],
                         {'homed':'0','homing':'0','playing':'0','track0':'1'})
        self.assertEqual(link.device_status['SLED:1'],{'playing':'1'})

    def test_connect_waits_for_player_without_holding_service_lock(self):
        self.app.real.detach()
        waiting=threading.Event();release=threading.Event();real_lock=threading.RLock()
        class Gate:
            def __enter__(self):
                if threading.current_thread().name=='connect-under-test':
                    waiting.set()
                    if not release.wait(2):raise RuntimeError('test gate timeout')
                real_lock.acquire();return self
            def __exit__(self,*_):real_lock.release()
        self.app.player.lock=Gate()
        replacement=Link();self.app.service.connect_fn=lambda:replacement
        thread=threading.Thread(target=self.app.service.connect,name='connect-under-test',daemon=True)
        thread.start()
        try:
            self.assertTrue(waiting.wait(1))
            acquired=self.app.service.lock.acquire(timeout=.1)
            if acquired:self.app.service.lock.release()
            self.assertTrue(acquired,'connect held service.lock while waiting for player.lock')
            with self.assertRaisesRegex(OutputError,'zajęty'):
                self.app.service.run('power_status')
        finally:
            release.set();thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertIs(self.app.real.link,replacement)

    def test_connect_does_not_hold_service_lock_while_waiting_for_ack(self):
        self.app.real.detach()
        replacement=Link();original=replacement.power
        def power(action):
            acquired=self.app.service.lock.acquire(blocking=False)
            if acquired:self.app.service.lock.release()
            self.assertTrue(acquired,'POWER ACK wait must not hold service.lock')
            return original(action)
        replacement.power=power;self.app.service.connect_fn=lambda:replacement
        self.assertTrue(self.app.service.connect())

    def test_disconnect_lease_does_not_release_a_new_browser_owner(self):
        self.app.virtual.claim_owner('old')
        self.app.virtual.active=True
        def new_session(_):
            self.app.virtual.claim_owner('new')
            self.app.virtual.active=True
        with patch.object(self.app.player,'stop'),patch('runtime.application.time.sleep',side_effect=new_session):
            self.app.disconnect('old')
        self.assertEqual(self.app.virtual.owner,'new')
        self.assertTrue(self.app.virtual.active)
