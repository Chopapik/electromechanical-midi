"""Reusable application operations: no HTTP/WebSocket or physical transports."""
import unittest
from unittest.mock import patch

from runtime.application import Application
from runtime.compiler import ExecutionCommand, ExecutionTimeline
from runtime.outputs import OutputError


class ApplicationScenarioTests(unittest.TestCase):
    def setUp(self):
        self.app=Application()
        self.addCleanup(self.app.service.shutdown)
        self.now=100.
        self.app.player.clock=lambda:self.now
        self.app.timeline=ExecutionTimeline((ExecutionCommand(0,'fdd-1','tone',2,110),),2)
        self.app.player.load(self.app.timeline)
        self.app.switch_output('VIRTUAL')
        self.packets=[]
        def emit(message):
            self.packets.append(message)
            if message['type']=='audio_cancel':
                self.app.acknowledge_audio(message['owner'],message['token'])
        self.app.virtual.emit=emit

    def test_play_pause_seek_mute_and_stop_use_one_timeline(self):
        app=self.app
        app.play('browser')
        self.assertEqual(app.virtual.owner,'browser')
        self.assertEqual(app.player.state,'playing')
        self.now+=.2
        app.player.tick()
        self.assertTrue(any(p['type']=='audio' for p in self.packets))
        app.pause()
        position=app.player.base
        self.assertGreater(position,0)
        self.assertEqual(app.player.state,'paused')
        app.seek(.7)
        self.assertEqual(app.player.base,.7)
        self.assertEqual(app.player.state,'paused')
        app.mute('fdd-1',True)
        self.assertIn('fdd-1',app.router.muted)
        app.mute('fdd-1',False)
        app.stop()
        self.assertEqual(app.player.base,0)
        self.assertIs(app.player.timeline,app.timeline)
        self.assertFalse(app.real.sent)

    def test_other_browser_cannot_take_active_audio_or_laboratory(self):
        app=self.app
        app.play('first')
        self.now+=.2
        app.player.tick()
        with self.assertRaisesRegex(ValueError,'inną przeglądarkę'):
            app.play('other')
        app.stop()
        app.enter_laboratory('first')
        with self.assertRaisesRegex(ValueError,'inną przeglądarkę'):
            app.enter_laboratory('other')
        with self.assertRaisesRegex(ValueError,'tej przeglądarce'):
            app.test_laboratory('other','fdd-1',110,None)
        app.test_laboratory('first','fdd-1',110,None)
        self.assertEqual(app.virtual.owner,'first')
        self.assertIn('fdd-1',app.lab.jobs)
        app.stop_laboratory('first','fdd-1')
        app.leave_laboratory('first')
        self.assertIsNone(app.lab.session)
        self.assertEqual(app.player.owner,'orchestra')
        self.assertIs(app.player.timeline,app.timeline)

    def test_audio_error_checks_owner_output_and_epoch(self):
        app=self.app
        app.play('first')
        epoch=app.player.epoch
        app.audio_error('other',epoch,'ignored')
        app.audio_error('first',epoch-1,'ignored')
        self.assertEqual(app.player.state,'playing')
        app.audio_error('first',epoch,'x'*300)
        self.assertEqual(app.player.state,'stopped')
        self.assertEqual(app.player.error,'Web Audio: '+'x'*250)

    def test_service_busy_blocks_scenarios_without_transport_controller(self):
        app=self.app
        app.service.busy=True
        for operation in (
            lambda:app.play('browser'),app.pause,app.stop,lambda:app.seek(1),
            lambda:app.switch_output('REAL'),lambda:app.mute('fdd-1',True),
            lambda:app.audio_error('browser',0),lambda:app.enter_laboratory('browser'),
            lambda:app.leave_laboratory('browser'),lambda:app.test_laboratory('browser','fdd-1'),
            lambda:app.stop_laboratory('browser','fdd-1'),lambda:app.run_service('power_status'),
        ):
            with self.subTest(operation=operation),self.assertRaisesRegex(ValueError,'zajęty'):
                operation()
        self.assertEqual(app.router.mode,'VIRTUAL')
        app.service.busy=False

    def test_service_confirmation_and_return_value_are_delegated(self):
        with patch.object(self.app.service,'run',return_value={'ok':True}) as run:
            self.assertEqual(self.app.run_service('power_on',confirmed=True),{'ok':True})
            run.assert_called_once_with('power_on',confirmed=True)

    def test_disconnect_keeps_owner_until_stop_and_browser_lease_expire(self):
        app=self.app
        app.virtual.owner='browser'
        app.virtual.active=True
        observed=[]
        def stop():
            observed.append(('stop',app.virtual.owner))
            raise OutputError('No audio ACK')
        def wait(seconds):
            observed.append(('wait',app.virtual.owner,seconds))
        with patch.object(app.player,'stop',side_effect=stop),patch('runtime.application.time.sleep',side_effect=wait):
            app.disconnect('other')
            self.assertEqual(observed,[])
            app.disconnect('browser')
        self.assertEqual(observed,[('stop','browser'),('wait','browser',.6)])
        self.assertFalse(app.virtual.active)
        self.assertIsNone(app.virtual.owner)

    def test_background_lifecycle_obeys_output_and_connection_policy(self):
        app=self.app
        with patch.object(app.service,'refresh') as refresh,patch.object(app.service,'connect') as connect:
            app.refresh_connection(True)
            refresh.assert_called_once()
            connect.assert_not_called()
            app.router.mode='REAL'
            app.refresh_connection(False)
            connect.assert_not_called()
            app.refresh_connection(True)
            connect.assert_called_once()
        with patch.object(app.player,'close',side_effect=OutputError('STOP failed')),patch.object(app.service,'shutdown') as shutdown:
            app.close()
            shutdown.assert_called_once()
