"""MIDI-clock invariants using the production scheduler and a slow fake link."""
import unittest
from unittest.mock import patch
from playback.engine import PlaybackState
from playback.timeline import Command, Timeline
from playback.engine import PlaybackEngine

class Clock:
    def __init__(self): self.now = 0.
    def monotonic(self): return self.now

class Transport:
    protocol_version = 2
    controller_status = {}
    def __init__(self, clock, cost=.020):
        self.clock, self.cost, self.writes = clock, cost, []
    def send(self, text):
        self.writes.append((self.clock.now, text))
        self.clock.now += self.cost

def engine_for(timeline, transport, trace):
    engine = PlaybackEngine(keepalive=1000)
    engine._timeline, engine._transport = timeline, transport
    engine._hardware.connected = engine._hardware.homed = True
    engine._hardware_active = True
    engine._state = PlaybackState.PLAYING
    engine._on_command = lambda c: trace.append(c)
    return engine

class PlaybackDriftTests(unittest.TestCase):
    def run_timeline(self, commands, cost=.020):
        clock = Clock()
        transport = Transport(clock, cost)
        engine = engine_for(Timeline.from_commands(commands), transport, [])
        engine._origin = 0.
        with patch('playback.engine.time.monotonic', clock.monotonic):
            while engine._state == PlaybackState.PLAYING:
                delay = engine._plan_locked()
                if delay is not None:
                    clock.now += max(delay, .000001)
        return engine, clock, transport

    def test_60_second_overload_never_stretches_to_75_seconds(self):
        commands = [Command(i * 60 / 3750, 'play', 220, lane='fdd:1') for i in range(3750)]
        commands += [Command(60, 'stop', lane='fdd:1')]
        engine, clock, transport = self.run_timeline(commands)
        self.assertLessEqual(clock.now, 60.061)
        self.assertGreaterEqual(clock.now, 60)
        self.assertGreater(engine._late_commands, 0)
        self.assertEqual(engine._origin, 0)
        self.assertEqual(transport.writes[-1][1], 'ALL STOP')
        self.assertTrue(all(t < 60 for t, text in transport.writes if 'PLAY' in text))

    def test_simultaneous_group_does_not_shift_later_deadline(self):
        commands = [Command(10, 'play', 220, lane=f'fdd:{i}') for i in range(1, 5)]
        commands += [Command(10, 'play', 250, lane='sled:1'), Command(10, 'drum_on', 330, lane='drum:1'),
                     Command(11, 'play', 440, lane='fdd:1'), Command(12, 'stop', lane='fdd:1')]
        engine, clock, transport = self.run_timeline(commands)
        later = [t for t, text in transport.writes if text == 'FDD 1 PLAY 440.00']
        self.assertEqual(later, [11])
        self.assertLessEqual(clock.now, 12.041)
        self.assertEqual(engine._origin, 0)

    def test_expired_stops_are_delivered_and_catchup_releases_lock(self):
        clock = Clock(); clock.now = 10
        transport = Transport(clock)
        engine = engine_for(Timeline.from_commands([
            Command(1, 'play', 220, lane='fdd:1'),
            *[Command(2, 'stop', lane='fdd:1') for _ in range(10)],
            Command(20, 'stop', lane='fdd:1')]), transport, [])
        engine._origin = 0.
        with patch('playback.engine.time.monotonic', clock.monotonic):
            engine._plan_locked()
        self.assertEqual(engine._late_commands, 1)
        self.assertEqual(len(transport.writes), 3)
        self.assertTrue(all(text == 'FDD 1 STOP' for _, text in transport.writes))
        self.assertLessEqual(clock.now, 10.061)

    def test_under_capacity_preserves_every_note(self):
        commands = [Command(i, 'play', 220, lane='fdd:1') for i in range(60)] + [Command(60, 'stop', lane='fdd:1')]
        engine, clock, transport = self.run_timeline(commands)
        self.assertEqual(engine._late_commands, 0)
        self.assertEqual(sum('PLAY' in text for _, text in transport.writes), 60)
        self.assertLessEqual(clock.now, 60.041)

class BatchTransport(Transport):
    is_ble = True
    def __init__(self, clock, cost=.020):
        super().__init__(clock, cost)
        self.batches = []
    def send_batch(self, lines):
        self.batches.append((self.clock.now, list(lines)))
        self.writes.extend((self.clock.now, text) for text in lines)
        self.clock.now += self.cost

class ProductionBatchTests(unittest.TestCase):
    def prepare(self, commands, position=0):
        clock = Clock(); clock.now = position
        transport = BatchTransport(clock)
        engine = engine_for(Timeline.from_commands(commands), transport, [])
        engine._origin = 0
        return engine, clock, transport

    def tick(self, engine, clock):
        with patch('playback.engine.time.monotonic', clock.monotonic):
            return engine._plan_locked()

    def test_six_simultaneous_devices_one_batch_amp_before_freq(self):
        commands = [Command(10, 'play', 220, lane=f'fdd:{i}') for i in range(1, 5)]
        commands += [Command(10, 'play', 250, lane='sled:1'), Command(10, 'drum_on', 330, lane='drum:1'), Command(11, 'stop', lane='fdd:1')]
        engine, clock, transport = self.prepare(commands, 10)
        self.tick(engine, clock)
        self.assertEqual(len(transport.batches), 1)
        self.assertEqual(transport.batches[0][1], [*(f'FDD {i} PLAY 220.00' for i in range(1, 5)), 'SLED 1 PLAY 250.00', 'VHS AMP 38', 'VHS FREQ 330.00'])
        self.assertAlmostEqual(clock.now, 10.02)
        self.assertEqual(engine._ble_commands, 7)

    def test_two_second_backlog_collapses_to_current_note(self):
        commands = [Command(t, 'play', hz, lane='fdd:1') for t, hz in [(0, 220), (.05, 261), (.1, 329)]]
        commands += [Command(3, 'stop', lane='fdd:1')]
        engine, clock, transport = self.prepare(commands, 2)
        self.tick(engine, clock)
        self.assertEqual([text for _, text in transport.writes], ['FDD 1 PLAY 329.00'])
        self.assertEqual(engine._late_commands, 2)
        self.assertEqual(engine._collapsed_events, 2)
        self.assertEqual(engine._late_reasons['LATE_SUPERSEDED'], 2)
        self.assertEqual(engine._origin, 0)

    def test_expired_interval_sends_stop_not_old_notes(self):
        engine, clock, transport = self.prepare([
            Command(0, 'play', 220, lane='fdd:1'), Command(1, 'stop', lane='fdd:1'),
            Command(4, 'stop', lane='sled:1')], 2)
        self.tick(engine, clock)
        self.assertEqual(transport.writes, [(2, 'FDD 1 STOP')])
        self.assertEqual(engine._late_reasons, {'LATE_EXPIRED': 1})

    def test_deadline_discards_backlog_and_sends_failsafe(self):
        engine, clock, transport = self.prepare([
            Command(0, 'play', 220, lane='fdd:1'), Command(1, 'stop', lane='fdd:1')], 2)
        self.tick(engine, clock)
        self.assertEqual([text for _, text in transport.writes], ['ALL STOP'])
        self.assertEqual(engine._state, PlaybackState.STOPPED)
        self.assertEqual(engine._position_base, 1)
        self.assertEqual(engine._late_reasons['LATE_EXPIRED'], 1)

    def test_old_hdd_tray_oneshots_never_burst(self):
        commands = [Command(t, 'hit', lane='hdd:1') for t in [0, .1, .2]]
        commands += [Command(.25, 'tray_pulse', 20, lane='tray:1'), Command(4, 'stop', lane='hdd:1')]
        engine, clock, transport = self.prepare(commands, 2)
        self.tick(engine, clock)
        self.assertEqual(transport.writes, [])
        self.assertEqual(engine._late_reasons, {'LATE_EXPIRED': 4})

    def test_separate_timestamps_never_dispatched_early(self):
        engine, clock, transport = self.prepare([
            Command(1, 'play', 220, lane='fdd:1'), Command(1.001, 'play', 330, lane='fdd:2'),
            Command(2, 'stop', lane='fdd:1')], 1)
        self.tick(engine, clock)
        self.assertEqual(len(transport.batches), 2)
        self.assertGreaterEqual(transport.batches[1][0], 1.001)

    def test_stop_precedes_play_in_batch_and_failure_pauses(self):
        engine, clock, transport = self.prepare([
            Command(1, 'stop', lane='fdd:1'), Command(1, 'play', 220, lane='fdd:1'),
            Command(2, 'stop', lane='fdd:1')], 1)
        self.tick(engine, clock)
        self.assertEqual(transport.batches[0][1], ['FDD 1 STOP', 'FDD 1 PLAY 220.00'])
        engine, clock, transport = self.prepare([Command(1, 'play', 220, lane='fdd:1'), Command(2, 'stop', lane='fdd:1')], 1)
        transport.send_batch = lambda _: (_ for _ in ()).throw(OSError('radio lost'))
        self.tick(engine, clock)
        self.assertEqual(engine._state, PlaybackState.PAUSED)
        self.assertIn('radio lost', engine._hardware.error)
        self.assertEqual(transport.writes[-1][1], 'ALL STOP')

    def test_batch_60_second_saturation_preserves_timeline_and_deadline(self):
        commands = [Command(i*60/3750, 'play', 220, lane='fdd:1') for i in range(3750)] + [Command(60, 'stop', lane='fdd:1')]
        engine, clock, transport = self.prepare(commands)
        original = tuple(engine._timeline.commands)
        with patch('playback.engine.time.monotonic', clock.monotonic):
            while engine._state == PlaybackState.PLAYING:
                delay = engine._plan_locked()
                if delay is not None: clock.now += max(delay, .000001)
        self.assertEqual(engine._timeline.commands, original)
        self.assertAlmostEqual(engine._timeline.duration, 60)
        self.assertLess(clock.now, 60.061)
        self.assertEqual(transport.writes[-1][1], 'ALL STOP')
        self.assertGreater(engine._late_reasons['LATE_SUPERSEDED'], 0)
        self.assertLess(engine._max_dispatch_lag, .021)
