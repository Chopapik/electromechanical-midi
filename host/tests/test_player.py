"""Testy budowania harmonogramu komend PLAY/STOP (bez sprzetu)."""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import NoteSpan  # noqa: E402
from pitch import midi_to_hz  # noqa: E402
from player import ARTICULATION_S, MIN_NOTE_S, build_schedule, main  # noqa: E402


def span(start: float, end: float, note: int) -> NoteSpan:
    return NoteSpan(start=start, end=end, note=note, velocity=100, channel=0)


def as_tuples(commands):
    return [(round(c.time, 4), c.text) for c in commands]


class TestHarmonogram(unittest.TestCase):
    def test_nuty_stykajace_sie_to_legato(self):
        commands, stats = build_schedule([span(0.0, 0.5, 60), span(0.5, 1.0, 62)])

        self.assertEqual(
            [c.kind for c in commands], ["play", "play", "stop"]
        )
        self.assertAlmostEqual(commands[0].time, 0.0, places=6)
        self.assertAlmostEqual(commands[1].time, 0.5, places=6)
        self.assertAlmostEqual(commands[2].time, 1.0, places=6)
        self.assertEqual(stats.notes, 2)

    def test_przerwa_daje_stop(self):
        commands, _ = build_schedule([span(0.0, 0.5, 60), span(1.0, 1.5, 62)])

        self.assertEqual(
            as_tuples(commands),
            [
                (0.0, "PLAY 261.63"),
                (0.5, "STOP"),
                (1.0, "PLAY 293.66"),
                (1.5, "STOP"),
            ],
        )

    def test_powtorka_tej_samej_nuty_jest_artykulowana(self):
        """STOP musi byc PRZED powtorka, inaczej przerwa jest zerowa."""
        commands, _ = build_schedule([span(0.0, 0.5, 60), span(0.5, 1.0, 60)])

        kinds = [c.kind for c in commands]

        self.assertEqual(kinds, ["play", "stop", "play", "stop"])
        self.assertAlmostEqual(commands[2].time, 0.5, places=6)
        self.assertLess(commands[1].time, commands[2].time)
        self.assertAlmostEqual(commands[2].time - commands[1].time, ARTICULATION_S, places=6)

    def test_bardzo_krotka_powtorka_nie_lamie_kolejnosci(self):
        """Nuta krotsza niz artykulacja: STOP nie moze wypasc przed jej startem."""
        commands, _ = build_schedule([span(0.0, 0.012, 60), span(0.012, 0.024, 60)])

        times = [c.time for c in commands]

        self.assertEqual(times, sorted(times))
        for time in times:
            self.assertGreaterEqual(time, 0.0)

    def test_powtorka_nie_ucina_poprzedniej_nuty_ponizej_minimum(self):
        """Artykulacja nie moze skrocic nuty do 1 ms."""
        commands, _ = build_schedule([span(0.0, 0.013, 60), span(0.013, 0.5, 60)])

        stop = next(command for command in commands if command.kind == "stop")

        self.assertGreaterEqual(stop.time, MIN_NOTE_S - 1e-9)

    def test_za_krotkie_nuty_sa_pomijane(self):
        commands, stats = build_schedule([span(0.0, 0.002, 60), span(0.0, 0.5, 62)])

        self.assertEqual(stats.skipped, 1)
        self.assertEqual(stats.notes, 1)
        self.assertEqual(len([c for c in commands if c.kind == "play"]), 1)

    def test_skladanie_oktawowe_w_komendzie(self):
        """C5 zapisane w MIDI ma po zagraniu dac C4 = 261.63 Hz."""
        commands, stats = build_schedule([span(0.0, 0.5, 72)])

        self.assertEqual(commands[0].text, "PLAY 261.63")
        self.assertAlmostEqual(commands[0].hz, midi_to_hz(60), places=2)
        self.assertEqual(stats.folded, 1)
        self.assertEqual(stats.out_of_range, 0)

    def test_gate_skraca_nuty(self):
        commands, _ = build_schedule([span(0.0, 1.0, 60)], gate=0.5)

        self.assertAlmostEqual(commands[-1].time, 0.5, places=6)

    def test_zakres_wezszy_niz_oktawa_jest_raportowany(self):
        _, stats = build_schedule(
            [span(0.0, 0.5, 61)], min_hz=100.0, max_hz=130.0
        )

        self.assertGreater(stats.out_of_range, 0)

    def test_pusty_utwor(self):
        commands, stats = build_schedule([])

        self.assertEqual(commands, [])
        self.assertEqual(stats.duration, 0.0)

    def test_wyslane_czestotliwosci_mieszcza_sie_w_zakresie(self):
        notes = [span(index * 0.5, index * 0.5 + 0.5, note) for index, note in enumerate(range(0, 128, 3))]

        commands, stats = build_schedule(notes)

        for command in commands:
            if command.kind == "play":
                self.assertGreaterEqual(command.hz, 130.0 - 1e-6)
                self.assertLessEqual(command.hz, 330.0 + 1e-6)


class TestCLI(unittest.TestCase):
    """CLI nie moze pozwolic na wyslanie calego utworu bez czekania."""

    MIDI = Path(__file__).resolve().parents[2] / "midi" / "test.mid"

    def test_no_wait_bez_dry_run_jest_odrzucane(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main([str(self.MIDI), "--track", "1", "--no-wait"])

        self.assertEqual(code, 2)

    def test_no_wait_z_dry_run_jest_ok(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main([str(self.MIDI), "--track", "1", "--dry-run", "--no-wait"])

        self.assertEqual(code, 0)

    def test_zly_zakres_jest_odrzucany(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main([str(self.MIDI), "--track", "1", "--min-hz", "300", "--max-hz", "200"])

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
