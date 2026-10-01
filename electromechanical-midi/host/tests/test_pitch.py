"""Testy skladania oktawowego (bez sprzetu)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pitch import (  # noqa: E402
    COMFORT_MAX_HZ,
    COMFORT_MIN_HZ,
    PitchError,
    fold_note,
    hz_to_midi,
    midi_to_hz,
    note_name,
)


class TestKonwersje(unittest.TestCase):
    def test_a4_to_440(self):
        self.assertAlmostEqual(midi_to_hz(69), 440.0, places=6)

    def test_c4_to_261(self):
        self.assertAlmostEqual(midi_to_hz(60), 261.6255653, places=5)

    def test_round_trip(self):
        for note in range(128):
            self.assertAlmostEqual(hz_to_midi(midi_to_hz(note)), note, places=6)

    def test_nazwy_nut(self):
        self.assertEqual(note_name(60), "C4")
        self.assertEqual(note_name(69), "A4")
        self.assertEqual(note_name(61), "C#4")

    def test_ujemna_czestotliwosc(self):
        with self.assertRaises(PitchError):
            hz_to_midi(0.0)


class TestSkladanieOktawowe(unittest.TestCase):
    def test_przyklad_z_dokumentacji(self):
        """C5 = 523.25 Hz -> C4 = 261.63 Hz (jedna oktawa w dol)."""
        folded = fold_note(72)

        self.assertEqual(folded.octave_shift, -1)
        self.assertEqual(folded.played_midi_note, 60)
        self.assertAlmostEqual(folded.hz, 261.6255653, places=4)
        self.assertTrue(folded.in_range)

    def test_nuta_ponizej_zakresu_w_gore(self):
        """C2 = 65.4 Hz -> C3 = 130.8 Hz."""
        folded = fold_note(36)

        self.assertEqual(folded.played_midi_note, 48)
        self.assertAlmostEqual(folded.hz, 130.8127827, places=4)
        self.assertTrue(folded.in_range)

    def test_nuta_w_zakresie_zostaje(self):
        folded = fold_note(60)

        self.assertEqual(folded.octave_shift, 0)
        self.assertAlmostEqual(folded.hz, midi_to_hz(60), places=6)

    def test_wszystkie_nuty_mieszcza_sie_w_komfortowym_zakresie(self):
        """130-330 Hz to wiecej niz oktawa, wiec kazda nuta ma swoja oktave."""
        for note in range(128):
            folded = fold_note(note)

            self.assertTrue(folded.in_range, msg=f"nuta {note} poza zakresem")
            self.assertGreaterEqual(folded.hz, COMFORT_MIN_HZ - 1e-6)
            self.assertLessEqual(folded.hz, COMFORT_MAX_HZ + 1e-6)

    def test_klasa_wysokosci_dzwieku_zostaje(self):
        """Skladanie oktawowe nie zmienia nazwy dzwieku."""
        for note in range(128):
            folded = fold_note(note)

            self.assertEqual(folded.played_midi_note % 12, note % 12)

    def test_zakres_wezszy_niz_oktawa(self):
        """Gdy nie ma idealnej oktawy, gramy najblizsza i to sygnalizujemy."""
        # C#4 = 277.2 Hz: /2 = 138.6 Hz (ponizej 130... nie, powyzej),
        # /4 = 69.3 Hz - zadna oktawa nie miesci sie w 100-130 Hz.
        folded = fold_note(61, min_hz=100.0, max_hz=130.0)

        self.assertFalse(folded.in_range)
        self.assertEqual(folded.played_midi_note % 12, 1)
        self.assertEqual(folded.octave_shift, -1)
        self.assertGreater(folded.hz, 0.0)

    def test_tryby_skladania(self):
        for mode in ("auto", "low", "high"):
            folded = fold_note(72, mode=mode)

            self.assertGreaterEqual(folded.hz, COMFORT_MIN_HZ - 1e-6)
            self.assertLessEqual(folded.hz, COMFORT_MAX_HZ + 1e-6)

    def test_tryb_low_zawsze_najnizsza_oktawa(self):
        """C4 i C5 daja ten sam dzwiek - melodia nie ma skokow oktawowych."""
        for note in (60, 72, 84):
            folded = fold_note(note, mode="low")

            self.assertAlmostEqual(folded.hz, midi_to_hz(48), places=4)

    def test_tryb_high_zawsze_najwyzsza_oktawa(self):
        for note in (48, 60, 72):
            folded = fold_note(note, mode="high")

            self.assertAlmostEqual(folded.hz, midi_to_hz(60), places=4)

    def test_tryby_low_high_bez_skokow_dla_chromatyki(self):
        """W trybach low/high wynik dla kazdej nuty pada w jedno-oktawowe okno."""
        for note in range(128):
            low = fold_note(note, mode="low").hz
            high = fold_note(note, mode="high").hz

            self.assertGreaterEqual(low, COMFORT_MIN_HZ - 1e-6)
            self.assertLess(low, COMFORT_MIN_HZ * 2)

            self.assertGreater(high, COMFORT_MAX_HZ / 2)
            self.assertLessEqual(high, COMFORT_MAX_HZ + 1e-6)

    def test_auto_zgodne_z_przykladem_z_dokumentacji(self):
        """Tryb domyslny: C5 = 523.25 Hz -> C4 = 261.63 Hz."""
        folded = fold_note(72, mode="auto")

        self.assertEqual(folded.played_name, "C4")
        self.assertAlmostEqual(folded.hz, 261.6255653, places=4)

    def test_zle_parametry(self):
        with self.assertRaises(PitchError):
            fold_note(60, mode="byle-jak")

        with self.assertRaises(PitchError):
            fold_note(60, min_hz=200.0, max_hz=100.0)

        with self.assertRaises(PitchError):
            fold_note(60, min_hz=0.0)


if __name__ == "__main__":
    unittest.main()
