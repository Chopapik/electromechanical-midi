"""Output selection must not queue behind offline MIDI planning."""
import threading
import tempfile
import unittest
from unittest.mock import patch
from test_runtime import Application, Link, ROOT, create_app, TestClient


class OutputDuringPlanningTests(unittest.TestCase):
    def test_switch_during_planning_still_requires_real_stop_confirmation(self):
        for connected, fail_stop in ((False,False),(True,False),(True,True)):
            with self.subTest(connected=connected,fail_stop=fail_stop):
                app=Application()
                if connected:
                    link=Link();app.real.attach(link);link.fail_stop=fail_stop
                started=threading.Event();release=threading.Event();finished=threading.Event()
                original=app.load
                def slow_load(path):
                    started.set()
                    if not release.wait(5): raise RuntimeError('test release timeout')
                    try: original(path)
                    finally: finished.set()
                # Failure on the old serialized handler is bounded, not a hung test.
                fallback=threading.Timer(3,release.set)
                with tempfile.TemporaryDirectory() as directory, patch.object(app,'load',side_effect=slow_load), TestClient(create_app(midi_dir=directory,runtime=app,connect_on_start=False)) as client:
                    result=client.post('/api/files',files={'file':('test.mid',(ROOT/'midi/test.mid').read_bytes(),'audio/midi')})
                    with client.websocket_connect('/ws') as ws:
                        ws.receive_json()
                        fallback.start()
                        try:
                            ws.send_json({'action':'set_file','file':result.json()['name'],'requestId':'load'})
                            self.assertTrue(started.wait(1))
                            ws.send_json({'action':'output','mode':'VIRTUAL','requestId':'output'})
                            while True:
                                response=ws.receive_json()
                                if response.get('requestId')=='output': break
                            self.assertFalse(finished.is_set(),'Output switch waited for MIDI planning')
                            if fail_stop:
                                self.assertEqual(response['type'],'error')
                                self.assertIn('STOP',response['message'])
                                self.assertEqual(app.router.mode,'REAL')
                                self.assertTrue(app.real.unknown)
                            else:
                                self.assertEqual(response['type'],'ack')
                                self.assertEqual(response['state']['output']['mode'],'VIRTUAL')
                                self.assertEqual(response['state']['state'],'stopped')
                                if connected:self.assertIn('ALL STOP token',link.sent)
                            release.set()
                            while True:
                                message=ws.receive_json()
                                if message.get('requestId')=='load': break
                            if not fail_stop:
                                self.assertEqual(message['type'],'ack')
                                self.assertEqual(message['state']['output']['mode'],'VIRTUAL')
                                self.assertEqual(message['state']['state'],'stopped')
                            else:self.assertEqual(message['type'],'error')
                        finally:
                            release.set();fallback.cancel()

    def test_service_exclusivity_still_blocks_output_changes(self):
        app=Application();app.service.busy=True
        with TestClient(create_app(runtime=app,connect_on_start=False)) as client:
            with client.websocket_connect('/ws') as ws:
                ws.receive_json();ws.send_json({'action':'output','mode':'VIRTUAL','requestId':'output'})
                while True:
                    message=ws.receive_json()
                    if message.get('requestId')=='output':break
                self.assertEqual(message['type'],'error')
                self.assertIn('zajęty',message['message'])
                self.assertEqual(app.router.mode,'REAL')
        app.service.busy=False
