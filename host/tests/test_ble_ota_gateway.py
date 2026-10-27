import asyncio
import threading
import time
import unittest
from unittest.mock import Mock,patch
from ble_gateway import serve_client
from ble_link import GatewayBytes
from floppy_link import SerialLinkError


class OtaGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def session(self,size=5,fail=False):
        key=b'k'*32;image=b'image'
        class Reader:
            def __init__(self):self.once=False;self.binary_read=False
            async def readuntil(self,_):
                if self.once:await asyncio.Future()
                self.once=True;return f'GATEWAY OTA {size}\n'.encode()
            async def readexactly(self,count):
                self.binary_read=True;assert count==37;return key+image
        class Writer:
            def __init__(self):self.data=bytearray()
            def write(self,data):self.data.extend(data)
            async def drain(self):pass
            def close(self):pass
            async def wait_closed(self):pass
        class Link:
            supports_ota=True;in_waiting=0
            def __init__(self):self.commands=[];self.uploads=0;self.closed=False
            def write(self,data):self.commands.append(data)
            def upload_firmware(self,data,secret,progress):
                assert data==image and secret==key
                self.uploads+=1;progress(0)
                time.sleep(.3) # Maintenance is not a pending musical command.
                if fail:raise RuntimeError('OTA failed')
                progress(100)
            def close(self):self.closed=True
        reader,writer,link=Reader(),Writer(),Link()
        with patch('ble_gateway.BleBytes',return_value=link):
            await asyncio.wait_for(serve_client(reader,writer),2)
        return reader,writer,link

    async def test_binary_transfer_never_enters_musical_queue_or_age_guard(self):
        reader,writer,link=await self.session()
        self.assertTrue(reader.binary_read);self.assertEqual(link.uploads,1);self.assertTrue(link.closed)
        self.assertFalse(link.commands)
        self.assertIn(b'BLE CONNECTED ota=1\nBLE OTA READY\n',writer.data)
        self.assertIn(b'BLE OTA PROGRESS 100\nBLE OTA COMPLETE\n',writer.data)
        self.assertNotIn(b'BLE ERROR',writer.data)

    async def test_invalid_size_never_reads_key_or_image(self):
        with self.assertLogs('orchestra.ble',level='WARNING'):
            reader,writer,link=await self.session(size=2000000)
        self.assertFalse(reader.binary_read);self.assertEqual(link.uploads,0)
        self.assertNotIn(b'BLE OTA READY',writer.data)

    async def test_failure_does_not_claim_commit_and_attempts_only_safety_stop(self):
        with self.assertLogs('orchestra.ble',level='WARNING'):
            _,writer,link=await self.session(fail=True)
        self.assertNotIn(b'BLE OTA COMPLETE',writer.data)
        self.assertIn(b'BLE ERROR OTA failed',writer.data)
        self.assertEqual(link.commands,[b'ALL STOP\n']);self.assertEqual(link.uploads,1)


class OtaGatewayClientTests(unittest.TestCase):
    def raw(self,lines):
        raw=GatewayBytes.__new__(GatewayBytes);raw.supports_ota=True
        raw._socket=Mock();raw._socket.recv.side_effect=[bytes([value]) for value in lines]
        raw._write_lock=threading.Lock()
        return raw

    def test_private_key_is_sent_only_after_gateway_readiness(self):
        raw=self.raw(b'BLE OTA READY\nBLE OTA PROGRESS 50\nBLE OTA COMPLETE\n');progress=[]
        result=raw.upload_firmware(b'image',b'k'*32,progress.append)
        self.assertEqual(result['bytes'],5);self.assertEqual(progress,[50])
        self.assertEqual(raw._socket.sendall.call_args_list[0].args,(b'GATEWAY OTA 5\n',))
        self.assertEqual(raw._socket.sendall.call_args_list[1].args,(b'k'*32+b'image',))
        raw=self.raw(b'BLE ERROR unavailable\n')
        with self.assertRaises(SerialLinkError):raw.upload_firmware(b'image',b'k'*32)
        raw._socket.sendall.assert_called_once_with(b'GATEWAY OTA 5\n')
