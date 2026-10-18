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
    def test_live_real_zero_stops_and_raise_restores_current_note(self):
        link=Link();self.app.real.attach(link)
        self.app.real.dispatch([ExecutionCommand(0,'pc-speaker-fx','tone',5,830)])
        link.sent.clear();timeline=self.app.player.timeline
        self.app.set_speaker_volume('pc-speaker-fx','REAL',0)
        self.assertEqual(link.sent,['VHS2 STOP'])
        self.app.set_speaker_volume('pc-speaker-fx','REAL',64)
        self.assertEqual(link.sent[-2:],['VHS2 AMP 64','VHS2 FREQ 830.00'])
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

    def test_only_pulse_is_accepted_and_saved_experiments_are_migrated(self):
        self.path.write_text(json.dumps({'vhs-1':{'waveform':'sine','volume':.8,'realAmplitude':22},'pc-speaker-fx':{'waveform':'sawtooth','volume':1,'realAmplitude':50}}))
        registry=DeviceRegistry(volume_path=self.path)
        self.assertEqual(registry.by_id['vhs-1']['waveform'],'pulse')
        self.assertEqual(registry.by_id['pc-speaker-fx']['waveform'],'pulse')
        self.assertEqual(registry.by_id['vhs-1']['realAmplitude'],22)
        self.assertEqual(registry.by_id['vhs-1']['volume'],.8)
        for wave in ('sine','triangle','sawtooth','noise'):
            with self.assertRaises(ValueError):self.app.set_speaker_waveform('vhs-1',wave)
        self.app.set_speaker_waveform('vhs-1','pulse')
        self.assertEqual(json.loads(self.path.read_text())['vhs-1']['waveform'],'pulse')

    def test_real_uses_pulse_even_when_previous_settings_selected_other_waves(self):
        link=Link();link.controller_status['speaker_waves']='1';self.app.real.attach(link)
        self.app.real.configured=True;link.sent.clear()
        self.app.real.dispatch([ExecutionCommand(0,'vhs-1','tone',1,440)])
        self.assertEqual(link.sent[:3],['VHS WAVE pulse','VHS AMP 50','VHS FREQ 440.00'])

    def test_zero_real_skips_tones_for_both_speakers_and_resumes_latest_pitch(self):
        link=Link();self.app.real.attach(link)
        for ident,prefix in [('vhs-1','VHS'),('pc-speaker-fx','VHS2')]:
            self.app.set_speaker_volume(ident,'REAL',0)
            link.sent.clear()
            self.app.real.dispatch([ExecutionCommand(0,ident,'tone',5,440),ExecutionCommand(1,ident,'tone',5,830)])
            self.assertEqual(link.sent,[prefix+' STOP',prefix+' STOP'])
            self.app.set_speaker_volume(ident,'REAL',128)
            self.assertEqual(link.sent[-2:],[prefix+' AMP 128',prefix+' FREQ 830.00'])
            self.app.real.stop_device(ident)
            link.sent.clear();self.app.set_speaker_volume(ident,'REAL',64)
            self.assertEqual(link.sent,[])

    def test_zero_sends_stop_even_when_idle_without_power_on(self):
        link=Link();self.app.real.attach(link);link.sent.clear()
        link.controller_status['atx']='OFF'
        self.app.set_speaker_volume('vhs-1','REAL',0)
        self.assertEqual(link.sent,['VHS STOP'])
        self.assertEqual(link.controller_status['atx'],'OFF')
