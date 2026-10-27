"""Setup waits for execution; its receipt cannot corrupt fragmented telemetry."""
import asyncio
import threading
import unittest
from unittest.mock import Mock, patch

from ble_gateway import serve_client
from ble_link import GatewayBytes
from floppy_link import SerialLinkError


class GatewayConfigurationReceiptTests(unittest.TestCase):
    def transport(self, replies):
        raw = GatewayBytes.__new__(GatewayBytes)
        raw._write_lock = threading.Lock()
        raw._configuration_buffer = bytearray()
        raw._error_probe = b''
        raw._socket = Mock()
        raw._socket.recv.side_effect = [bytes([b]) for b in replies] + [b'']
        return raw

    def test_missing_receipt_or_gateway_error_never_reports_success(self):
        for response in (b'STATUS END\n', b'BLE ERROR delivery lag\n'):
            raw = self.transport(response)
            with self.subTest(response=response), self.assertRaises(SerialLinkError):
                raw.configure(b'FDD 1 ENABLE 1\n')

    def test_configuration_requires_its_completion_and_preserves_telemetry(self):
        raw = self.transport(b'STATUS END\nBLE CONFIGURED\n')
        raw.configure(b'FDD 1 ENABLE 1\n')
        self.assertEqual(raw.read(raw.in_waiting), b'STATUS END\n')
        raw._socket.sendall.assert_called_once_with(b'GATEWAY CONFIG 15\nFDD 1 ENABLE 1\n')


class GatewayReceiptFramingTests(unittest.IsolatedAsyncioTestCase):
    async def test_receipt_never_splits_a_fragmented_firmware_line(self):
        class Reader:
            def __init__(self):
                self.queue = asyncio.Queue()
            async def readuntil(self, _):
                return await self.queue.get()
            async def readexactly(self, _):
                return b'FDD 1 ENABLE 1\n'
        class Writer:
            def __init__(self):
                self.data = bytearray()
            def write(self, data): self.data.extend(data)
            async def drain(self): pass
            def close(self): pass
            async def wait_closed(self): pass
        class Link:
            write_size = 252
            def __init__(self):
                self.chunks = [b'STATUS CTRL rea']
                self.written = threading.Event()
                self.finish = threading.Event()
            @property
            def in_waiting(self): return len(self.chunks[0]) if self.chunks else 0
            def read(self, _): return self.chunks.pop(0)
            def write(self, data):
                if data == b'FDD 1 ENABLE 1\n':
                    self.written.set()
                    assert self.finish.wait(2)
            def close(self): pass
        reader, writer, link = Reader(), Writer(), Link()
        with patch('ble_gateway.BleBytes', return_value=link):
            task = asyncio.create_task(serve_client(reader, writer))
            try:
                await asyncio.sleep(.02)  # Let the first telemetry fragment arrive.
                await reader.queue.put(b'GATEWAY CONFIG 15\n')
                self.assertTrue(await asyncio.to_thread(link.written.wait, 1))
                self.assertNotIn(b'BLE CONFIGURED', writer.data)
                link.finish.set()
                for _ in range(50):
                    if b'BLE CONFIGURED' in writer.data: break
                    await asyncio.sleep(.005)
                link.chunks.append(b'dy=1\n')
                for _ in range(50):
                    if b'STATUS CTRL ready=1\n' in writer.data: break
                    await asyncio.sleep(.005)
                self.assertEqual(writer.data, b'BLE CONNECTED\nBLE CONFIGURED\nSTATUS CTRL ready=1\n')
            finally:
                link.finish.set()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
