"""Public catalog and checked command boundary, entirely without hardware."""
import json
import tempfile
import typing
import unittest

from fastapi.testclient import TestClient
from arrangement_presets import PRESETS, PRESET_IDS
from playback.orchestra import parse_policy
from runtime.application import Application
from web.contracts import COMMAND_ACTIONS, ClientCommand, validate_command
from web.server import create_app
from scripts.generate_preset_catalog import TARGET, render


class CommandContractTests(unittest.TestCase):
    def test_catalog_has_unique_complete_ids_and_browser_generation_is_current(self):
        self.assertEqual(len(PRESET_IDS), len(set(PRESET_IDS)))
        self.assertEqual({p.ui_order for p in PRESETS}, set(range(len(PRESETS))))
        self.assertEqual(TARGET.read_text(), render(), 'Run scripts/generate_preset_catalog.py')
        for preset in PRESETS:
            self.assertEqual(parse_policy({'arrangementPreset':preset.id})['arrangementPreset'], preset.id)
            self.assertTrue(preset.label)
            self.assertTrue(all(preset.descriptions))
        self.assertEqual(PRESET_IDS[0], 'balanced')
        self.assertEqual(PRESET_IDS[-1], 'universal')

    def test_every_typed_action_has_runtime_validation(self):
        actions = set()
        for variant in typing.get_args(ClientCommand):
            actions.update(typing.get_args(typing.get_type_hints(variant)['action']))
        self.assertEqual(actions, COMMAND_ACTIONS)

    def test_valid_commands_keep_wire_fields_and_defaults_unmodified(self):
        commands = [
            *({'action':action} for action in ('play','pause','stop','lab_enter','lab_leave')),
            {'action':'set_file','file':'test.mid','requestId':'r','future':42},
            {'action':'arrangement_preset','preset':'adaptive_legato'},
            {'action':'seek','position':2.1}, {'action':'output','mode':'VIRTUAL'},
            {'action':'mute','deviceId':'fdd-1','muted':True},
            {'action':'speaker_waveform','deviceId':'vhs-1','waveform':'pulse'},
            {'action':'speaker_volume','deviceId':'vhs-1','output':'REAL','value':50},
            {'action':'lab_test','deviceId':'fdd-1'},
            {'action':'lab_update','deviceId':'fdd-1','duration':None,'modulation':{'mode':'sine','depth':2,'period':4}},
            {'action':'lab_stop','deviceId':'fdd-1'},
            {'action':'service','operation':'power_on','confirmed':True},
            {'action':'audio_error','epoch':3,'message':'failed'},
            {'action':'audio_ack','token':'cancel'}, {'action':'sync','sent':2.5},
        ]
        for command in commands:
            with self.subTest(command=command):
                before = json.dumps(command)
                self.assertIs(validate_command(command), command)
                self.assertEqual(json.dumps(command), before)

    def test_invalid_values_are_rejected_before_dispatch(self):
        for command in (
            None, [], 'stop', {}, {'action':[]}, {'action':'missing'},
            {'action':'set_file'}, {'action':'seek','position':True},
            {'action':'seek','position':float('nan')}, {'action':'sync','sent':float('inf')},
            {'action':'stop','requestId':[]},
            {'action':'mute','deviceId':'fdd-1','muted':'false'},
            {'action':'speaker_volume','deviceId':'vhs-1','output':'REAL','value':False},
            {'action':'lab_test','deviceId':'fdd-1','modulation':[]},
            {'action':'lab_test','deviceId':'fdd-1','hz':'200'},
            {'action':'audio_ack','token':{}},
            {'action':'service','operation':'power_on','confirmed':1},
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                validate_command(command)
        with self.assertRaisesRegex(ValueError, 'Unknown arrangement preset'):
            validate_command({'action':'arrangement_preset','preset':'missing'})
        with self.assertRaisesRegex(ValueError, "'file'"):
            validate_command({'action':'set_file'})

    @staticmethod
    def response(ws, request):
        for _ in range(80):
            message = ws.receive_json()
            if message.get('type') in ('ack', 'error') and message.get('requestId') == request:
                return message
        raise AssertionError('No correlated response')

    def test_malformed_socket_messages_do_not_disconnect_or_dispatch(self):
        app = Application()
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(
                midi_dir=directory, runtime=app, connect_on_start=False)) as client:
            with client.websocket_connect('/ws') as ws:
                self.assertEqual(ws.receive_json()['type'], 'hello')
                for raw in ('{', 'null', '[]', '"stop"'):
                    ws.send_text(raw)
                    self.assertEqual(self.response(ws, None)['type'], 'error')
                for command in (
                    {'action':'missing','requestId':'unknown'},
                    {'action':'seek','position':False,'requestId':'type'},
                    {'action':'set_file','requestId':'missing'},
                    {'action':'arrangement_preset','preset':'missing','requestId':'preset'},
                ):
                    ws.send_json(command)
                    response = self.response(ws, command['requestId'])
                    self.assertEqual(response['type'], 'error')
                    self.assertEqual(set(response), {'type','requestId','message'})
                ws.send_json({'action':'output','mode':'VIRTUAL','requestId':'valid'})
                response = self.response(ws, 'valid')
                self.assertEqual(response['type'], 'ack')
                self.assertEqual(response['state']['output']['mode'], 'VIRTUAL')
                self.assertFalse(app.real.sent)

    def test_sync_and_audio_ack_are_not_blocked_by_pending_stop(self):
        app = Application()
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(
                midi_dir=directory, runtime=app, connect_on_start=False)) as client:
            with client.websocket_connect('/ws') as ws:
                owner = ws.receive_json()['session']
                app.router.mode = 'VIRTUAL'
                app.virtual.owner = owner
                app.virtual.active = True
                ws.send_json({'action':'stop','requestId':'stop'})
                for _ in range(80):
                    message = ws.receive_json()
                    if message['type'] == 'audio_cancel':
                        break
                else:
                    self.fail('No audio cancellation')
                ws.send_json({'action':'sync','sent':123.5})
                for _ in range(80):
                    synced = ws.receive_json()
                    if synced['type'] == 'sync':
                        break
                else:
                    self.fail('Sync was queued behind STOP')
                self.assertEqual(synced['sent'], 123.5)
                ws.send_json({'action':'audio_ack','token':message['token']})
                self.assertEqual(self.response(ws, 'stop')['type'], 'ack')
                self.assertFalse(app.virtual.active)
