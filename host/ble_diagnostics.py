"""Bounded host-side timing evidence; no transport or actuator operations."""
from collections import deque
import threading
import time


class WriteTrace:
    def __init__(self, data, *, created=None, clock=time.monotonic):
        self.clock = clock
        self.created = clock() if created is None else created
        self.lock = threading.Lock()
        self.phase = 'submitted'
        self.events = {'submitted': self.created}
        self.ended = None
        self.fragments = 0
        self.gatt_total = self.gatt_max = 0.
        self.error = None
        self.size = len(data)
        lines = data.decode('ascii', errors='replace').splitlines()
        self.command_count = len(lines)
        self.commands = [line[:95] for line in lines[:8]]

    def mark(self, phase):
        with self.lock:
            now = self.clock()
            self.events[phase] = now
            self.phase = phase
            if phase == 'completed': self.ended = now

    def fragment_finished(self):
        with self.lock:
            now = self.clock()
            duration = now-self.events['gatt_started']
            self.fragments += 1
            self.gatt_total += duration
            self.gatt_max = max(self.gatt_max, duration)
            self.events['gatt_completed'] = now
            self.phase = 'gatt_completed'

    def fail(self, error):
        with self.lock:
            self.ended = self.clock()
            self.error = type(error).__name__+': '+str(error)[:200]
            self.phase = 'failed'

    def snapshot(self):
        with self.lock:
            now = self.clock()
            ms = lambda value: round(value*1000, 3)
            difference = lambda end, start: (ms(self.events[end]-self.events[start])
                if end in self.events and start in self.events else None)
            return {'phase':self.phase, 'bytes':self.size, 'commandCount':self.command_count,
                    'commands':list(self.commands), 'error':self.error,
                    'ageMs':ms((self.ended if self.ended is not None else now)-self.created),
                    'eventsMs':{key:ms(value-self.created) for key,value in self.events.items()},
                    'bleLoopDelayMs':difference('ble_loop', 'submitted'),
                    'lockWaitMs':difference('lock_acquired', 'ble_loop'),
                    'workerQueueMs':difference('worker_started', 'dispatch'),
                    'gatewayResumeMs':difference('completed', 'worker_finished'),
                    'executionAckWaitMs':difference('ack_received', 'ack_wait'),
                    'currentExecutionAckWaitMs':ms(now-self.events['ack_wait']) if self.phase=='ack_wait' else 0.,
                    'fragments':self.fragments, 'gattTotalMs':ms(self.gatt_total),
                    'gattMaxMs':ms(self.gatt_max),
                    'currentGattMs':ms(now-self.events['gatt_started']) if self.phase=='gatt_started' else 0.}


class WriteHistory:
    def __init__(self, capacity=64):
        self.lock = threading.Lock()
        self.traces = deque(maxlen=capacity)

    def add(self, data, **kwargs):
        trace = WriteTrace(data, **kwargs)
        with self.lock: self.traces.append(trace)
        return trace

    def snapshot(self):
        with self.lock: traces = tuple(self.traces)
        values = [trace.snapshot() for trace in traces]
        completed = sorted(trace['ageMs'] for trace in values if trace['phase']=='completed')
        return {'scope':f'last {self.traces.maxlen} writes; host clocks (deliveryMode identifies the ACK source)',
                'sampleCount':len(completed),
                'meanMs':round(sum(completed)/len(completed),3) if completed else None,
                'p95Ms':completed[max(0, (95*len(completed)+99)//100-1)] if completed else None,
                'maxMs':max(completed) if completed else None,
                'active':[trace for trace in values if trace['phase'] not in ('completed','failed')],
                'recent':values[-8:]}


class LoopTiming:
    """Separate a suspended local event loop from a slow asynchronous GATT call."""
    interval = .02

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.previous = clock()
        self.last_lag = self.max_lag = 0.

    def tick(self):
        with self.lock:
            now = self.clock()
            self.last_lag = max(0., now-self.previous-self.interval)
            self.max_lag = max(self.max_lag, self.last_lag)
            self.previous = now

    def snapshot(self):
        with self.lock:
            return {'intervalMs':self.interval*1000,
                    'lastLagMs':round(self.last_lag*1000,3),
                    'maxLagMs':round(self.max_lag*1000,3),
                    'currentlyOverdueMs':round(max(0., self.clock()-self.previous-self.interval)*1000,3)}
