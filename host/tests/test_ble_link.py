import asyncio
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ble_link import BleBytes, BleOrchestraLink, RX, TX, NAME, maintain_ble_connection
from floppy_link import SerialLinkError
from playback.engine import PlaybackEngine


class Scanner:
    async def find_device_by_filter(self, predicate, **kwargs):
        device=SimpleNamespace(name=NAME)
        assert predicate(device, SimpleNamespace(local_name=NAME))
        return device


class Client:
    def __init__(self, device, disconnected_callback, **kwargs):
        self.disconnect_callback=disconnected_callback; self.sent=[]; self.line=b''
    async def __aenter__(self): return self
    async def __aexit__(self,*args): self.exited=True
    async def start_notify(self,uuid,callback):
        assert uuid==TX;self.callback=callback
    async def write_gatt_char(self,uuid,data,response):
        assert uuid==RX and len(data)<=20 and response
        self.sent.append(data);self.line+=data
        if self.line.endswith(b'\n'):
            command=self.line;self.line=b''
            if command==b'PING\n':
                self.callback(None,b'PO');self.callback(None,b'NG\r\n')
            if command==b'STATUS\n':
                self.callback(None,b'STATUS BEGIN\nSTATUS CTRL board=esp32 protocol=2 ready=1\nSTATUS FDD 1 enabled=1 homed=1 homing=0\nSTATUS END\n')


class BleTests(unittest.TestCase):
    def create(self):
        raw=BleBytes(scanner=Scanner(),client_factory=Client)
        self.addCleanup(raw.close)
        return raw,BleOrchestraLink(raw)
    def test_ping_uses_ble_notifications_and_no_boot_ready(self):
        raw,link=self.create()
        self.assertTrue(link.wait_boot(timeout=.1))
        self.assertEqual(link.board,'esp32')
        self.assertEqual(link.protocol_version,2)
        self.assertEqual(link.poll_lines(),[])
    def test_shared_status_parser_and_homing(self):
        raw,link=self.create()
        self.assertTrue(link.wait_homed(timeout=.1,echo=lambda _:None))
        self.assertEqual(link.device_status['FDD:1']['homed'],'1')
        self.assertEqual(raw._client.sent,[b'STATUS\n'])
    def test_fragmented_write_preserves_order_and_newline(self):
        raw,link=self.create()
        command='FDD 1 PLAY 220.123456789'
        link.send(command)
        self.assertEqual(b''.join(raw._client.sent),(command+'\n').encode())
    def test_disconnect_is_transport_error(self):
        raw,link=self.create()
        raw._loop.call_soon_threadsafe(raw._client.disconnect_callback,raw._client)
        raw._thread.join(timeout=1)
        with self.assertRaises(SerialLinkError):link.poll_lines()
        with self.assertRaises(SerialLinkError):link.send('PING')
    def test_close_stops_session(self):
        raw,link=self.create();link.close()
        self.assertFalse(raw._thread.is_alive())
    def test_not_found_surfaces_error(self):
        scanner=SimpleNamespace(find_device_by_filter=AsyncMock(return_value=None))
        with self.assertRaisesRegex(SerialLinkError,'Nie znaleziono'):
            BleBytes(scanner=scanner,client_factory=Client)
    def test_esp32_selects_ble_only_and_reports_connecting(self):
        serial=Mock();engine=PlaybackEngine(connect_fn=serial)
        engine._hardware.error='Previous Serial error'
        engine.set_controller_target('esp32')
        self.assertIsNone(engine.snapshot()['hardware']['error'])
        def fail():
            self.assertEqual(engine.snapshot()['hardware']['connectionStatus'],'connecting')
            raise SerialLinkError('not found')
        with patch('ble_link.BleOrchestraLink',side_effect=fail):
            self.assertFalse(engine.connect('/dev/should-not-open'))
        serial.assert_not_called()
        status=engine.snapshot()['hardware']
        self.assertEqual(status['controllerTarget'],'esp32')
        self.assertEqual(status['transport'],'ble')
        self.assertEqual(status['connectionStatus'],'disconnected')
    def test_switch_to_uno_keeps_existing_serial_factory(self):
        serial=Mock(side_effect=SerialLinkError('unplugged'))
        engine=PlaybackEngine(connect_fn=serial)
        engine.set_controller_target('esp32');engine.set_controller_target('uno')
        engine.connect('/dev/uno');serial.assert_called_once_with('/dev/uno')


class ReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_until_connected_and_again_after_disconnect(self):
        states=[(False,False),(False,False),(True,False),(False,False)]
        def snapshot():
            if not states:raise asyncio.CancelledError()
            connected,connecting=states.pop(0)
            return {'hardware':{'controllerTarget':'esp32','connected':connected,'connecting':connecting}}
        engine=SimpleNamespace(snapshot=snapshot);connect=AsyncMock()
        with self.assertRaises(asyncio.CancelledError):
            await maintain_ble_connection(engine,connect,interval=0)
        self.assertEqual(connect.await_count,3)
    async def test_no_retry_for_uno_homing_or_upload(self):
        for target,connected,connecting,allowed in [('uno',False,False,True),('esp32',True,True,True),('esp32',False,True,True),('esp32',False,False,False)]:
            engine=SimpleNamespace(snapshot=Mock(side_effect=[{'hardware':{'controllerTarget':target,'connected':connected,'connecting':connecting}},asyncio.CancelledError()]))
            connect=AsyncMock()
            with self.assertRaises(asyncio.CancelledError):
                await maintain_ble_connection(engine,connect,lambda:allowed,interval=0)
            connect.assert_not_awaited()

class SelectionPersistenceTests(unittest.TestCase):
    def test_settings_select_transport_and_restore_after_restart(self):
        import tempfile,json
        from fastapi.testclient import TestClient
        from web.server import create_app
        with tempfile.TemporaryDirectory() as directory:
            engine=PlaybackEngine()
            with patch.object(engine,'connect',return_value=False) as connect:
                with TestClient(create_app(midi_dir=Path(directory),engine=engine,connect_on_start=False)) as client:
                    with client.websocket_connect('/ws') as ws:
                        ws.receive_json()
                        ws.send_json({'action':'set_controller','target':'esp32'})
                        for _ in range(15):
                            packet=ws.receive_json()
                            if packet.get('state',{}).get('hardware',{}).get('controllerTarget')=='esp32':break
                        self.assertEqual(client.get('/api/state').json()['hardware']['transport'],'ble')
                    self.assertEqual(json.loads((Path(directory)/'.controller.json').read_text())['target'],'esp32')
            restored=PlaybackEngine()
            create_app(midi_dir=Path(directory),engine=restored,connect_on_start=False)
            self.assertEqual(restored.snapshot()['hardware']['controllerTarget'],'esp32')
