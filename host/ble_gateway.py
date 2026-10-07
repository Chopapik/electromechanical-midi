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


async def serve_client(reader, writer):
    link = None
    tasks = []
    try:
        link = await asyncio.to_thread(BleBytes)
        log.info('BLE connected')
        writer.write(b'BLE CONNECTED\n'); await writer.drain()
        pending = deque()
        command_ready = asyncio.Event()
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
                if len(pending) >= 4096:
                    raise ValueError('BLE command queue overflow')
                pending.append(data)
                command_ready.set()
        async def send():
            while True:
                await command_ready.wait()
                data = pending.popleft()
                if not pending:
                    command_ready.clear()
                await asyncio.to_thread(link.write, data)
        async def transmit():
            while True:
                count = link.in_waiting
                if count:
                    writer.write(link.read(count)); await writer.drain()
                await asyncio.sleep(.005)
        tasks = [asyncio.create_task(receive()), asyncio.create_task(send()), asyncio.create_task(transmit())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done: task.result()
    except Exception as exc:
        log.info('BLE disconnected / connect failed: %s', exc)
        if link is None:
            writer.write(('BLE ERROR ' + str(exc).replace('\n', ' ') + '\n').encode())
            with contextlib.suppress(Exception): await writer.drain()
    finally:
        for task in tasks: task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception): await task
        if link: await asyncio.to_thread(link.close)
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
