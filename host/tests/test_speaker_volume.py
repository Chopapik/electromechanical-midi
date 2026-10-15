import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime.registry import DeviceRegistry
from runtime.application import Application
from runtime.compiler import ExecutionCommand
from test_runtime import Link
from fastapi.testclient import TestClient
from web.server import create_app

class SpeakerVolumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'volumes.json'
        self.app=Application(DeviceRegistry(volume_path=self.path))
    def tearDown(self):self.temp.cleanup()
    def test_independent_levels_survive_registry_reload(self):
        self.app.set_speaker_volume('vhs-1','REAL',50)
        self.app.set_speaker_volume('pc-speaker-fx','REAL',22)
        self.app.set_speaker_volume('vhs-1','VIRTUAL',.2)
        self.app.set_speaker_volume('pc-speaker-fx','VIRTUAL',.7)
        r=DeviceRegistry(volume_path=self.path)
        self.assertEqual((r.by_id['vhs-1']['realAmplitude'],r.by_id['pc-speaker-fx']['realAmplitude']),(50,22))
        self.assertEqual((r.by_id['vhs-1']['volume'],r.by_id['pc-speaker-fx']['volume']),(.2,.7))
    def test_live_real_amp_without_restart_or_frequency_change(self):
        link=Link();self.app.real.attach(link)
        self.app.real.dispatch([ExecutionCommand(0,'pc-speaker-fx','tone',5,830)])
        link.sent.clear();timeline=self.app.player.timeline
        self.app.set_speaker_volume('pc-speaker-fx','REAL',0)
        self.assertEqual(link.sent,['VHS2 AMP 0'])
        self.app.set_speaker_volume('pc-speaker-fx','REAL',64)
        self.assertEqual(link.sent[-1],'VHS2 AMP 64')
        self.assertIs(self.app.player.timeline,timeline)
        link.sent.clear();self.app.set_speaker_volume('vhs-1','REAL',33)
        self.assertEqual(link.sent,[])  # No sound is started by changing an idle speaker.
        self.app.real.dispatch([ExecutionCommand(6,'pc-speaker-fx','stop')]);link.sent.clear()
        self.app.set_speaker_volume('pc-speaker-fx','REAL',50);self.assertEqual(link.sent,[])
    def test_invalid_levels_and_other_devices_do_not_save(self):
        for ident,output,value in [('fdd-1','VIRTUAL',.5),('missing','REAL',50),('vhs-1','REAL',129),('vhs-1','REAL',1.5),('vhs-1','REAL',True),('vhs-1','VIRTUAL',float('nan')),('vhs-1','VIRTUAL',-1),('vhs-1','VIRTUAL',2.6),('vhs-1','bad',50)]:
            with self.subTest(value=value),self.assertRaises(ValueError):self.app.set_speaker_volume(ident,output,value)
        self.assertFalse(self.path.exists())
    def test_websocket_saves_and_reports_volume_offline(self):
        with TestClient(create_app(runtime=self.app,midi_dir=self.temp.name,connect_on_start=False)) as client:
            with client.websocket_connect('/ws') as ws:
                ws.receive_json()
                ws.send_json({'action':'speaker_volume','requestId':'volume','deviceId':'pc-speaker-fx','output':'VIRTUAL','value':.25})
                while True:
                    message=ws.receive_json()
                    if message.get('requestId')=='volume':break
                self.assertEqual(message['type'],'ack')
                device=next(d for d in message['state']['devices'] if d['id']=='pc-speaker-fx')
                self.assertEqual(device['volume'],.25)
        self.assertEqual(json.loads(self.path.read_text())['pc-speaker-fx']['volume'],.25)

    def test_extended_virtual_gain_remains_valid_for_planning_and_reload(self):
        self.app.set_speaker_volume('vhs-1','VIRTUAL',2.5)
        self.app.set_speaker_volume('pc-speaker-fx','VIRTUAL',1.75)
        registry=DeviceRegistry(volume_path=self.path)
        self.assertEqual(registry.by_id['vhs-1']['volume'],2.5)
        config=registry.configuration()
        self.assertEqual(next(d for d in config.devices if d['id']=='vhs-1')['volume'],2.5)

    def test_waveforms_persist_independently_and_live_real_requires_new_firmware(self):
        link=Link();self.app.real.attach(link)
        self.app.real.dispatch([ExecutionCommand(0,'vhs-1','tone',5,220)])
        with self.assertRaisesRegex(Exception,'firmware'):self.app.set_speaker_waveform('vhs-1','sine')
        self.assertNotIn('waveform',self.app.registry.by_id['vhs-1'])
        link.controller_status['speaker_waves']='1';self.app.real.configured=True;link.sent.clear()
        self.app.set_speaker_waveform('vhs-1','sine')
        self.app.set_speaker_waveform('pc-speaker-fx','triangle')
        self.assertEqual(link.sent,['VHS WAVE sine','VHS2 WAVE triangle'])
        self.app.set_speaker_volume('vhs-1','VIRTUAL',1.75)
        registry=DeviceRegistry(volume_path=self.path)
        self.assertEqual(registry.by_id['vhs-1']['waveform'],'sine')
        self.assertEqual(registry.by_id['pc-speaker-fx']['waveform'],'triangle')
        with self.assertRaises(ValueError):registry.set_waveform('fdd-1','sine')
        with self.assertRaises(ValueError):registry.set_waveform('vhs-1','noise')

    def test_next_real_note_uses_waveform_changed_while_virtual(self):
        link=Link();link.controller_status['speaker_waves']='1';self.app.real.attach(link)
        self.app.real.configured=True;self.app.router.mode='VIRTUAL'
        self.app.set_speaker_waveform('vhs-1','sawtooth')
        link.sent.clear();self.app.router.mode='REAL'
        self.app.real.dispatch([ExecutionCommand(0,'vhs-1','tone',1,440)])
        self.assertEqual(link.sent[:3],['VHS WAVE sawtooth','VHS AMP 50','VHS FREQ 440.00'])
