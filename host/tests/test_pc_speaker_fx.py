import sys
import tempfile
import unittest
from pathlib import Path
import mido
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from midi_source import MidiSource
from runtime.registry import DeviceRegistry
from runtime.arranger import arrange
from runtime.compiler import compile_plan,ExecutionCommand
from runtime.outputs import RealOutput,OutputError
from orchestra_link import parse_status
from test_runtime import Link

class SpeakerFxTests(unittest.TestCase):
    def source(self,path,lyrics=True):
        midi=mido.MidiFile(ticks_per_beat=480)
        for channel,program,pitch in [(0,26,60),(1,73,80)]:
            track=mido.MidiTrack();midi.tracks.append(track)
            track.append(mido.Message('program_change',channel=channel,program=program))
            for i in range(24):
                track.append(mido.Message('note_on',channel=channel,note=pitch+i%3,velocity=90,time=240 if i else 0))
                if lyrics and channel==0:track.append(mido.MetaMessage('lyrics',text='word'+str(i)))
                track.append(mido.Message('note_off',channel=channel,note=pitch+i%3,time=240))
        midi.save(path);return MidiSource(path)
    def test_unnamed_vocal_beats_high_flute_and_fx_is_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            p=arrange(self.source(Path(directory)/'song.mid'),DeviceRegistry())
        self.assertEqual(p.analysis['leadTrack'],0)
        self.assertEqual(p.analysis['fxTracks'],[1])
        self.assertTrue(all(e.device_id=='vhs-1' for e in p.events if e.track==0))
        self.assertTrue(all(e.device_id=='pc-speaker-fx' for e in p.events if e.track==1))
        self.assertEqual(len([e for e in p.events if e.played]),48)
        self.assertEqual(compile_plan(p),compile_plan(p))
    def test_no_lyrics_keeps_heuristic_and_no_automatic_fx(self):
        with tempfile.TemporaryDirectory() as directory:
            p=arrange(self.source(Path(directory)/'song.mid',False),DeviceRegistry())
        self.assertEqual(p.analysis['fxTracks'],[])
        self.assertEqual(p.analysis['leadSelection'],'heuristic')
    def test_second_real_output_and_old_firmware_guard(self):
        real=RealOutput(DeviceRegistry());link=Link();real.attach(link)
        command=ExecutionCommand(0,'pc-speaker-fx','tone',.5,987.77)
        with self.assertRaisesRegex(OutputError,'GPIO 26'):real.ready([command])
        link.controller_status['speaker_fx']='1'
        link.device_status['VHS2']={'enabled':'1'}
        real.ready([command]);real.dispatch([command]);real.stop_device('pc-speaker-fx')
        self.assertIn('VHS2 ENABLE 1',link.sent)
        self.assertIn('VHS2 FREQ 987.77',link.sent)
        self.assertIn('VHS2 STOP',link.sent)
        parsed=parse_status(['STATUS BEGIN','STATUS CTRL speaker_fx=1','STATUS VHS2 enabled=1 amp=50 hz=830','STATUS END'])
        self.assertEqual(parsed['devices']['VHS2']['hz'],'830')
