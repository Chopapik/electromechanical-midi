"""Semantic track classification and its effect on lead routing."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import MidiSource  # noqa: E402
from playback.analysis import analyze  # noqa: E402
from playback.allocator import allocate  # noqa: E402
from playback.duplicates import normalize  # noqa: E402
from playback.orchestra import default_orchestra  # noqa: E402

MIDI_DIR = Path(__file__).resolve().parents[2] / 'midi'


def make_midi(path: Path, name: str, *, program: int | None = None,
              pitch: int = 65, lyrics: bool = False) -> MidiSource:
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(mido.MetaMessage('set_tempo', tempo=500_000))
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage('track_name', name=name))
    if program is not None:
        track.append(mido.Message('program_change', channel=0, program=program))
    for n in range(12):
        note = pitch + (n % 3)
        track.append(mido.Message('note_on', channel=0, note=note, velocity=90,
                                  time=480 if n else 0))
        if lyrics:
            track.append(mido.MetaMessage('lyrics', text=f'word{n}', time=0))
        track.append(mido.Message('note_off', channel=0, note=note, velocity=0, time=240))
    midi.save(path)
    return MidiSource(path)


class SemanticClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'semantic.mid'

    def tearDown(self):
        self.temp.cleanup()

    def classified(self, name: str, **kwargs):
        return analyze(make_midi(self.path, name, **kwargs))

    def test_names_and_gm_are_combined_without_hardcoded_artist(self):
        cases = [
            ('Lead Vocal', 65, 65, 'VOCAL'),
            ('Thom Yorke (voz)', 65, 65, 'VOCAL'),
            ('Backing Vox', 54, 65, 'BACKING_VOCAL'),
            ('Add voice', 54, 65, 'BACKING_VOCAL'),
            ('Synth Voice', 91, 65, 'BACKING_VOCAL'),
            ('Bass', 33, 40, 'BASS'),
            ('Guitar', 26, 65, 'GUITAR'),
            ('Strings', 44, 65, 'STRINGS'),
        ]
        for name, program, pitch, role in cases:
            with self.subTest(name=name):
                result = self.classified(name, program=program, pitch=pitch)
                track = result.classifications[1]
                self.assertEqual(track.final_role, role)
                self.assertTrue(track.evidence)

    def test_monophonic_low_line_is_not_vocal(self):
        result = self.classified('Instrument 1', pitch=40)
        self.assertEqual(result.classifications[1].final_role, 'OTHER')
        self.assertNotEqual(result.classifications[1].final_role, 'VOCAL')

    def test_alto_sax_does_not_override_voz_and_lyrics_add_evidence(self):
        result = self.classified('voz', program=65, lyrics=True)
        track = result.classifications[1]
        self.assertEqual(track.final_role, 'VOCAL')
        self.assertEqual(track.gm_family, 'Reed')
        self.assertGreater(track.lyric_alignment, .9)
        self.assertIn('lyrics alignment', ' '.join(track.evidence))
        self.assertEqual(result.lead_source, 'semantic-vocal')

    def test_deterministic_classification(self):
        source = make_midi(self.path, 'Voice', program=65, lyrics=True)
        self.assertEqual(analyze(source).as_dict(), analyze(source).as_dict())

    def test_perfect_lyric_alignment_can_identify_unnamed_melody(self):
        result = self.classified('Melody', program=65, lyrics=True)
        self.assertEqual(result.classifications[1].final_role, 'VOCAL')
        self.assertEqual(result.lead_source, 'semantic-vocal')


class RealMidiRegressionTests(unittest.TestCase):
    def source(self, filename: str) -> MidiSource:
        path = MIDI_DIR / filename
        if not path.is_file():
            self.skipTest(f'brak lokalnego pliku MIDI: {filename}')
        return MidiSource(path)

    def test_there_there_vocal_uses_only_vhs(self):
        source = normalize(self.source('0071-09-radiohead_2003-there_there-[k].mid'))
        result = analyze(source)
        by_name = {item.name: item for item in result.classifications}
        vocal = by_name['Thom Yorke (voz)']
        self.assertEqual(vocal.final_role, 'VOCAL')
        self.assertEqual(result.lead_track, vocal.index)
        self.assertEqual(result.lead_source, 'semantic-vocal')
        self.assertEqual(by_name['Add voice'].final_role, 'BACKING_VOCAL')

        plan = allocate(source, default_orchestra())
        reported = {item['name']: item for item in plan.report()['trackClassification']}
        self.assertEqual(reported['Thom Yorke (voz)']['finalRole'], 'VOCAL')
        self.assertGreater(reported['Thom Yorke (voz)']['confidence'], .75)
        lead = [event for event in plan.events if event.track == vocal.index]
        self.assertEqual(len(lead), vocal.note_count)
        self.assertTrue(all(event.played and event.device_type == 'VHS' for event in lead))
        self.assertFalse(any(event.device_type == 'VHS' and event.role != 'lead'
                             for event in plan.events))

    def test_nude_bass_cannot_become_vocal_or_lead(self):
        source = self.source('0081-03-radiohead_2007-nude.mid')
        result = analyze(source)
        by_name = {item.name: item for item in result.classifications}
        self.assertEqual(by_name['Bass'].final_role, 'BASS')
        self.assertFalse(any(item.final_role == 'VOCAL' for item in result.classifications))
        self.assertEqual(result.lead_source, 'heuristic')
        self.assertNotEqual(result.lead_track, by_name['Bass'].index)

    def test_other_available_songs_keep_expected_leads(self):
        cases = [
            ('0002-02-radiohead_1993-creep-[k].mid', 4),
            ('0063-01-radiohead_2003-2+2=5-[k].mid', 7),
            ('0087-09-radiohead_2007-jigsaw_falling_into_place.mid', 3),
        ]
        for filename, lead in cases:
            with self.subTest(filename=filename):
                result = analyze(self.source(filename))
                self.assertEqual(result.lead_track, lead)
