"""Quiet transport probe: only correlated ALL STOP and PING, never motion/power.

Stop the orchestra container first; a second BLE client must not compete with it.
Run .venv/bin/python scripts/probe_ble_ping.py --seconds 120 --output /tmp/ble-ping.json
No retries after a communication error. RTT includes notification return time;
it is not the gateway's one-way 250 ms delivery-age measurement.
"""
import argparse
import contextlib
import json
import math
from pathlib import Path
import socket
import time


def validate_command(command):
    if command == 'PING': return
    if command.startswith('ALL STOP '):
        token = command[9:]
        if token.isascii() and token.isdecimal() and 1 <= len(token) <= 10: return
    raise ValueError('Probe permits only PING and correlated ALL STOP')


class Gateway:
    def __init__(self, host, port):
        self.socket = socket.create_connection((host, port), timeout=25)
        self.reader = self.socket.makefile('rb')
        try:
            if self.line() != 'BLE CONNECTED': raise RuntimeError('Missing BLE connection header')
            self.socket.settimeout(3)
        except BaseException:
            self.close(); raise

    def line(self):
        data = self.reader.readline(4097)
        if not data or len(data) > 4096: raise RuntimeError('BLE gateway closed or invalid frame')
        line = data.decode('ascii').strip()
        if line.startswith('BLE ERROR ') or line.startswith('ERR '): raise RuntimeError(line)
        return line

    def exchange(self, command, expected):
        validate_command(command)
        self.socket.sendall((command+'\n').encode('ascii'))
        response = self.line()
        if response != expected: raise RuntimeError('Unexpected response: '+response)

    def close(self):
        try: self.reader.close()
        finally: self.socket.close()


def probe(gateway, count, interval, *, clock=time.monotonic, sleep=time.sleep, progress=None):
    result = {'scope':'PING RTT through native gateway; no instrument or POWER commands',
              'initialStopConfirmed':False, 'finalStopConfirmed':False, 'samplesMs':[], 'error':None}
    started = clock()
    token = int(time.monotonic_ns() & 0xffffffff)
    try:
        gateway.exchange('ALL STOP '+str(token), 'STOPPED '+str(token))
        result['initialStopConfirmed'] = True
        due = clock()
        for index in range(count):
            sleep(max(0., due-clock()))
            before = clock()
            gateway.exchange('PING', 'PONG')
            result['samplesMs'].append(round((clock()-before)*1000, 3))
            due = max(before+interval, clock())  # No catch-up burst.
            if progress and (index+1) % 100 == 0: progress(index+1, result['samplesMs'][-1])
        token = (token+1) & 0xffffffff
        gateway.exchange('ALL STOP '+str(token), 'STOPPED '+str(token))
        result['finalStopConfirmed'] = True
    except Exception as error:
        result['error'] = type(error).__name__+': '+str(error)
        # A failed session is never retried or treated as STOP-confirmed.
    result['elapsedSeconds'] = round(clock()-started, 3)
    samples = sorted(result['samplesMs'])
    percentile = lambda percent: samples[max(0, math.ceil(percent*len(samples))-1)] if samples else None
    result['summary'] = {'samples':len(samples),
                         'meanMs':round(sum(samples)/len(samples),3) if samples else None,
                         'p50Ms':percentile(.50), 'p95Ms':percentile(.95), 'p99Ms':percentile(.99),
                         'maxMs':max(samples) if samples else None,
                         'rttOver100Ms':sum(value>100 for value in samples),
                         'rttOver250Ms':sum(value>250 for value in samples)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--interval', type=float, default=.1)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--app-port', type=int, default=5173)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (not math.isfinite(args.seconds) or not 1 <= args.seconds <= 600 or
            not math.isfinite(args.interval) or not .05 <= args.interval <= 2):
        parser.error('Use duration 1–600 s and interval 0.05–2 s')
    if args.output.exists(): parser.error('Refusing to overwrite an existing report')
    try:
        running = socket.create_connection(('127.0.0.1', args.app_port), timeout=1)
    except OSError:
        pass
    else:
        running.close()
        parser.error('Stop orchestra first: the application port is still open')
    gateway = None
    try:
        gateway = Gateway('127.0.0.1', args.port)
        result = probe(gateway, math.ceil(args.seconds/args.interval), args.interval,
                       progress=lambda count, last:print(f'{count} PONG; last RTT {last:.1f} ms', flush=True))
    except Exception as error:
        result = {'error':type(error).__name__+': '+str(error), 'initialStopConfirmed':False,
                  'finalStopConfirmed':False, 'summary':{'samples':0}}
    finally:
        if gateway:
            with contextlib.suppress(OSError): gateway.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({key:value for key,value in result.items() if key!='samplesMs'}, indent=2))
    return 0 if result['finalStopConfirmed'] and not result['error'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
