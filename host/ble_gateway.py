"""Native macOS Bluetooth access for the Docker runtime; no Serial fallback."""
import asyncio
import contextlib
import argparse
import logging
import json
import os
import plistlib
import subprocess
import sys
from collections import deque
from pathlib import Path
from ble_link import BleBytes
from ble_diagnostics import WriteHistory
from ble_ota import MAX_IMAGE
from ble_configuration import MAX_CONFIGURATION, validate_configuration, command_groups

log = logging.getLogger('orchestra.ble')

# A live performance must stop on congestion, never play seconds-old notes.
MAX_COMMAND_AGE = .250
MAX_PENDING = 512


from diagnostics import Diagnostics, NullDiagnostics

gateway_diagnostics=NullDiagnostics()


async def serve_client(reader, writer):
    link = None
    tasks = []
    history = WriteHistory()
    latest_loop_lag = max_loop_lag = 0.
    inflight = None
    pending = deque()
    maintenance_completed = False
    try:
        link = await asyncio.to_thread(BleBytes)
        log.info('BLE connected: payload=%d bytes, delivery=%s, command window=%d bytes, latency limit=%d ms',
                 getattr(link, 'write_size', 20),
                 'execution-ack' if getattr(link, '_application_ack', False) else 'att-response (legacy)',
                 getattr(link, 'command_capacity', getattr(link, 'write_size', 20)),
                 MAX_COMMAND_AGE * 1000)
        writer.write(b'BLE CONNECTED ota=1\n' if getattr(link,'supports_ota',False) else b'BLE CONNECTED\n'); await writer.drain()
        command_ready = asyncio.Event()
        oldest_inflight = None
        clock = asyncio.get_running_loop().time
        async def receive():
            nonlocal maintenance_completed
            # Read independently of slow GATT writes, so STOP can overtake
            # queued notes. Finish one in-flight line, then STOP, never replay it.
            while True:
                try:
                    data = await reader.readuntil(b'\n')
                except asyncio.IncompleteReadError as error:
                    if error.partial:
                        raise
                    return
                created = clock()
                if data.startswith(b'GATEWAY CONFIG '):
                    size = data[len(b'GATEWAY CONFIG '):-1]
                    if not size.isdigit() or len(size) > 8 or not 1 <= int(size) <= MAX_CONFIGURATION:
                        raise ValueError('Invalid BLE configuration size')
                    payload = await asyncio.wait_for(reader.readexactly(int(size)), 2)
                    validate_configuration(payload)
                    # Preparation happens before song time. Drain prior traffic,
                    # then await each bounded execution window, never queue the
                    # entire setup burst as already-due musical events.
                    deadline = clock() + MAX_COMMAND_AGE
                    while (pending or oldest_inflight is not None) and clock() < deadline:
                        await asyncio.sleep(.005)
                    if pending or oldest_inflight is not None:
                        raise ValueError('BLE configuration requires an idle command queue')
                    capacity = getattr(link, 'command_capacity', getattr(link, 'write_size', 20))
                    for group in command_groups(payload, capacity):
                        await asyncio.to_thread(link.write, group)
                    writer.write(b'BLE CONFIGURED\n')
                    await writer.drain()
                    continue
                if data.startswith(b'GATEWAY OTA '):
                    # Exclusive maintenance only, never mix binary image/key
                    # bytes with the line-oriented musical command queue.
                    size_text=data[len(b'GATEWAY OTA '):-1]
                    if not size_text.isdigit() or len(size_text)>8 or not 1<=int(size_text)<=MAX_IMAGE:
                        raise ValueError('Invalid BLE OTA size')
                    if not getattr(link,'supports_ota',False):raise ValueError('Firmware without BLE OTA')
                    deadline=clock()+MAX_COMMAND_AGE
                    while oldest_inflight is not None and clock()<deadline:await asyncio.sleep(.005)
                    if pending or oldest_inflight is not None:raise ValueError('BLE OTA requires an idle command queue')
                    writer.write(b'BLE OTA READY\n');await writer.drain()
                    payload=await asyncio.wait_for(reader.readexactly(32+int(size_text)),15)
                    loop=asyncio.get_running_loop()
                    def progress(percent):
                        loop.call_soon_threadsafe(writer.write,f'BLE OTA PROGRESS {percent}\n'.encode('ascii'))
                    await asyncio.to_thread(link.upload_firmware,payload[32:],payload[:32],progress)
                    maintenance_completed=True
                    writer.write(b'BLE OTA COMPLETE\n');await writer.drain()
                    return
                if len(data) > 96:
                    raise ValueError('BLE command too long')
                command = data.strip()
                if command == b'ALL STOP' or command.startswith(b'ALL STOP '):
                    discarded = len(pending)
                    pending.clear()
                    log.info('STOP priority: discarded %d queued commands', discarded)
                if len(pending) >= MAX_PENDING:
                    raise ValueError('BLE realtime overrun: command queue full; playback stopped')
                pending.append((created, data))
                command_ready.set()
        async def send():
            nonlocal oldest_inflight, inflight
            while True:
                await command_ready.wait()
                oldest_inflight, data = pending.popleft()
                if clock() - oldest_inflight > MAX_COMMAND_AGE:
                    raise ValueError('BLE realtime overrun: stale commands; playback stopped')
                # Batch already-due lines into one bounded execution window.
                # Do not wait for future notes or change their ordering.
                capacity = getattr(link, 'command_capacity', getattr(link, 'write_size', 20))
                while pending and len(data) + len(pending[0][1]) <= capacity:
                    _, line = pending.popleft()
                    data += line
                if not pending:
                    command_ready.clear()
                inflight = history.add(data, created=oldest_inflight)
                inflight.mark('dispatch')
                trace = inflight
                def write():
                    trace.mark('worker_started')
                    try: return link.write(data)
                    finally: trace.mark('worker_finished')
                try:
                    await asyncio.to_thread(write)
                except Exception as error:
                    trace.fail(error)
                    raise
                trace.mark('completed')
                inflight = None
                oldest_inflight = None
        async def watch_latency():
            nonlocal latest_loop_lag, max_loop_lag
            while True:
                scheduled = clock()+.01
                await asyncio.sleep(.01)
                latest_loop_lag = max(0., clock()-scheduled)*1000
                max_loop_lag = max(max_loop_lag, latest_loop_lag)
                oldest = oldest_inflight
                if oldest is None and pending:
                    oldest = pending[0][0]
                if oldest is not None and clock() - oldest > MAX_COMMAND_AGE:
                    delay = (clock() - oldest) * 1000
                    raise ValueError(f'BLE realtime overrun: {delay:.0f} ms delivery lag, {len(pending)} queued; playback stopped')
        async def transmit():
            telemetry = bytearray()
            while True:
                count = link.in_waiting
                if count:
                    telemetry.extend(link.read(count))
                    if len(telemetry) > 65536:
                        raise ValueError('BLE gateway telemetry overflow')
                    # Firmware STATUS arrives in 20-byte notifications. Gateway
                    # receipts must go BETWEEN lines, never inside a partial one.
                    while b'\n' in telemetry:
                        line, _, rest = telemetry.partition(b'\n')
                        telemetry[:] = rest
                        writer.write(line+b'\n')
                    await writer.drain()
                await asyncio.sleep(.005)
        tasks = [asyncio.create_task(receive()), asyncio.create_task(send()), asyncio.create_task(transmit()), asyncio.create_task(watch_latency())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done: task.result()
    except Exception as exc:
        if link:
            with contextlib.suppress(Exception):
                evidence = {'schema':1, 'reason':str(exc), 'queuedLines':len(pending),
                            'gatewayLoopLagMs':round(latest_loop_lag,3),
                            'maxGatewayLoopLagMs':round(max_loop_lag,3),
                            'gatewayWrites':history.snapshot(),
                            'transportWrites':link.timing_snapshot() if hasattr(link,'timing_snapshot') else None}
                gateway_diagnostics.incident('ble_transport_failure',context=evidence,error=exc)
                log.warning('BLE_TIMING %s', json.dumps(evidence, separators=(',',':')))
        log.info('BLE disconnected / connect failed: %s', exc)
        writer.write(('BLE ERROR ' + str(exc).replace('\n', ' ') + '\n').encode())
        with contextlib.suppress(Exception): await writer.drain()
    finally:
        for task in tasks: task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception): await task
        if link:
            # Cancellation of to_thread does not cancel a GATT write. BleBytes'
            # write lock orders this STOP after that one in-flight packet.
            if not maintenance_completed:
                with contextlib.suppress(Exception): await asyncio.to_thread(link.write, b'ALL STOP\n')
            await asyncio.to_thread(link.close)
        writer.close()
        with contextlib.suppress(Exception): await writer.wait_closed()


async def main(port=8766):
    global gateway_diagnostics
    gateway_diagnostics=Diagnostics(os.getenv('ORCHESTRA_GATEWAY_DIAGNOSTICS_DIR',
        str(Path(__file__).resolve().parents[1]/'.runtime/diagnostics/gateway')))
    gateway_diagnostics.start()
    try:
        server = await asyncio.start_server(serve_client, '127.0.0.1', port, limit=4096)
        async with server: await server.serve_forever()
    except BaseException as exc:
        gateway_diagnostics.incident('gateway_exit',error=exc)
        raise
    finally: await asyncio.to_thread(gateway_diagnostics.close)


def install_macos_service(port=8766):
    """The Docker VM cannot use CoreBluetooth: supervise the native gateway."""
    if sys.platform != 'darwin':
        raise RuntimeError('LaunchAgent installer requires macOS')
    root = Path(__file__).resolve().parents[1]
    runtime = root / '.runtime'; runtime.mkdir(exist_ok=True)
    path = Path.home() / 'Library/LaunchAgents/com.chopapik.electromechanical-midi.ble.plist'
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = {'Label': 'com.chopapik.electromechanical-midi.ble',
        'ProgramArguments': [sys.executable, str(Path(__file__).resolve()), '--port', str(port)],
        'WorkingDirectory': str(root), 'RunAtLoad': True, 'KeepAlive': True,
        'StandardOutPath': str(runtime / 'ble-gateway.log'),
        'StandardErrorPath': str(runtime / 'ble-gateway.log')}
    path.write_bytes(plistlib.dumps(settings))
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl','bootout',domain,str(path)], capture_output=True)
    subprocess.run(['launchctl','bootstrap',domain,str(path)], check=True)
    print('Installed native BLE gateway:', path)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(name)s:%(message)s')
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--install-macos-service', action='store_true')
    args = parser.parse_args()
    if args.install_macos_service: install_macos_service(args.port)
    else: asyncio.run(main(args.port))
