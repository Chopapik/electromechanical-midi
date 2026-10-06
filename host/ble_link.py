"""NUS byte transport beneath the existing OrchestraLink command/status parser."""
import asyncio
import os
import select
import socket
import threading
import time

from floppy_link import SerialLinkError
from orchestra_link import OrchestraLink

NAME = 'Electromechanical-MIDI'
SERVICE = '6E400001-B5A3-F393-E0A9-E50E24DCCA9E'
RX = '6E400002-B5A3-F393-E0A9-E50E24DCCA9E'
TX = '6E400003-B5A3-F393-E0A9-E50E24DCCA9E'


class BleBytes:
    """One BLE session. Never replay pending commands into a new connection."""
    def __init__(self, scanner=None, client_factory=None, timeout=20):
        if scanner is None:
            from bleak import BleakScanner, BleakClient
            scanner, client_factory = BleakScanner, BleakClient
        self._scanner, self._factory = scanner, client_factory
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._error = None
        self._ready = threading.Event()
        self._closed = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name='orchestra-ble', daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self.close()
            raise SerialLinkError('BLE: timeout podczas szukania/łączenia ' + NAME)
        self._check()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._task = self._loop.create_task(self._session())
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._error = SerialLinkError(f'BLE: {exc}')
        finally:
            self._closed = True
            self._ready.set()
            self._loop.close()

    async def _session(self):
        self._end = asyncio.Event()
        device = await self._scanner.find_device_by_filter(
            lambda device, adv: (adv.local_name or device.name) == NAME,
            timeout=6, service_uuids=[SERVICE])
        if device is None:
            raise SerialLinkError('Nie znaleziono ' + NAME)
        def disconnected(_client):
            self._error = SerialLinkError('BLE: disconnected')
            self._end.set()
        async with self._factory(device, disconnected_callback=disconnected, timeout=10) as client:
            self._client = client
            self._write_lock = asyncio.Lock()
            await client.start_notify(TX, self._notification)
            self._ready.set()
            await self._end.wait()

    def _notification(self, _characteristic, data):
        with self._lock:
            if len(self._buffer) + len(data) > 65536:
                self._error = SerialLinkError('BLE: przepełnienie bufora RX')
                self._end.set()
                return
            self._buffer.extend(data)

    def _check(self):
        if self._error:
            raise self._error
        if self._closed:
            raise SerialLinkError('BLE: disconnected')

    @property
    def in_waiting(self):
        self._check()
        with self._lock:
            return len(self._buffer)

    def read(self, count):
        self._check()
        with self._lock:
            data = bytes(self._buffer[:count]); del self._buffer[:count]
            return data

    async def _write(self, data):
        async with self._write_lock:
            # MTU=23 is supported; preserve newline framing across fragments.
            for offset in range(0, len(data), 20):
                await self._client.write_gatt_char(RX, data[offset:offset+20], response=True)

    def write(self, data):
        self._check()
        coroutine = self._write(data)
        future = None
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            future.result(timeout=2)
        except Exception as exc:
            if future is not None: future.cancel()
            else: coroutine.close()
            self._error = SerialLinkError(f'BLE write: {exc}')
            self.close()
            raise self._error from exc
        return len(data)

    def close(self):
        self._closed = True
        if self._loop.is_running():
            if hasattr(self, '_end'):
                self._loop.call_soon_threadsafe(self._end.set)
            if hasattr(self, '_task'):
                self._loop.call_soon_threadsafe(self._task.cancel)
            else:
                self._loop.call_soon_threadsafe(lambda: None)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)


class GatewayBytes:
    """Docker-to-native BLE bridge; plain command bytes after connection header."""
    def __init__(self, address):
        host, port = address.rsplit(':', 1)
        self._socket = socket.create_connection((host, int(port)), timeout=2)
        try:
            self._socket.settimeout(20)
            header = bytearray()
            while not header.endswith(b'\n') and len(header) < 1024:
                chunk = self._socket.recv(1)
                if not chunk: break
                header.extend(chunk)
            if bytes(header) != b'BLE CONNECTED\n':
                raise SerialLinkError(header.decode(errors='replace').strip() or 'BLE bridge disconnected')
            self._socket.settimeout(2)
        except Exception:
            self.close()
            raise

    @property
    def in_waiting(self):
        return 65536 if select.select([self._socket], [], [], 0)[0] else 0

    def read(self, count):
        data = self._socket.recv(count)
        if not data:
            raise SerialLinkError('BLE: disconnected')
        return data

    def write(self, data):
        self._socket.sendall(data)
        return len(data)

    def close(self):
        self._socket.close()


class BleOrchestraLink(OrchestraLink):
    protocol_version = 2
    board = 'esp32'
    transport_kind = 'ble'

    def __init__(self, byte_transport=None):
        self.port = 'ble://' + NAME
        self.label = NAME + ' · BLE'
        self._buffer = ''
        self.device_status = {}
        self.controller_status = {}
        self._status_lines = None
        gateway = os.getenv('ORCHESTRA_BLE_GATEWAY')
        self._serial = byte_transport or (GatewayBytes(gateway) if gateway else BleBytes())

    def wait_boot(self, timeout=10, echo=print, **_kwargs):
        # BLE does not receive USB's boot READY. Validate the same protocol via PING.
        self.ping()
        return self.wait_for('PONG', timeout=timeout) == 'PONG'

    def close(self):
        self._serial.close()

    def wait_homed(self, timeout=10, echo=print):
        # BLE STATUS is fragmented/paced: do not request another transaction
        # until the previous one ends. Device readiness/parser are unchanged.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.status()
            while time.monotonic() < deadline:
                lines = self.poll_lines()
                for line in lines:
                    echo(line)
                    if line.startswith('ERR'): return False
                if 'STATUS END' in lines:
                    fdds = [value for key, value in self.device_status.items() if key.startswith('FDD:') and value.get('enabled') == '1']
                    if any(key.startswith('FDD:') for key in self.device_status) and all(value.get('homed') == '1' and value.get('homing') == '0' for value in fdds):
                        return True
                    break
                time.sleep(.005)
        return False

async def maintain_ble_connection(engine, connect, can_connect=lambda: True, interval=2):
    """Retry BLE indefinitely; device errors with a live link do not reconnect."""
    while True:
        status = (await asyncio.to_thread(engine.snapshot))['hardware']
        if status.get('controllerTarget') == 'esp32' and not status['connected'] and not status['connecting'] and can_connect():
            await connect()
        await asyncio.sleep(interval)
