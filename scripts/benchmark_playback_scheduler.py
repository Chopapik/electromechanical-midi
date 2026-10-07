#!/usr/bin/env python3
"""Production scheduler benchmark, virtual monotonic clock, no hardware."""
import json
from pathlib import Path
from unittest.mock import patch
from audit_mechanical_drift import Clock, Transport, engine_for, Timeline, Command, PlaybackState, ROOT

class BatchTransport(Transport):
    is_ble = True
    def __init__(self, clock):
        super().__init__(clock)
        self.batches = []
    def send_batch(self, lines):
        self.batches.append((self.clock.now, list(lines)))
        self.writes.extend((self.clock.now, text) for text in lines)
        self.clock.now += self.cost

def run(commands, batching=True, initial_position=0.):
    clock = Clock(); clock.now = initial_position
    transport = BatchTransport(clock) if batching else Transport(clock)
    engine = engine_for(Timeline.from_commands(commands), transport, [])
    engine._origin = 0
    with patch('playback.engine.time.monotonic', clock.monotonic):
        while engine._state == PlaybackState.PLAYING:
            delay = engine._plan_locked()
            if delay is not None: clock.now += max(delay, .000001)
    return {'timelineSeconds': engine._timeline.duration, 'elapsedSeconds': clock.now,
            'maxSchedulerLagMs': engine._max_dispatch_lag*1000,
            'droppedLateEvents': engine._late_commands, 'backlogCollapsedEvents': engine._collapsed_events,
            'dropReasons': engine._late_reasons, 'bleBatches': engine._ble_batches,
            'bleCommands': engine._ble_commands, 'maxCommandsPerBatch': engine._max_batch_commands,
            'discardedAtEnd': engine._end_discarded_commands, 'wireCommands': len(transport.writes),
            'noteTransactions': len(transport.batches) if batching else sum('PLAY' in text for _, text in transport.writes),
            'lastCommand': transport.writes[-1][1]}

if __name__ == '__main__':
    stress = [Command(i*60/3750, 'play', 220, lane='fdd:1') for i in range(3750)] + [Command(60, 'stop', lane='fdd:1')]
    dense = [Command(t, 'play', 220, lane=lane) for t in range(10)
             for lane in ['fdd:1','fdd:2','fdd:3','fdd:4','sled:1','sled:2']]
    dense += [Command(10, 'stop', lane='fdd:1')]
    historical = [Command(t,'play',hz,lane='fdd:1') for t,hz in [(0,220),(.05,261),(.1,329)]] + [Command(3,'stop',lane='fdd:1')]
    result = {'model': 'production engine, simulated monotonic, 20 ms per send or send_batch; no physical song',
              'stress60': run(stress), 'denseIndividual': run(dense, False),
              'denseBatch': run(dense), 'backlogTwoSeconds': run(historical, initial_position=2)}
    path = ROOT/'docs/diagnostics/mechanical-drift/production-scheduler.json'
    path.write_text(json.dumps(result, indent=2)); print(json.dumps(result, indent=2))
