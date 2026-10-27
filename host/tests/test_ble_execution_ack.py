"""Execution receipts replace ATT responses, never receipts themselves.

All clients here are fakes: no Bluetooth, GPIO, ATX or instrument commands run.
"""
import asyncio
import unittest
from types import SimpleNamespace

from ble_link import BleBytes, ACK, RX, TX
from floppy_link import SerialLinkError
from test_ble_link import Client, Scanner


class AckClient(Client):
    mtu_size = 255
    capacity = 252
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services = SimpleNamespace(get_characteristic=lambda uuid:
            SimpleNamespace(max_write_without_response_size=self.capacity) if uuid == RX else object())
        self.callbacks = {}
        self.tokens = []
        self.responses = []
        self.drop = self.wrong = self.duplicate = False
        self.parsed = []
        self.ack_delay = 0

    async def start_notify(self, uuid, callback):
        self.callbacks[uuid] = callback

    async def write_gatt_char(self, uuid, data, response):
        assert uuid == RX and len(data) <= self.capacity
        self.responses.append(response)
        # Reproduce the old bottleneck: an ATT request takes >250 ms, while the
        # separate peripheral execution receipt is available immediately.
        if response: await asyncio.sleep(.35)
        self.sent.append(data)
        self.line += data
        while b'\n' in self.line:
            line, _, self.line = self.line.partition(b'\n')
            if line.startswith(b'SYNC '):
                token = line[5:]
                self.tokens.append(token)
                if self.drop: continue
                callback = self.callbacks[ACK]
                if self.wrong:
                    callback(None, b'SYNCED 9999999999\n')
                    continue
                if self.ack_delay: await asyncio.sleep(self.ack_delay)
                # Also exercise notification fragmentation and duplicate ACKs.
                callback(None, b'SYNC'); callback(None, b'ED '+token+b'\n')
                if self.duplicate: callback(None, b'SYNCED '+token+b'\n')
            else:
                self.parsed.append(line)
                if line == b'PING': self.callbacks[TX](None, b'PONG\n')


class ExecutionAckTests(unittest.TestCase):
    def create(self, client=AckClient):
        raw = BleBytes(scanner=Scanner(), client_factory=client)
        self.addCleanup(raw.close)
        self.assertTrue(raw._application_ack)
        return raw, raw._client

    def test_removes_delayed_att_response_dependency_but_waits_for_execution(self):
        raw, client = self.create()
        raw.write(b'PING\n')
        self.assertEqual(client.responses, [False, False])  # Handshake + data.
        self.assertEqual(client.parsed, [b'PING'])
        self.assertEqual(raw.read(raw.in_waiting), b'PONG\n')
        self.assertEqual(raw.timing_snapshot()['deliveryMode'], 'execution-ack')
        self.assertEqual(len(set(client.tokens)), 2)
        self.assertIsNotNone(raw.timing_snapshot()['recent'][0]['executionAckWaitMs'])

    def test_no_fallback_when_advertised_receipt_does_not_work(self):
        class Broken(AckClient):
            async def start_notify(self, uuid, callback):
                await super().start_notify(uuid, callback)
                self.drop = True
        with self.assertRaisesRegex(SerialLinkError, 'execution ACK timeout'):
            BleBytes(scanner=Scanner(), client_factory=Broken)

    def test_missing_or_wrong_ack_fails_and_never_replays_next_group(self):
        for wrong in (False, True):
            with self.subTest(wrong=wrong):
                raw, client = self.create()
                client.wrong = wrong; client.drop = not wrong
                with self.assertRaisesRegex(SerialLinkError, 'execution ACK timeout'):
                    raw.write(b'PING\n'*100)
                self.assertEqual(client.parsed.count(b'ALL STOP'), 1)
                self.assertLess(client.parsed.count(b'PING'), 100)
                self.assertTrue(raw._closed)

    def test_mtu23_fragmentation_and_large_batches_preserve_exact_commands(self):
        class Small(AckClient):
            mtu_size = 23
            capacity = 20
        raw, client = self.create(Small)
        # A max-sized command plus a large configuration burst; each credit
        # holds <=6 ATT fragments, within the firmware's eight RX slots.
        commands = [b'X'*95] + [b'PING']*100
        raw.write(b'\n'.join(commands)+b'\n')
        self.assertEqual(client.parsed, commands)
        self.assertTrue(all(len(p) <= 20 for p in client.sent))
        groups = b''.join(client.sent).split(b'SYNC ')[1:]
        self.assertGreater(len(groups), 2)
        self.assertEqual(len(client.tokens), len(set(client.tokens)))

    def test_duplicate_acks_do_not_satisfy_a_later_write(self):
        raw, client = self.create()
        client.duplicate = True
        raw.write(b'PING\n')
        client.drop = True
        with self.assertRaisesRegex(SerialLinkError, 'execution ACK timeout'):
            raw.write(b'PING\n')
        self.assertEqual(client.parsed, [b'PING', b'PING', b'ALL STOP'])

    def test_invalid_batch_is_rejected_before_any_bytes_are_sent(self):
        raw, client = self.create()
        for invalid in (b'PING', b'PING\n'+b'X'*96+b'\n', b'PING\n\xff\n', b'PING\r\n'):
            with self.subTest(invalid=invalid):
                before = list(client.sent)
                # Validation alone, before the synchronous session-poisoning API.
                with self.assertRaises(SerialLinkError): raw._ack_groups(invalid)
                self.assertEqual(client.sent, before)

    def test_write_without_response_capacity_is_respected(self):
        class SmallLimit(AckClient):
            capacity = 20  # MTU alone must not select 252-byte NR writes.
        raw, client = self.create(SmallLimit)
        raw.write(b'PING\n'*40)
        self.assertEqual(raw.write_size, 20)
        self.assertTrue(all(len(packet)<=20 for packet in client.sent))

    def test_disconnect_while_waiting_for_ack_fails_without_replaying(self):
        raw, client = self.create()
        class Disconnect:
            def __bool__(self):
                # Drop the receipt and disconnect on the BLE loop itself.
                raw._loop.call_soon(client.disconnect_callback, client)
                return True
        client.drop = Disconnect()
        with self.assertRaises(SerialLinkError): raw.write(b'PING\n'*100)
        self.assertTrue(raw._closed)
        self.assertFalse(raw._thread.is_alive())
        self.assertLess(client.parsed.count(b'PING'), 100)


class AckAtomicTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_batches_share_one_credit_and_do_not_interleave(self):
        raw = BleBytes.__new__(BleBytes)
        client = AckClient(None, lambda _: None)
        raw._client = client
        raw._write_lock = asyncio.Lock()
        raw._application_ack = True
        raw._pending_ack = None
        raw._ack_buffer = bytearray()
        raw._ack_sequence = 1
        raw.write_size = 252
        await client.start_notify(ACK, raw._ack_notification)
        await client.start_notify(TX, lambda *_: None)
        a, b = b'FIRST\n'*100, b'SECOND\n'*100
        await asyncio.gather(raw._write(a), raw._write(b))
        self.assertEqual(client.parsed, [b'FIRST']*100+[b'SECOND']*100)
