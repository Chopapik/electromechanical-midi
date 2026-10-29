"""Offline concurrency regressions: planning, STOP, group gates and diagnostics."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from runtime.application import Application
from runtime.compiler import ExecutionCommand, ExecutionTimeline
from web.server import create_app


class ResponsivenessTests(unittest.TestCase):
    def setUp(self):
        self.app=Application()
        self.addCleanup(self.app.service.shutdown)
        self.app.source=SimpleNamespace(path=Path('test.mid'))
        self.app.timeline=ExecutionTimeline((ExecutionCommand(0,'fdd-1','tone',1,110),),1)
        self.app.player.load(self.app.timeline)

    def test_planning_releases_player_lock_and_stop_discards_result(self):
        app=self.app
        entered=threading.Event(); release=threading.Event()
        old=app.timeline; revision=app.revision
        preset=app.registry.document.get('parameters',{}).get('arrangementPreset','balanced')
        def arrange(source,registry):
            self.assertEqual(registry.document['parameters']['arrangementPreset'],'fdd_legato')
            entered.set()
            if not release.wait(3): raise AssertionError('planning test timed out')
            return object()
        with ThreadPoolExecutor(3) as pool, patch('runtime.application.arrange',side_effect=arrange):
            future=pool.submit(app.set_preset,'fdd_legato')
            try:
                self.assertTrue(entered.wait(1))
                state=pool.submit(app.snapshot).result(timeout=1)
                self.assertEqual(state['planning']['stage'],'planning')
                self.assertEqual(state['arrangementPreset'],preset)
                pool.submit(app.stop).result(timeout=1)
            finally: release.set()
            with self.assertRaisesRegex(ValueError,'anulowane'): future.result(timeout=1)
        self.assertIs(app.timeline,old)
        self.assertEqual(app.revision,revision)
        self.assertIsNone(app.planning)

    def test_failed_planning_retains_preset_and_previous_plan(self):
        app=self.app
        old=app.timeline
        preset=app.snapshot()['arrangementPreset']
        with patch('runtime.application.arrange',side_effect=ValueError('bad plan')):
            with self.assertRaisesRegex(ValueError,'bad plan'):app.set_preset('fdd_legato')
        self.assertIs(app.timeline,old)
        self.assertEqual(app.snapshot()['arrangementPreset'],preset)
        self.assertIsNone(app.planning)

    def test_group_mute_validates_before_changes_and_closes_all_gates_on_failure(self):
        app=self.app
        with self.assertRaises(ValueError):app.mute_group(['fdd-1','missing'],True)
        self.assertFalse(app.router.muted)
        with patch.object(app.real,'stop_device',side_effect=RuntimeError('STOP failed')):
            with self.assertRaisesRegex(RuntimeError,'STOP failed'):
                app.mute_group(['fdd-1','fdd-2','fdd-3','fdd-4'],True)
        self.assertEqual(app.router.muted,{'fdd-1','fdd-2','fdd-3','fdd-4'})
        self.assertEqual(app.player.state,'stopped')
        app.mute_group(['fdd-1','fdd-2'],False)
        self.assertEqual(app.router.muted,{'fdd-3','fdd-4'})

    def test_failure_keeps_original_context_after_stop(self):
        app=self.app
        app.player.context={'file':'badapple.mid','preset':'fdd_legato'}
        with patch.object(app.real,'poll',side_effect=RuntimeError('BLE realtime overrun: stale commands')):
            app.player.tick()
        app.stop()
        self.assertIsNone(app.player.error)
        self.assertEqual(app.snapshot()['lastFailure']['code'],'ble_overrun')
        self.assertEqual(app.player.failure['context']['file'],'badapple.mid')

    def test_websocket_stop_overtakes_planning_and_cancels_queued_play(self):
        app=self.app
        entered=threading.Event(); release=threading.Event()
        def arrange(*args):
            entered.set()
            if not release.wait(3):raise AssertionError('planning test timed out')
            return object()
        with patch('runtime.application.arrange',side_effect=arrange):
            with TestClient(create_app(runtime=app,connect_on_start=False)) as client:
                with client.websocket_connect('/ws') as ws:
                    ws.send_json({'action':'arrangement_preset','preset':'fdd_legato','requestId':'plan'})
                    try:
                        self.assertTrue(entered.wait(1))
                        ws.send_json({'action':'play','requestId':'play'})
                        ws.send_json({'action':'stop','requestId':'stop'})
                        while True:
                            message=ws.receive_json()
                            if message.get('requestId')=='stop':break
                        self.assertEqual(message['type'],'ack')
                        self.assertFalse(release.is_set())
                    finally:release.set()
                    responses={}
                    while len(responses)<2:
                        message=ws.receive_json()
                        if message.get('requestId') in ('plan','play'):responses[message['requestId']]=message
                    self.assertEqual(responses['plan']['type'],'error')
                    self.assertEqual(responses['play']['type'],'error')
                    self.assertEqual(app.player.state,'stopped')

    def test_homing_timeout_names_only_devices_still_unconfirmed(self):
        from test_runtime import Link
        app=self.app;link=Link()
        app.real.attach(link)
        app.real.homing_devices=('fdd-1','fdd-2')
        app.real.homing_deadline=110
        app.real.homing_status_pending=True
        app.real.homing_status_requirements=(True,False)
        app.real.homing_status_generation=(0,0)
        app.real.homing_query_after=105
        link.status_generation=1
        link.device_status['FDD:2']['homed']='0'
        with patch('runtime.outputs.time.monotonic',return_value=100):
            self.assertFalse(app.real.homing_ready())
        self.assertEqual(app.real.homing_devices,('fdd-2',))
        with patch('runtime.outputs.time.monotonic',return_value=111):
            with self.assertRaisesRegex(Exception,'TRACK0') as caught:app.real.homing_ready()
        self.assertIn(app.registry.by_id['fdd-2']['name'],str(caught.exception))
        self.assertNotIn(app.registry.by_id['fdd-1']['name'],str(caught.exception))
