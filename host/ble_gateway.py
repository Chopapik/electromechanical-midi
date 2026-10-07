"""Native macOS Bluetooth access for the Docker runtime; no Serial fallback."""
import asyncio
import contextlib
import argparse
import logging
import os
import plistlib
import subprocess
import sys
from collections import deque
from pathlib import Path
from ble_link import BleBytes

log = logging.getLogger('orchestra.ble')

# A live performance must stop on congestion, never play seconds-old notes.
MAX_COMMAND_AGE = .250
MAX_PENDING = 512


async def serve_client(reader, writer):
    link = None
    tasks = []
    try:
        link = await asyncio.to_thread(BleBytes)
        log.info('BLE connected: acknowledged write payload=%d bytes, latency limit=%d ms',
                 getattr(link, 'write_size', 20), MAX_COMMAND_AGE * 1000)
        writer.write(b'BLE CONNECTED\n'); await writer.drain()
        pending = deque()
        command_ready = asyncio.Event()
        oldest_inflight = None
        clock = asyncio.get_running_loop().time
        async def receive():
            # Read independently of slow GATT writes, so STOP can overtake
            # queued notes. Finish one in-flight line, then STOP, never replay it.
            while True:
                data = await reader.readuntil(b'\n')
                if len(data) > 96:
                    raise ValueError('BLE command too long')
                command = data.strip()
                if command == b'ALL STOP' or command.startswith(b'ALL STOP '):
                    discarded = len(pending)
                    pending.clear()
                    log.info('STOP priority: discarded %d queued commands', discarded)
                if len(pending) >= MAX_PENDING:
                    raise ValueError('BLE realtime overrun: command queue full; playback stopped')
                pending.append((clock(), data))
                command_ready.set()
        async def send():
            nonlocal oldest_inflight
            while True:
                await command_ready.wait()
                oldest_inflight, data = pending.popleft()
                if clock() - oldest_inflight > MAX_COMMAND_AGE:
                    raise ValueError('BLE realtime overrun: stale commands; playback stopped')
                # Batch complete, already-due lines into one acknowledged ATT
                # packet. Do not wait for future notes or change their ordering.
                capacity = getattr(link, 'write_size', 20)
                while pending and len(data) + len(pending[0][1]) <= capacity:
                    data += pending.popleft()[1]
                if not pending:
                    command_ready.clear()
                await asyncio.to_thread(link.write, data)
                oldest_inflight = None
        async def watch_latency():
            while True:
                await asyncio.sleep(.01)
                oldest = oldest_inflight
                if oldest is None and pending:
                    oldest = pending[0][0]
                if oldest is not None and clock() - oldest > MAX_COMMAND_AGE:
                    delay = (clock() - oldest) * 1000
                    raise ValueError(f'BLE realtime overrun: {delay:.0f} ms delivery lag, {len(pending)} queued; playback stopped')
        async def transmit():
            while True:
                count = link.in_waiting
                if count:
                    writer.write(link.read(count)); await writer.drain()
                await asyncio.sleep(.005)
        tasks = [asyncio.create_task(receive()), asyncio.create_task(send()), asyncio.create_task(transmit()), asyncio.create_task(watch_latency())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done: task.result()
    except Exception as exc:
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
            with contextlib.suppress(Exception): await asyncio.to_thread(link.write, b'ALL STOP\n')
            await asyncio.to_thread(link.close)
        writer.close()
        with contextlib.suppress(Exception): await writer.wait_closed()


async def main(port=8766):
    server = await asyncio.start_server(serve_client, '127.0.0.1', port, limit=4096)
    async with server: await server.serve_forever()


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
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(); parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--install-macos-service', action='store_true')
    args = parser.parse_args()
    if args.install_macos_service: install_macos_service(args.port)
    else: asyncio.run(main(args.port))
