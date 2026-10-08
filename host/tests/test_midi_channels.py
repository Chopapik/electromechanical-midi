"""Mixed-channel MIDI import preserves timing and separates drums from tones."""
import tempfile
import unittest
from pathlib import Path

import mido

from midi_source import MidiSource
from playback.analysis import analyze, PERCUSSION
from playback.allocator import allocate
from playback.duplicates import normalize
from playback.hardware_profiles import HardwareContext
from playback.orchestra import default_orchestra


class ChannelImportTests(unittest.TestCase):
    def source(self, directory, file_type=0):
        midi = mido.MidiFile(type=file_type, ticks_per_beat=480)
        track = mido.MidiTrack([
            mido.MetaMessage('track_name', name='Mixed'),
            mido.MetaMessage('set_tempo', tempo=500000),
            mido.Message('program_change', channel=0, program=27),
            mido.Message('program_change', channel=1, program=32),
            mido.Message('control_change', channel=0, control=64, value=127),
            mido.Message('note_on', channel=0, note=60, velocity=90),
            mido.Message('note_on', channel=1, note=36, velocity=80),
            mido.Message('note_on', channel=9, note=38, velocity=100),
            mido.Message('note_off', channel=9, note=38, time=240),
            mido.MetaMessage('lyrics', text='Hello', time=240),
            mido.MetaMessage('set_tempo', tempo=1000000),
            mido.Message('pitchwheel', channel=1, pitch=500, time=120),
            mido.Message('aftertouch', channel=0, value=50),
            mido.Message('polytouch', channel=0, note=60, value=40),
            mido.Message('control_change', channel=0, control=64, value=0),
            mido.Message('note_off', channel=0, note=60, time=120),
            mido.Message('note_on', channel=0, note=64, velocity=70),
            # Both dangling notes must last until the original track end.
            mido.MetaMessage('end_of_track', time=240),
        ])
        midi.tracks.append(track)
        path = Path(directory) / f'mixed-{file_type}.mid'
        midi.save(path)
        return MidiSource(path)

    def test_type_zero_and_mixed_type_one_preserve_times_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            for file_type in (0, 1):
                with self.subTest(file_type=file_type):
                    source = self.source(tmp, file_type)
                    self.assertEqual(source.file_type, file_type)
                    self.assertEqual([t.channels for t in source.tracks], [(0,), (1,), (9,)])
                    self.assertEqual([t.is_drums for t in source.tracks], [False, False, True])
                    self.assertEqual(sum(t.note_count for t in source.tracks), 4)
                    self.assertAlmostEqual(source.duration, 1.5)
                    self.assertEqual(source.tempo.change_count, 1)
                    self.assertEqual([(n.start, n.end) for n in source.notes(0)], [(0, 1), (1, 1.5)])
                    self.assertEqual([(n.start, n.end) for n in source.notes(1)], [(0, 1.5)])
                    self.assertEqual([(n.start, n.end) for n in source.notes(2)], [(0, .25)])
                    self.assertEqual(source.programs(0), (27,))
                    self.assertEqual(source.programs(1), (32,))
                    self.assertEqual(source.programs(2), ())
                    self.assertEqual([(t.time, t.text) for t in source.text_events()], [(.5, 'Hello')])
                    expression = source.expression_events()
                    self.assertEqual(len(expression), 7)
                    for event in expression:
                        self.assertEqual(source.tracks[event['track']].channels, (event['channel'],))
                    self.assertEqual(next(e['time'] for e in expression if e['kind'] == 'pitchwheel'), .75)
                    # Original file and physical track are untouched.
                    self.assertEqual(len(source._midi.tracks), 1)
                    self.assertEqual(source._midi.type, file_type)

    def test_normalization_and_real_plan_keep_guitars_out_of_hdd(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = normalize(self.source(tmp))
            analysis = analyze(source)
            for track in source.tracks:
                for note in source.notes(track.index):
                    role = analysis.roles[f'{track.index}:{note.order}']
                    self.assertEqual(role == PERCUSSION, note.channel == 9)
            config = default_orchestra()
            for device in config.devices:
                device['mode'] = 'real'
            plan = allocate(source, config, hardware_context=HardwareContext(True))
            played = [event for event in plan.events if event.outcome != 'DROPPED']
            self.assertTrue(any(event.role != PERCUSSION for event in played))
            self.assertTrue(any(event.role == PERCUSSION for event in played))
            for event in played:
                self.assertEqual(event.device_id.startswith('hdd_vcm-'), event.role == PERCUSSION)

    def test_single_channel_tracks_and_text_only_tracks_keep_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            midi = mido.MidiFile(type=1)
            midi.tracks.append(mido.MidiTrack([mido.MetaMessage('lyrics', text='Intro')]))
            midi.tracks.append(mido.MidiTrack([
                mido.MetaMessage('track_name', name='Guitar'),
                mido.Message('note_on', channel=2, note=60, velocity=80),
                mido.Message('note_off', channel=2, note=60, time=480),
            ]))
            path = Path(tmp) / 'separate.mid'
            midi.save(path)
            source = MidiSource(path)
            self.assertEqual(len(source.tracks), 2)
            self.assertEqual(source.tracks[1].name, 'Guitar')
            self.assertEqual(source.tracks[1].channels, (2,))
            self.assertEqual(source.text_events()[0].track, 0)
