"""Testy parsowania MIDI i redukcji do monofonii (bez sprzetu)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import (  # noqa: E402
    DANGLING_NOTE_S,
    MidiSource,
    MidiSourceError,
    NoteSpan,
    TempoMap,
    monophonic,
)

TPB = 480


def write_midi(path: Path, build) -> Path:
    midi = mido.MidiFile(ticks_per_beat=TPB)
    midi.tracks.append(build())
    midi.save(path)
    return path


class TestTempo(unittest.TestCase):
    def test_stale_tempo_to_domyslne_120_bpm(self):
        """Bez set_tempo obowiazuje 120 BPM: 480 tickow = 0.5 s."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_midi(
                Path(tmp) / "a.mid",
                lambda: _track_with_note(),
            )

            source = MidiSource(path)
            notes = source.notes(0)

            self.assertAlmostEqual(notes[0].start, 0.0, places=6)
            self.assertAlmostEqual(notes[0].end, 0.5, places=6)

    def test_zmiana_tempa_w_trakcie_utworu(self):
        """Druga nuta gra przy 240 BPM, wiec trwa 0.25 s."""

        def build() -> mido.MidiTrack:
            track = mido.MidiTrack()
            track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
            track.append(mido.Message("note_on", note=60, velocity=100, time=0))
            track.append(mido.Message("note_off", note=60, velocity=0, time=TPB))
            track.append(mido.MetaMessage("set_tempo", tempo=250_000, time=0))
            track.append(mido.Message("note_on", note=62, velocity=100, time=TPB))
            track.append(mido.Message("note_off", note=62, velocity=0, time=TPB))
            return track

        with tempfile.TemporaryDirectory() as tmp:
            source = MidiSource(write_midi(Path(tmp) / "b.mid", build))
            notes = source.notes(0)

            self.assertEqual(len(notes), 2)
            self.assertAlmostEqual(notes[0].start, 0.0, places=6)
            self.assertAlmostEqual(notes[0].end, 0.5, places=6)
            self.assertAlmostEqual(notes[1].start, 0.75, places=6)
            self.assertAlmostEqual(notes[1].end, 1.0, places=6)
            self.assertEqual(source.tempo.change_count, 1)

    def test_nuta_bez_note_off_jest_zamykana(self):
        def build() -> mido.MidiTrack:
            track = mido.MidiTrack()
            track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
            track.append(mido.Message("note_on", note=60, velocity=100, time=0))
            track.append(mido.Message("note_off", note=61, velocity=0, time=TPB))
            return track

        with tempfile.TemporaryDirectory() as tmp:
            source = MidiSource(write_midi(Path(tmp) / "c.mid", build))
            notes = source.notes(0)

            self.assertEqual(len(notes), 1)
            self.assertAlmostEqual(notes[0].duration, 0.5, places=6)

    def test_nuta_bez_note_off_na_koncu_tracku_ma_dlugosc(self):
        """Regresja: taka nuta konczyla sie na ostatnim zdarzeniu nutowym
        (czyli miala 0 s) i byla po cichu wyrzucana."""

        def build() -> mido.MidiTrack:
            track = mido.MidiTrack()
            track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
            track.append(mido.Message("note_on", note=60, velocity=100, time=0))
            return track

        with tempfile.TemporaryDirectory() as tmp:
            source = MidiSource(write_midi(Path(tmp) / "dangling.mid", build))
            notes = source.notes(0)

            self.assertEqual(len(notes), 1)
            self.assertGreater(notes[0].duration, 0.0)
            self.assertAlmostEqual(notes[0].duration, DANGLING_NOTE_S, places=6)


def _track_with_note(tempo: int | None = None) -> mido.MidiTrack:
    track = mido.MidiTrack()

    if tempo is not None:
        track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))

    track.append(mido.Message("note_on", note=60, velocity=100, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=TPB))

    return track


class TestOpisTrackow(unittest.TestCase):
    def test_nazwy_i_liczba_nut(self):
        def build() -> mido.MidiTrack:
            track = mido.MidiTrack()
            track.append(mido.MetaMessage("track_name", name="Piano", time=0))
            track.append(mido.Message("note_on", note=60, velocity=100, time=0))
            track.append(mido.Message("note_off", note=60, velocity=0, time=TPB))
            track.append(mido.Message("note_on", note=64, velocity=100, time=0))
            track.append(mido.Message("note_off", note=64, velocity=0, time=TPB))
            return track

        with tempfile.TemporaryDirectory() as tmp:
            source = MidiSource(write_midi(Path(tmp) / "d.mid", build))

            self.assertEqual(source.tracks[0].name, "Piano")
            self.assertEqual(source.tracks[0].note_count, 2)
            self.assertEqual(source.tracks[0].channels, (0,))
            self.assertFalse(source.tracks[0].is_drums)

    def test_plik_bez_nut_to_blad(self):
        def build() -> mido.MidiTrack:
            track = mido.MidiTrack()
            track.append(mido.MetaMessage("track_name", name="Pusty", time=0))
            return track

        with tempfile.TemporaryDirectory() as tmp:
            path = write_midi(Path(tmp) / "e.mid", build)

            with self.assertRaises(MidiSourceError):
                MidiSource(path)

    def test_brak_pliku(self):
        with self.assertRaises(MidiSourceError):
            MidiSource("/nie/ma/takiego/pliku.mid")

    def test_wykrywanie_perkusji(self):
        def build() -> mido.MidiTrack:
            track = mido.MidiTrack()
            track.append(
                mido.Message("note_on", note=36, velocity=100, channel=9, time=0)
            )
            track.append(
                mido.Message("note_off", note=36, velocity=0, channel=9, time=TPB)
            )
            return track

        with tempfile.TemporaryDirectory() as tmp:
            source = MidiSource(write_midi(Path(tmp) / "f.mid", build))

            self.assertTrue(source.tracks[0].is_drums)


class TestMonofonia(unittest.TestCase):
    """Trzy nuty: A (0-1 s), B (0-0.5 s, najwyzsza), C (0.5-1 s, najnizsza)."""

    def setUp(self):
        self.notes = [
            NoteSpan(start=0.0, end=1.0, note=60, velocity=100, channel=0),
            NoteSpan(start=0.0, end=0.5, note=72, velocity=100, channel=0),
            NoteSpan(start=0.5, end=1.0, note=48, velocity=100, channel=0),
        ]

    def test_najwyzsza_nuta(self):
        result = monophonic(self.notes, "highest")

        self.assertEqual([(n.start, n.end, n.note) for n in result],
                         [(0.0, 0.5, 72), (0.5, 1.0, 60)])

    def test_najnizsza_nuta(self):
        result = monophonic(self.notes, "lowest")

        self.assertEqual([(n.start, n.end, n.note) for n in result],
                         [(0.0, 0.5, 60), (0.5, 1.0, 48)])

    def test_ostatni_note_on(self):
        result = monophonic(self.notes, "last")

        self.assertEqual([(n.start, n.end, n.note) for n in result],
                         [(0.0, 0.5, 72), (0.5, 1.0, 48)])

    def test_segmenty_sa_rozlaczne(self):
        for strategy in ("highest", "lowest", "last"):
            result = monophonic(self.notes, strategy)

            for previous, following in zip(result, result[1:]):
                self.assertLessEqual(previous.end, following.start)

    def test_powtorka_tej_samej_nuty(self):
        """Dwa razy ta sama nuta jeden po drugiej to dwa osobne odcinki."""
        notes = [
            NoteSpan(0.0, 0.5, 60, 100, 0),
            NoteSpan(0.5, 1.0, 60, 100, 0),
        ]

        result = monophonic(notes, "highest")

        self.assertEqual(len(result), 2)

    def test_nakladajaca_sie_ta_sama_nuta_scala_sie_w_jeden_dzwiek(self):
        """Monofoniczna stacja slyszy to jako jeden ciagly dzwiek."""
        notes = [
            NoteSpan(0.0, 1.0, 60, 100, 0),
            NoteSpan(0.5, 1.5, 60, 100, 0),
        ]

        result = monophonic(notes, "highest")

        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].start, 0.0, places=6)
        self.assertAlmostEqual(result[0].end, 1.5, places=6)

    def test_ta_sama_wysokosc_na_dwoch_kanalach_to_jeden_dzwiek(self):
        notes = [
            NoteSpan(0.0, 1.0, 60, 100, 0),
            NoteSpan(0.25, 1.25, 60, 100, 1),
        ]

        result = monophonic(notes, "highest")

        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].end, 1.25, places=6)

    def test_dluga_nuta_nad_ruchomym_basem_to_jedna_nuta(self):
        """Trzymany dzwiek nie moze byc cietty przez inne nuty pod nim.

        Regresja: kazde zdarzenie nuty towarzyszacej zamykalo odcinek,
        przez co dluga nuta zamieniala sie w serie ponownych atakow
        (z 12 ms przerwami w harmonogramie).
        """
        notes = [NoteSpan(0.0, 2.0, 72, 100, 0)]

        for index in range(3):
            notes.append(NoteSpan(index * 0.1, index * 0.1 + 0.1, 48, 100, 0))

        result = monophonic(notes, "highest")

        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].start, 0.0, places=6)
        self.assertAlmostEqual(result[0].end, 2.0, places=6)
        self.assertEqual(result[0].note, 72)

    def test_last_gra_ostatni_note_on_a_nie_najwyzsza_nute(self):
        """Kolejnosc zdarzen z pliku, nie kolejnosc po wysokosci."""
        notes = [
            NoteSpan(0.0, 1.0, 72, 100, 0, order=0),  # wczesniejsze zdarzenie
            NoteSpan(0.0, 1.0, 60, 100, 0, order=1),  # pozniejsze zdarzenie
        ]

        self.assertEqual(monophonic(notes, "highest")[0].note, 72)
        self.assertEqual(monophonic(notes, "last")[0].note, 60)

    def test_pusta_lista(self):
        self.assertEqual(monophonic([], "highest"), [])

    def test_nieznana_strategia(self):
        with self.assertRaises(MidiSourceError):
            monophonic(self.notes, "najglosniejsza")


if __name__ == "__main__":
    unittest.main()
