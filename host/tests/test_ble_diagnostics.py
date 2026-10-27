"""Host clocks can identify the stage of a delay, without a BLE device."""
import unittest
from ble_diagnostics import WriteTrace, WriteHistory, LoopTiming


class BleTimingTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.
        self.clock = lambda: self.now

    def test_dispatch_lock_and_gatt_delays_are_distinct(self):
        trace = WriteTrace(b'PING\n', clock=self.clock)
        self.now += .020; trace.mark('ble_loop')
        self.now += .030; trace.mark('lock_acquired')
        trace.mark('gatt_started')
        self.now += .040; trace.fragment_finished()
        trace.mark('gatt_started')
        self.now += .010; trace.fragment_finished()
        trace.mark('completed')
        value = trace.snapshot()
        self.assertEqual(value['bleLoopDelayMs'], 20)
        self.assertEqual(value['lockWaitMs'], 30)
        self.assertEqual(value['gattTotalMs'], 50)
        self.assertEqual(value['gattMaxMs'], 40)
        self.assertEqual(value['fragments'], 2)
        self.assertEqual(value['ageMs'], 100)
        self.now += 1
        self.assertEqual(trace.snapshot()['ageMs'], 100)

    def test_pending_gatt_is_visible_before_timeout(self):
        trace = WriteTrace(b'PING\n', clock=self.clock)
        trace.mark('gatt_started'); self.now += .253
        value = trace.snapshot()
        self.assertEqual(value['currentGattMs'], 253)
        self.assertEqual(value['fragments'], 0)
        self.assertIsNone(value['workerQueueMs'])

    def test_executor_wait_and_observer_resume_are_separate(self):
        trace = WriteTrace(b'PING\n', clock=self.clock)
        trace.mark('dispatch'); self.now += .180
        trace.mark('worker_started'); self.now += .010
        trace.mark('worker_finished'); self.now += .090
        trace.mark('completed')
        value = trace.snapshot()
        self.assertEqual(value['workerQueueMs'], 180)
        self.assertEqual(value['gatewayResumeMs'], 90)
        self.assertEqual(value['ageMs'], 280)

    def test_bounded_history_and_commands_without_unbounded_payload(self):
        history = WriteHistory(capacity=2)
        for _ in range(5):
            trace = history.add((b'PING\n'*100), clock=self.clock)
            trace.mark('completed')
        value = history.snapshot()
        self.assertEqual(value['sampleCount'], 2)
        self.assertEqual(len(value['recent']), 2)
        self.assertEqual(len(value['recent'][0]['commands']), 8)
        self.assertEqual(value['recent'][0]['commandCount'], 100)
        self.assertEqual(value['maxMs'], 0)

    def test_failure_is_not_counted_as_confirmed_completion(self):
        history = WriteHistory()
        trace = history.add(b'PING\n', clock=self.clock)
        trace.fail(OSError('write failed'))
        value = history.snapshot()
        self.assertEqual(value['sampleCount'], 0)
        self.assertFalse(value['active'])
        self.assertIn('OSError', value['recent'][0]['error'])

    def test_ble_loop_stall_visible_even_before_it_can_run_again(self):
        timing = LoopTiming(clock=self.clock)
        self.now += .020; timing.tick()
        self.now += .273
        self.assertEqual(timing.snapshot()['currentlyOverdueMs'], 253)
        timing.tick()
        self.assertEqual(timing.snapshot()['maxLagMs'], 253)
        self.now += .020; timing.tick()
        self.assertEqual(timing.snapshot()['lastLagMs'], 0)
        self.assertEqual(timing.snapshot()['maxLagMs'], 253)
