"""ATX logical state and upload barriers; fake transports and PlatformIO only."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_runtime
import test_orchestra_link
from runtime.application import Application
from runtime.outputs import OutputError
from runtime.compiler import ExecutionCommand
from fastapi.testclient import TestClient
from web.server import create_app

class AtxTests(unittest.TestCase):
    def app(self):
        app=Application();self.addCleanup(app.service.shutdown)
        app.service.power_off_delay=0
        link=test_runtime.Link();app.real.attach(link)
        return app,link

    def port(self): return [SimpleNamespace(vid=0x10c4,device='/dev/cu.usbserial-mock')]

    def test_power_confirmation_ignores_stale_token_and_validates_gpio(self):
        link=test_orchestra_link.ProtocolTests().link()
        link.controller_status={'atx':'ON'}
        link.poll_lines=Mock(side_effect=[['POWER OFF gpio19=0 token=7'],['POWER OFF gpio19=1 token=42'],['POWER OFF gpio19=0 token=42']])
        with patch('orchestra_link.time.monotonic_ns',return_value=42): self.assertEqual(link.power('OFF'),'OFF')
        link.send.assert_called_once_with('POWER OFF 42')
        self.assertEqual(link.poll_lines.call_count,3)
        self.assertEqual(link.controller_status['atx'],'OFF')

    def test_missing_ack_and_transport_failure_are_unknown(self):
        for failure in (None,OSError('BLE lost')):
            link=test_orchestra_link.ProtocolTests().link();link.controller_status={'atx':'ON'}
            link.poll_lines=Mock(return_value=[],side_effect=failure)
            with self.assertRaises((RuntimeError,OSError)):link.power('OFF',timeout=.01)
            self.assertEqual(link.controller_status['atx'],'UNKNOWN')

    def test_on_off_status_and_no_restore_of_playback(self):
        app,link=self.app()
        for confirmed in (False,'true',1):
            with self.assertRaisesRegex(OutputError,'potwierdzenia'): app.service.run('power_on',confirmed=confirmed)
        app.service.run('power_off');self.assertEqual(app.service.status()['power']['state'],'OFF')
        app.service.run('power_on',confirmed=True);self.assertEqual(app.service.status()['power']['state'],'ON')
        self.assertEqual(app.service.run('power_status')['power'],'ON')
        self.assertEqual(app.player.state,'stopped');self.assertFalse(app.service.status()['power']['measured'])
        self.assertFalse(any('PLAY' in s or 'HOME' in s for s in link.sent))
        self.assertLess(link.sent.index('ALL STOP token'),link.sent.index('POWER OFF'))

    def test_off_unknown_unavailable_block_real_but_not_virtual_or_stops(self):
        app,link=self.app()
        command=ExecutionCommand(0,'fdd-1','tone',1,220)
        for state in ('OFF','UNKNOWN',None):
            if state:link.controller_status['atx']=state
            else:link.controller_status.pop('atx',None)
            with self.assertRaisesRegex(OutputError,'ATX'):app.real.ready([command])
            with self.assertRaisesRegex(OutputError,'ATX'):app.real.dispatch([command])
            app.real.dispatch([ExecutionCommand(0,'fdd-1','stop')])
            with self.assertRaisesRegex(OutputError,'ATX'):app.service.run('home')
        app.virtual.owner='browser';app.virtual.ready([command]);app.virtual.dispatch([command],epoch=1)

    def test_disconnect_unknown_and_old_firmware_unavailable(self):
        app,link=self.app();app.real.lost('BLE lost')
        self.assertEqual(app.service.status()['power']['state'],'UNKNOWN')
        self.assertFalse(app.service.status()['power']['available'])
        old=test_runtime.Link();old.controller_status.pop('atx');old.power=Mock(side_effect=RuntimeError('Firmware bez POWER'))
        app.real.attach(old)
        self.assertEqual(app.service.status()['power']['state'],'UNAVAILABLE')
        with patch('runtime.device_service.run_firmware') as uploader:
            with self.assertRaisesRegex(OutputError,'bez POWER'):app.service.run('firmware')
            uploader.assert_not_called()

    def test_upload_requires_ble_and_fresh_off_ack_before_any_build(self):
        for failure in ('offline','timeout','wrong_ack','stop_timeout'):
            app,link=self.app()
            if failure=='offline':app.real.link=None
            elif failure=='timeout':link.power=Mock(side_effect=RuntimeError('Brak potwierdzenia POWER OFF'))
            elif failure=='wrong_ack':link.power=Mock(return_value='ON')
            else:link.fail_stop=True
            with patch('runtime.device_service.run_firmware') as uploader:
                with self.assertRaises(Exception):app.service.run('firmware')
                uploader.assert_not_called()
            if failure not in ('offline',):self.assertFalse(link.closed)
            self.assertEqual(app.service.status()['firmware']['flash'],'failed')

    def test_upload_order_success_and_build_or_upload_error(self):
        for fail_stage in (None,'build','upload'):
            app,link=self.app();app.service.restart_delay=60
            order=[]
            original_power=link.power
            def power(action):order.append('power_'+action);return original_power(action)
            link.power=power
            original_close=link.close
            def close():order.append('close');original_close()
            link.close=close
            def upload(_tool,port=None,**kwargs):
                stage='upload' if port else 'build';order.append(stage)
                self.assertEqual(app.player.owner,'service');self.assertIsNone(app.real.link)
                self.assertEqual(link.controller_status['atx'],'OFF')
                if stage==fail_stage:raise RuntimeError(stage+' failed')
                return 'ok'
            with patch('runtime.device_service.scan_ports',side_effect=self.port),patch('runtime.device_service.platformio',return_value='pio'),patch('runtime.device_service.run_firmware',side_effect=upload),patch('runtime.device_service.time.sleep',side_effect=lambda _:order.append('wait')):
                if fail_stage:
                    with self.assertRaisesRegex(RuntimeError,'failed'):app.service.run('firmware')
                else:app.service.run('firmware')
            self.assertEqual(order[:4],['power_OFF','wait','close','build'])
            self.assertNotIn('POWER ON',link.sent)
            self.assertEqual(app.service.status()['firmware']['flash'],'failed' if fail_stage else 'success')

    def test_busy_and_connecting_block_power_without_sending(self):
        app,link=self.app();before=list(link.sent)
        for flag in ('busy','connecting'):
            setattr(app.service,flag,True)
            for operation in ('power_on','power_off','firmware'):
                with self.assertRaisesRegex(OutputError,'zajęty'):app.service.run(operation,confirmed=True)
            setattr(app.service,flag,False)
        self.assertEqual(before,link.sent)

    def test_reconnect_reads_off_without_power_on(self):
        app,old=self.app();app.real.link=None
        link=test_runtime.Link();link.controller_status['atx']='OFF'
        app.service.connect_fn=lambda:link
        self.assertTrue(app.service.connect())
        self.assertIn('POWER STATUS',link.sent);self.assertNotIn('POWER ON',link.sent)
        self.assertEqual(app.service.status()['power']['state'],'OFF')
        self.assertEqual(app.player.state,'stopped')

    def test_manual_off_still_tries_atomic_off_if_separate_stop_ack_is_lost(self):
        app,link=self.app();link.fail_stop=True
        self.assertEqual(app.service.run('power_off')['power'],'OFF')
        self.assertFalse(app.real.unknown)
        self.assertTrue(all(v['homed']=='0' for k,v in link.device_status.items() if k.startswith('FDD:')))

    def test_recovery_after_flash_confirms_off_and_refuses_missing_power_support(self):
        for supported in (True,False):
            app,old=self.app();app.real.link=None
            app.service.firmware_state.update(flash='success',ble='connecting')
            link=test_runtime.Link()
            if not supported:link.controller_status.pop('atx')
            app.service.connect_fn=lambda:link
            self.assertEqual(app.service.connect(),supported)
            self.assertNotIn('POWER ON',link.sent)
            if supported:
                self.assertEqual(app.service.status()['power']['state'],'OFF')
                self.assertEqual(link.sent[:2],['POWER STATUS','POWER OFF'])
            else:
                self.assertIsNone(app.real.link);self.assertTrue(link.closed)

    def test_http_websocket_origin_and_confirmation_restrict_power(self):
        app,link=self.app()
        with tempfile.TemporaryDirectory() as tmp,TestClient(create_app(midi_dir=tmp,runtime=app,connect_on_start=False),base_url='http://localhost',headers={'Host':'localhost'}) as client:
            for origin,confirmed,ok in [(None,True,False),('https://evil.example',True,False),('http://localhost:9999',True,False),('http://localhost',False,False),('http://localhost',True,True)]:
                with client.websocket_connect('/ws',headers={'Origin':origin} if origin else {}) as ws:
                    ws.send_json({'action':'service','operation':'power_on','confirmed':confirmed,'requestId':'power'})
                    while True:
                        result=ws.receive_json()
                        if result.get('requestId')=='power':break
                    self.assertEqual(result['type'],'ack' if ok else 'error')
