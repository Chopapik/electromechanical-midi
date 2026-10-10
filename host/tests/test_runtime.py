"""New runtime contracts; fake transport and clock only, never physical hardware."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from midi_source import MidiSource
from runtime.application import Application
from runtime.arranger import arrange
from runtime.compiler import ExecutionCommand as C, ExecutionTimeline as T, compile_plan
from runtime.registry import DeviceRegistry
from runtime.outputs import OutputError
from runtime.player import Player
from web.server import create_app
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[2]

class Link:
    def __init__(self):
        self.sent=[];self.closed=False;self.fail_stop=False;self.fail_write=False
        self.controller_status={'stop_ack':'1','hardware_profiles':'1','strict_tracks':'1'}
        self.device_status={d['lane'].upper() if d['type']!='VHS' else 'VHS':{'enabled':'1','homed':'1','homing':'0'} for d in DeviceRegistry().devices}
        self.lines=[]
    def send_batch(self, lines):
        if self.fail_write: raise OSError('BLE lost')
        self.sent.extend(lines)
    def all_stop_confirmed(self):
        self.sent.append('ALL STOP token')
        if self.fail_stop: raise OSError('no STOPPED')
        return True
    def all_stop(self): self.sent.append('ALL STOP')
    def status(self): self.lines.append('STATUS END')
    def poll_lines(self): result,self.lines=self.lines,[];return result
    def ping(self): pass
    def wait_boot(self,**_): return True
    def wait_homed(self,**_): return True
    def close(self): self.closed=True

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.app=Application();self.now=100.
        self.player=Player(self.app.router,clock=lambda:self.now)
        self.app.player=self.player;self.app.lab.player=self.player;self.app.service.player=self.player
        self.link=Link()
    def real(self):
        self.app.real.attach(self.link);self.app.real.configured=True
    def virtual(self):
        self.player.switch('VIRTUAL');self.app.virtual.owner='browser'
        self.packets=[]
        def emit(m):
            self.packets.append(m)
            if m['type']=='audio_cancel':self.app.virtual.acknowledge('browser',m['token'])
        self.app.virtual.emit=emit
    def timeline(self):
        self.player.load(T((C(0,'fdd-1','tone',1,220),C(1,'fdd-1','stop'),C(2,'fdd-1','tone',1,250),C(3,'fdd-1','stop')),3))
    def test_real_seek_continues_current_note_after_confirmed_stop(self):
        self.real();self.timeline();self.player.play();self.player.tick();self.now+=.3
        epoch=self.player.epoch;self.link.sent.clear();self.player.seek(2.4)
        self.assertEqual(self.player.state,'playing');self.assertAlmostEqual(self.player.position(),2.4)
        self.assertGreater(self.player.epoch,epoch)
        self.assertIn('STOP',self.link.sent[0]);self.assertTrue(any('250' in line for line in self.link.sent))
        self.assertFalse(any('220' in line for line in self.link.sent))
        self.now+=.1;self.assertAlmostEqual(self.player.position(),2.5)
    def test_virtual_seek_cancels_old_epoch_and_continues_in_both_directions(self):
        self.virtual();self.timeline();self.player.play();self.player.tick();self.now+=.3
        for target in (2.3,.4):
            self.packets.clear();epoch=self.player.epoch;self.player.seek(target)
            self.assertEqual(self.player.state,'playing');self.assertAlmostEqual(self.player.base,target)
            self.assertEqual(self.packets[0]['type'],'audio_cancel')
            audio=[m for m in self.packets if m['type']=='audio']
            self.assertEqual(len(audio),1);self.assertGreater(audio[0]['epoch'],epoch)
            self.assertAlmostEqual(audio[0]['commands'][0]['time'],target)
            self.assertAlmostEqual(audio[0]['commands'][0]['duration'],(3 if target>2 else 1)-target)
    def test_seek_retains_pause_or_stopped_state_and_does_not_play_offline(self):
        self.timeline();self.player.seek(.4)
        self.assertEqual(self.player.state,'stopped');self.assertAlmostEqual(self.player.position(),.4)
        self.player.state='paused';self.player.seek(2.2)
        self.assertEqual(self.player.state,'paused');self.assertAlmostEqual(self.player.position(),2.2)
        self.assertEqual(self.link.sent,[])
    def test_seek_to_end_does_not_restart_from_beginning(self):
        self.real();self.timeline();self.player.play();self.player.tick();self.link.sent.clear()
        self.player.seek(99)
        self.assertEqual(self.player.state,'stopped');self.assertEqual(self.player.position(),3)
        self.assertFalse(any('PLAY' in line for line in self.link.sent))
    def test_seek_does_not_resume_if_stop_confirmation_fails(self):
        self.real();self.timeline();self.player.play();self.player.tick();self.link.fail_stop=True
        self.link.sent.clear()
        with self.assertRaises(OutputError):self.player.seek(2.4)
        self.assertNotEqual(self.player.state,'playing');self.assertTrue(self.app.real.unknown)
        self.assertFalse(any('PLAY' in line for line in self.link.sent))

    def test_default_real_offline_no_fallback_and_no_auto_play(self):
        self.timeline()
        with self.assertRaisesRegex(OutputError,'Brak połączenia'):self.player.play()
        self.assertEqual(self.app.router.mode,'REAL');self.assertEqual(self.player.state,'stopped')
        self.real();self.player.tick();self.assertFalse(any('PLAY' in s for s in self.link.sent))
    def test_planning_identical_offline_real_virtual_and_no_transport(self):
        source=MidiSource(ROOT/'midi/test.mid');before=arrange(source,self.app.registry).as_dict()
        self.real();connected=arrange(source,self.app.registry).as_dict()
        self.virtual();virtual=arrange(source,self.app.registry).as_dict()
        self.assertEqual(before,connected);self.assertEqual(before,virtual)
        self.assertTrue(any(e['outcome']!='DROPPED' for e in before['events']))
    def test_registry_is_shared_and_calibration_references_are_retained(self):
        self.assertIs(self.app.lab.registry,self.app.registry)
        self.assertEqual(len(self.app.registry.catalog()),15)
        self.assertEqual(self.app.registry.profile('fdd-1').get('musicalHz'),[200,410])
        self.assertEqual(self.app.registry.profile('DVD_STEPPER_1').get('allowedBandsHz'),[[50.0,120.0],[180.0,190.0],[270.0,300.0],[340.0,470.0]])
    def test_compilation_is_deterministic_and_contains_only_device_ids(self):
        plan=arrange(MidiSource(ROOT/'midi/test.mid'),self.app.registry)
        before=copy.deepcopy(plan.as_dict());a=compile_plan(plan);b=compile_plan(plan)
        self.assertEqual(a,b);self.assertEqual(before,plan.as_dict())
        self.assertTrue(all(c.device_id in self.app.registry.by_id for c in a.commands))
        self.assertEqual([c.time for c in a.commands],sorted(c.time for c in a.commands))
    def test_virtual_never_writes_ble_even_connected(self):
        self.real();self.virtual();before=list(self.link.sent)
        self.timeline();self.player.play();self.now+=.2;self.player.tick();self.player.stop()
        self.assertEqual(before,self.link.sent);self.assertTrue(any(p['type']=='audio' for p in self.packets))
    def test_switch_cancels_before_selecting_and_never_resumes(self):
        self.virtual();self.timeline();self.player.play();self.player.tick()
        epoch=self.player.epoch;self.player.switch('REAL')
        self.assertEqual(self.packets[-1]['type'],'audio_cancel');self.assertEqual(self.player.state,'stopped')
        self.assertGreater(self.player.epoch,epoch);self.assertEqual(self.app.router.mode,'REAL')
    def test_failed_stop_keeps_real_and_marks_unknown(self):
        self.real();self.timeline();self.player.play();self.player.tick();self.link.fail_stop=True
        with self.assertRaises(OutputError):self.player.switch('VIRTUAL')
        self.assertEqual(self.app.router.mode,'REAL');self.assertTrue(self.app.real.unknown)
        self.assertNotEqual(self.player.state,'playing')
    def test_disconnected_never_used_hardware_needs_no_ack(self):
        self.player.switch('VIRTUAL');self.assertEqual(self.app.router.mode,'VIRTUAL')
    def test_lost_active_hardware_blocks_switch(self):
        self.real();self.timeline();self.player.play();self.player.tick()
        self.app.real.lost('BLE lost')
        with self.assertRaises(OutputError):self.player.switch('VIRTUAL')
        self.assertTrue(self.app.real.unknown)
    def test_no_confirmation_capability_is_not_success(self):
        self.real();self.link.controller_status.pop('stop_ack')
        with self.assertRaises(OutputError):self.player.switch('VIRTUAL')
        self.assertIn('ALL STOP',self.link.sent);self.assertEqual(self.app.router.mode,'REAL')
    def test_mute_immediate_stop_and_never_blocks_stop(self):
        self.real();self.timeline();self.player.play();self.player.tick();self.link.sent.clear()
        self.player.mute('fdd-1',True);self.assertEqual(self.link.sent,['FDD 1 STOP'])
        self.now+=2.1;self.player.tick()
        self.assertFalse(any('PLAY' in s for s in self.link.sent));self.assertGreaterEqual(self.link.sent.count('FDD 1 STOP'),2)
    def test_virtual_mute_cancels_scheduled_device(self):
        self.virtual();self.timeline();self.player.play();self.player.tick();self.player.mute('fdd-1',True)
        self.assertEqual(self.packets[-1]['deviceId'],'fdd-1')
        self.now+=2;self.player.tick()
        for packet in self.packets[2:]:
            self.assertFalse(any(c['kind']=='tone' for c in packet.get('commands',[])))
    def test_stall_discards_expired_tones_and_percussion(self):
        self.real();self.player.load(T((C(0,'fdd-1','tone',.1,220),C(.1,'fdd-1','stop'),C(.2,'hdd_vcm-1','hit',.2),C(.5,'fdd-1','tone',2,260),C(2.5,'fdd-1','stop')),2.5))
        self.player.play();self.now+=.8;self.player.tick()
        self.assertEqual([s for s in self.link.sent if 'PLAY' in s],['FDD 1 PLAY 260.00'])
        self.assertFalse(any('HIT' in s for s in self.link.sent));self.assertEqual(self.player.dropped,2)
    def test_stop_invalidates_queued_commands(self):
        self.real();self.timeline();self.player.play();self.player.stop();before=list(self.link.sent)
        self.now+=10;self.player.tick();self.assertEqual(before,self.link.sent)
    def test_lab_and_orchestra_transfer_stops_previous_owner(self):
        self.real();self.timeline();self.player.play();self.player.tick()
        self.app.lab.enter('browser');self.assertEqual(self.player.state,'stopped');self.assertEqual(self.player.owner,'lab')
        self.app.lab.test('browser','fdd-1',220,1);self.player.tick();self.assertEqual(self.player.state,'playing')
        self.app.orchestra();self.assertEqual(self.player.state,'stopped');self.assertEqual(self.player.owner,'orchestra')
    def test_service_home_stops_and_has_exclusive_owner(self):
        self.real();self.timeline();self.player.play();self.player.tick()
        def home(**_): self.assertEqual(self.player.owner,'service');self.assertEqual(self.player.state,'stopped');return True
        self.link.wait_homed=home
        self.app.service.run('home');self.assertIn('FDD ALL HOME',self.link.sent)
        self.assertEqual(self.player.owner,'orchestra')
    def test_reset_is_unavailable_and_sends_nothing(self):
        self.real();before=list(self.link.sent)
        with self.assertRaisesRegex(OutputError,'resetu'):self.app.service.run('reset')
        self.assertEqual(before,self.link.sent)
    def test_pause_resume_restores_only_current_tone(self):
        self.real();self.timeline();self.player.play();self.now+=.3;self.player.pause();self.link.sent.clear()
        self.player.play();self.assertEqual(self.link.sent,['FDD 1 PLAY 220.00'])

class WebRuntimeTests(unittest.TestCase):
    def test_offline_import_plan_switch_mute_and_lab_share_registry(self):
        runtime=Application()
        with tempfile.TemporaryDirectory() as directory,TestClient(create_app(midi_dir=directory,runtime=runtime,connect_on_start=False)) as client:
            self.assertEqual(client.get('/api/state').json()['output']['mode'],'REAL')
            result=client.post('/api/files',files={'file':('test.mid',(ROOT/'midi/test.mid').read_bytes(),'audio/midi')})
            self.assertEqual(result.status_code,200)
            with client.websocket_connect('/ws') as ws:
                ws.receive_json()
                def action(action,**kw):
                    ws.send_json({'action':action,**kw})
                    while True:
                        m=ws.receive_json()
                        if m['type'] in ('ack','error'):return m
                self.assertEqual(action('set_file',file=result.json()['name'])['type'],'ack')
                plan=client.get('/api/plan').json();self.assertTrue(plan['events'])
                self.assertEqual(action('play')['type'],'error')
                self.assertEqual(action('output',mode='VIRTUAL')['state']['output']['mode'],'VIRTUAL')
                self.assertEqual(client.get('/api/plan').json(),plan)
                self.assertEqual(action('mute',deviceId='fdd-1',muted=True)['state']['output']['muted'],['fdd-1'])
                lab=action('lab_enter')['state'];self.assertEqual(lab['owner'],'lab')
                self.assertEqual(lab['devices'],runtime.registry.catalog())
                self.assertEqual(action('lab_leave')['state']['owner'],'orchestra')

class SafetyTests(unittest.TestCase):
    def test_virtual_stop_requires_ack_and_wrong_session_cannot_ack(self):
        app=Application();app.player.switch('VIRTUAL');app.virtual.owner='a';app.virtual.active=True
        def emit(packet): app.virtual.acknowledge('wrong',packet['token'])
        app.virtual.emit=emit
        with patch('runtime.outputs.threading.Event.wait',return_value=False):
            with self.assertRaises(OutputError):app.player.switch('REAL')
        self.assertEqual(app.router.mode,'VIRTUAL');self.assertEqual(app.player.state,'stopped')
    def test_firmware_uses_existing_uploader_only_under_exclusive_stop(self):
        app=Application();link=Link();app.real.attach(link)
        def upload(*args,**kwargs):
            self.assertEqual(app.player.owner,'service');self.assertEqual(app.player.state,'stopped')
            self.assertEqual(kwargs['target'],'esp32');return 'ok'
        from types import SimpleNamespace
        with patch('runtime.device_service.scan_ports',return_value=[SimpleNamespace(vid=0x10C4,device='/dev/fake')]),patch('runtime.device_service.platformio',return_value='pio'),patch('runtime.device_service.run_firmware',side_effect=upload) as flash:
            app.service.run('firmware');self.assertEqual(flash.call_count,2)
        self.assertTrue(link.closed);self.assertEqual(app.player.owner,'orchestra')
    def test_disconnect_never_falls_back_or_replays_on_reconnect(self):
        app=Application();link=Link();app.real.attach(link);app.real.configured=True
        app.player.load(T((C(0,'fdd-1','tone',2,220),C(2,'fdd-1','stop')),2));app.player.play()
        link.fail_write=True;app.player.tick()
        self.assertEqual(app.player.state,'paused');self.assertEqual(app.router.mode,'REAL');self.assertTrue(app.real.unknown)
        replacement=Link();app.real.attach(replacement);app.player.tick()
        self.assertFalse(any('PLAY' in line for line in replacement.sent))
    def test_no_startup_env_can_enable_virtual(self):
        with patch.dict('os.environ',{'ORCHESTRA_MODE':'virtual'}):
            self.assertEqual(Application().router.mode,'REAL')
    def test_mute_does_not_reallocate_plan(self):
        app=Application();app.load(ROOT/'midi/test.mid');plan=app.plan.as_dict()
        app.player.mute('fdd-1',True)
        self.assertEqual(app.plan.as_dict(),plan)

class MusicalRuntimeTests(unittest.TestCase):
    def test_strict_tracks_keeps_provenance_in_new_compiler(self):
        from midi_fixtures import write_midi
        import mido
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'four.mid';midi=mido.MidiFile()
            for i in range(5):
                track=mido.MidiTrack();track.append(mido.Message('note_on',note=60+i,velocity=90,time=0));track.append(mido.Message('note_off',note=60+i,time=480));midi.tracks.append(track)
            midi.save(p)
            registry=DeviceRegistry();registry.document['routing']={'mode':'STRICT_TRACKS','tracks':[3,1,4,2]}
            plan=arrange(MidiSource(p),registry);timeline=compile_plan(plan)
            for ident,track in zip(['fdd-1','fdd-2','fdd-3','fdd-4'],[3,1,4,2]):
                accepted=[c for c in timeline.commands if c.device_id==ident and c.kind=='tone']
                self.assertTrue(accepted);self.assertTrue(all(c.track==track for c in accepted))
    def test_compile_retains_touching_legato_and_autonomous_hits(self):
        from playback.performance import PerformancePlan,PerformanceEvent
        def event(ident,start,kind='FDD',device='fdd-1'):
            return PerformanceEvent(ident,0,'test',60,None,90,0,start,1,device,kind,60,220,start,1,'ACCEPTED')
        plan=PerformancePlan('x',[event('a',0),event('b',1),event('h',0,'HDD_VCM','hdd_vcm-1')],[{'id':'fdd-1','type':'FDD'},{'id':'hdd_vcm-1','type':'HDD_VCM'}],{})
        commands=compile_plan(plan).commands
        self.assertFalse(any(c.kind=='stop' and (c.time==1 or c.device_id=='hdd_vcm-1') for c in commands))
        self.assertTrue(any(c.kind=='stop' and c.time==2 for c in commands))
