"""The CLI must request the shared backend barrier, never invoke PlatformIO."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('safe_upload',Path(__file__).resolve().parents[2]/'scripts/safe_upload.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

class SafeUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_local_websocket_origin_and_shared_firmware_action(self):
        class Socket:
            async def send(self,text):self.request=json.loads(text)
            def __aiter__(self):return self
            async def __anext__(self):return json.dumps({'type':'ack','requestId':self.request['requestId']})
        socket=Socket()
        class Connection:
            async def __aenter__(self):return socket
            async def __aexit__(self,*args):pass
        with patch('websockets.asyncio.client.connect',return_value=Connection()) as connect:
            await cli.upload('ws://127.0.0.1:5173/ws')
        connect.assert_called_once_with('ws://127.0.0.1:5173/ws',origin='http://127.0.0.1:5173')
        self.assertEqual(socket.request['action'],'service')
        self.assertEqual(socket.request['operation'],'firmware')
        self.assertNotIn('confirmed',socket.request)

    async def test_nonlocal_urls_cannot_reach_transport(self):
        with patch('websockets.asyncio.client.connect') as connect:
            for url in ['ws://example.org/ws','wss://localhost/ws','ws://localhost/other']:
                with self.assertRaises(ValueError):await cli.upload(url)
            connect.assert_not_called()
