"""STOP must overtake a backlog of commands waiting for slow GATT writes."""
import asyncio
import threading
import unittest
from unittest.mock import patch
from ble_gateway import serve_client


class BleGatewayStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_discards_backlog_after_one_inflight_command(self):
        class Reader:
            def __init__(self):
                self.commands = asyncio.Queue()
                self.stop_read = asyncio.Event()
            async def readuntil(self, separator):
                data = await self.commands.get()
                if data.startswith(b'ALL STOP'):
                    self.stop_read.set()
                return data
        class Writer:
            def __init__(self): self.data = bytearray(); self.closed = False
            def write(self, data): self.data.extend(data)
            async def drain(self): pass
            def close(self): self.closed = True
            async def wait_closed(self): pass
        class Link:
            in_waiting = 0
            def __init__(self):
                self.started = threading.Event(); self.release = threading.Event()
                self.sent = []; self.closed = False
            def write(self, data):
                self.sent.append(data)
                if len(self.sent) == 1:
                    self.started.set()
                    assert self.release.wait(3)
            def close(self): self.closed = True
        reader, writer, link = Reader(), Writer(), Link()
        with patch('ble_gateway.BleBytes', return_value=link):
            task = asyncio.create_task(serve_client(reader, writer))
            try:
                await reader.commands.put(b'FDD 1 PLAY 220\n')
                self.assertTrue(await asyncio.to_thread(link.started.wait, 2))
                for _ in range(80):
                    await reader.commands.put(b'FDD 1 PLAY 330\n')
                await reader.commands.put(b'ALL STOP 42\n')
                await asyncio.wait_for(reader.stop_read.wait(), 2)
                link.release.set()
                for _ in range(100):
                    if len(link.sent) == 2: break
                    await asyncio.sleep(.01)
                self.assertEqual(link.sent, [b'FDD 1 PLAY 220\n', b'ALL STOP 42\n'])
                self.assertEqual(writer.data, b'BLE CONNECTED\n')
            finally:
                link.release.set(); task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            self.assertTrue(link.closed)


class BleGatewayRealtimeTests(unittest.IsolatedAsyncioTestCase):
    async def run_session(self, link, lines, budget=.25):
        class Reader:
            def __init__(self): self.queue = asyncio.Queue()
            async def readuntil(self, _): return await self.queue.get()
        class Writer:
            data = b''
            def write(self, data): self.data += data
            async def drain(self): pass
            def close(self): pass
            async def wait_closed(self): pass
        reader, writer = Reader(), Writer()
        for line in lines: reader.queue.put_nowait(line)
        with patch('ble_gateway.BleBytes', return_value=link), patch('ble_gateway.MAX_COMMAND_AGE', budget):
            task = asyncio.create_task(serve_client(reader, writer))
            try:
                await asyncio.wait_for(task, 2)
            finally:
                if not task.done():
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError): await task
        return writer.data

    async def test_slow_gatt_stops_instead_of_replaying_stale_notes(self):
        import time
        class Link:
            in_waiting = 0
            def __init__(self): self.sent = []
            def write(self, data):
                self.sent.append(data)
                if len(self.sent) == 1: time.sleep(.15)
            def close(self): pass
        link = Link()
        data = await self.run_session(link, [b'FDD 1 PLAY 220\n', b'FDD 1 PLAY 330\n'], budget=.05)
        self.assertIn(b'BLE ERROR BLE realtime overrun:', data)
        self.assertEqual(link.sent, [b'FDD 1 PLAY 220\n', b'ALL STOP\n'])

    async def test_due_commands_batched_without_changing_order(self):
        class Link:
            write_size = 182
            in_waiting = 0
            def __init__(self): self.sent = []
            def write(self, data):
                self.sent.append(data)
                if data.endswith(b'PING\n'): raise RuntimeError('end test')
            def close(self): pass
        link = Link()
        commands = [b'FDD 1 PLAY 220\n', b'SLED 1 PLAY 250\n', b'HDD 1 HIT\n']
        # Enough commands to exercise more than one packet.
        commands += [b'FDD 1 PLAY 220\n'] * 9 + [b'PING\n']
        data = await self.run_session(link, commands, budget=.01)
        normal = b''.join(link.sent[:-1])
        self.assertEqual(normal, b''.join(commands))
        self.assertTrue(any(packet.count(b'\n') > 1 for packet in link.sent[:-1]))
        self.assertTrue(all(len(packet) <= 182 for packet in link.sent))
        self.assertEqual(link.sent[-1], b'ALL STOP\n')
