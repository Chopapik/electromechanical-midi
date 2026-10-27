"""OTA signatures/credit flow with a fake peripheral; no physical flashing."""
import asyncio
import hashlib
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ecdsa import SigningKey,NIST256p,BadSignatureError
import ble_ota as ota

KEY=bytes(range(1,33))


class Peripheral:
    def __init__(self,capacity=252):
        self.mtu_size=capacity+3;self.capacity=capacity
        self.services=SimpleNamespace(get_characteristic=lambda _:SimpleNamespace(max_write_without_response_size=capacity))
        self.nonce=b'x'*16;self.meta=bytearray();self.image=bytearray();self.expected=None
        self.sent=[];self.selected=False;self.aborted=False;self.frames=0;self.max_frames=0;self.drop_progress=False
    async def start_notify(self,uuid,callback):self.callback=callback
    async def stop_notify(self,uuid):pass
    def reply(self,data):self.callback(None,bytes(data))
    async def write_gatt_char(self,uuid,data,response):
        assert not response and len(data)<=(20 if uuid==ota.CONTROL else self.capacity)
        self.sent.append((uuid,bytes(data)));op=data[0]
        if op==ota.QUERY:self.reply(bytes([ota.CHALLENGE,1])+self.nonce)
        elif op==ota.META:
            assert data[1]==len(self.meta);self.meta.extend(data[2:])
        elif op==ota.BEGIN:
            assert len(self.meta)==100
            try:SigningKey.from_string(KEY,curve=NIST256p).verifying_key.verify(self.meta[36:],self.nonce+self.meta[:36],hashfunc=hashlib.sha256)
            except BadSignatureError:self.reply([ota.ERROR,4]);return
            self.expected=struct.unpack('<I',self.meta[:4])[0]
            self.reply(bytes([ota.READY])+struct.pack('<I',0))
        elif op&0x7f==ota.WRITE:
            assert struct.unpack('<I',data[1:5])[0]==len(self.image)
            self.frames+=1;self.max_frames=max(self.max_frames,self.frames)
            self.image.extend(data[5:])
            if op&0x80:
                self.frames=0
                if not self.drop_progress:self.reply(bytes([ota.PROGRESS])+struct.pack('<I',len(self.image)))
        elif op==ota.END:
            assert len(self.image)==self.expected and hashlib.sha256(self.image).digest()==self.meta[4:36]
            self.reply([ota.VERIFIED])
        elif op==ota.COMMIT:self.selected=True;self.reply([ota.COMMITTED])
        elif op==ota.ABORT:self.aborted=True


class OtaTransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_receipts_do_not_replay_firmware_windows(self):
        client=Peripheral();original=client.reply
        def duplicate(packet):original(packet);original(packet)
        client.reply=duplicate
        await ota.upload(client,b'x'*4000,KEY)
        self.assertTrue(client.selected)
        writes=[p for uuid,p in client.sent if uuid==ota.DATA]
        offsets=[struct.unpack('<I',p[1:5])[0] for p in writes]
        self.assertEqual(len(offsets),len(set(offsets)))

    async def test_unconfirmed_commit_is_not_reported_as_success(self):
        client=Peripheral();original=client.reply
        def missing(packet):
            if packet[0]!=ota.COMMITTED:original(packet)
        client.reply=missing
        real_wait=asyncio.wait_for
        async def quick(awaitable,timeout):return await real_wait(awaitable,min(timeout,.01))
        with patch('ble_ota.asyncio.wait_for',side_effect=quick):
            with self.assertRaisesRegex(RuntimeError,'COMMIT niepotwierdzony'):
                await ota.upload(client,b'image',KEY)
        self.assertTrue(client.selected)
        self.assertTrue(client.aborted)
    async def test_mtu23_and_wide_mtu_hash_signature_and_bounded_credit(self):
        for capacity in (20,252):
            with self.subTest(capacity=capacity):
                client=Peripheral(capacity);image=bytes(range(256))*30;progress=[]
                result=await ota.upload(client,image,KEY,progress.append)
                self.assertEqual(bytes(client.image),image)
                self.assertTrue(client.selected);self.assertFalse(client.aborted)
                self.assertLessEqual(client.max_frames,6)
                self.assertEqual(progress[-1],100)
                self.assertEqual(result['sha256'],hashlib.sha256(image).hexdigest())
                self.assertEqual(len(client.meta),100)

    async def test_wrong_private_key_cannot_start_flash(self):
        client=Peripheral()
        with self.assertRaisesRegex(RuntimeError,'klucz'):
            await ota.upload(client,b'image',b'1'*32)
        self.assertFalse(client.image);self.assertFalse(client.selected);self.assertTrue(client.aborted)

    async def test_missing_progress_aborts_without_replaying_window_or_committing(self):
        client=Peripheral();client.drop_progress=True
        real_wait=asyncio.wait_for
        async def quick(awaitable,timeout):return await real_wait(awaitable,min(timeout,.01))
        with patch('ble_ota.asyncio.wait_for',side_effect=quick):
            with self.assertRaises(asyncio.TimeoutError):await ota.upload(client,b'x'*6000,KEY)
        self.assertFalse(client.selected);self.assertTrue(client.aborted)
        writes=[p for uuid,p in client.sent if uuid==ota.DATA]
        self.assertEqual(len(writes),6)
        self.assertEqual(len(client.image),6*(252-5))

    async def test_wrong_offset_is_a_failed_session(self):
        client=Peripheral();original=client.reply
        def wrong(packet):
            if packet[0]==ota.PROGRESS:packet=bytes([ota.PROGRESS])+struct.pack('<I',123)
            original(packet)
        client.reply=wrong
        with self.assertRaisesRegex(RuntimeError,'offset'):await ota.upload(client,b'x'*2000,KEY)
        self.assertFalse(client.selected);self.assertTrue(client.aborted)

    async def test_no_ota_characteristic_never_attempts_a_write(self):
        client=Peripheral();client.services.get_characteristic=lambda _:None
        with self.assertRaisesRegex(RuntimeError,'USB'):await ota.upload(client,b'image',KEY)
        self.assertFalse(client.sent)

    async def test_manifest_bound_to_nonce_image_size_and_content(self):
        verifier=SigningKey.from_string(KEY,curve=NIST256p).verifying_key
        meta=ota.manifest(b'image',KEY,b'x'*16)
        self.assertTrue(verifier.verify(meta[36:],b'x'*16+meta[:36],hashfunc=hashlib.sha256))
        for message in (b'y'*16+meta[:36],b'x'*16+struct.pack('<I',6)+meta[4:36],b'x'*16+meta[:4]+b'0'*32):
            with self.assertRaises(BadSignatureError):verifier.verify(meta[36:],message,hashfunc=hashlib.sha256)

    async def test_invalid_size_and_key_are_rejected(self):
        for image,key in ((b'',KEY),(b'x',b'bad'),(b'x'*(ota.MAX_IMAGE+1),KEY)):
            with self.assertRaises(ValueError):ota.manifest(image,key,b'x'*16)
