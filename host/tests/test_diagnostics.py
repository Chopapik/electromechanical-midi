"""Persistent diagnostics under crashes, disk errors and queue pressure; no hardware."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from diagnostics import Diagnostics, clean
from fastapi.testclient import TestClient
from runtime.application import Application
from web.server import create_app


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)

    def recorder(self,**kwargs):
        d=Diagnostics(self.path,**kwargs);d.start();self.addCleanup(d.close);return d

    def test_incident_retains_context_trace_and_survives_restart(self):
        d=self.recorder();d.record('command_requested',{'file':'BadApple.mid'})
        try:raise ValueError('queue overrun')
        except ValueError as exc:ident=d.incident('playback_failure',context={'position':12.5},error=exc)
        d.wait_saved(ident);d.close()
        self.assertFalse((self.path/'active.json').exists())
        restored=self.recorder();report=restored.read_incident(ident)
        self.assertEqual(restored.status()['lastIncident'],ident)
        self.assertIn('ValueError: queue overrun',report['data']['traceback'])
        self.assertEqual(report['data']['context']['position'],12.5)
        self.assertIn('command_requested',[r['kind'] for r in report['recent']])
        with self.assertRaises(ValueError):restored.read_incident('../active')

    def test_real_abrupt_process_exit_detected_next_start(self):
        script="from diagnostics import Diagnostics; import os,sys; d=Diagnostics(sys.argv[1]); d.start(); d.record('before_crash'); d.events.join(); os._exit(7)"
        result=subprocess.run([sys.executable,'-c',script,str(self.path)],timeout=5)
        self.assertEqual(result.returncode,7)
        d=self.recorder();d.incidents.join()
        report=d.read_incident(d.status()['lastIncident'])
        self.assertEqual(report['kind'],'unclean_shutdown')
        self.assertNotEqual(report['data']['context']['previousSession']['session'],d.session)

    def test_rotation_and_incident_retention(self):
        d=self.recorder(max_bytes=700,backups=2,keep_incidents=3)
        for n in range(10):
            d.record('test',{'n':n,'payload':'x'*400})
            ident=d.incident('test',context={'n':n});d.wait_saved(ident)
        d.close()
        self.assertLessEqual(len(list(self.path.glob('events*.jsonl'))),3)
        self.assertEqual(len(list(self.path.glob('incident-*.json'))),3)
        self.assertEqual(d.read_incident(ident)['data']['context']['n'],9)

    def test_slow_disk_does_not_block_producer_and_overflow_visible(self):
        entered=threading.Event();release=threading.Event()
        d=Diagnostics(self.path,capacity=2)
        original=d._write
        def blocked(entry):
            entered.set();release.wait(3);original(entry)
        with patch.object(d,'_write',side_effect=blocked):
            d.start()
            try:
                self.assertTrue(entered.wait(1))
                for _ in range(20):d.record('test')
                self.assertGreater(d.status()['droppedEvents'],0)
                self.assertIsNotNone(d.incident('failure'))
            finally:release.set();d.close()
        self.assertTrue(list(self.path.glob('incident-*.json')))

    def test_disk_failure_is_visible_and_keeps_unclean_marker(self):
        d=self.recorder();d.events.join()
        with patch.object(d,'_write',side_effect=OSError('disk full')):
            d.record('test');d.events.join()
            self.assertIn('disk full',d.status()['error'])
        d.close();self.assertTrue((self.path/'active.json').exists())

    def test_sensitive_fields_and_text_redacted(self):
        result=json.dumps(clean({'api_key':'sensitive','message':'password=hidden Bearer abc123',
            'trace':'-----BEGIN PRIVATE KEY-----\nxyz\n-----END PRIVATE KEY-----'}))
        for secret in ('sensitive','hidden','abc123','xyz'):self.assertNotIn(secret,result)

    def test_browser_report_is_durable_before_ack_and_readable_via_api(self):
        runtime=Application()
        app=create_app(runtime=runtime,connect_on_start=False,diagnostics_dir=self.path)
        with TestClient(app) as client:
            with client.websocket_connect('/ws') as ws:
                ws.send_json({'action':'client_error','requestId':'report-1','kind':'error','message':'synthetic offline test'})
                for _ in range(30):
                    response=ws.receive_json()
                    if response.get('requestId')=='report-1':break
                self.assertEqual(response['type'],'ack',response)
                status=client.get('/api/diagnostics').json()
                report=client.get('/api/diagnostics/incidents/'+status['lastIncident'])
                self.assertEqual(report.status_code,200)
                self.assertEqual(report.json()['kind'],'browser_failure')
                self.assertEqual(client.get('/api/diagnostics/incidents/invalid').status_code,404)
