"""Testy silnika odtwarzania (bez sprzetu - po to jest FakeTransport).

Sprawdzaja przede wszystkim to, co najlatwiej zepsuc:
seek do srodka nuty, wznowienie po pauzie, anulowanie starego planu
i brak narastajacego dryfu.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import MidiSource, NoteSpan  # noqa: E402
from playback.engine import (  # noqa: E402
    DRUM_DRIVE_DEFAULT,
    DRUM_START_VALUE,
    EngineError,
    PlaybackEngine,
    PlaybackState,
)

TPB = 480
TEMPO = 500_000          # 120 BPM -> 1 s = 960 tickow
TICKS_PER_SECOND = TPB * 1_000_000 // TEMPO


# ============================================================
# NARZEDZIA
# ============================================================


class FakeTransport:
    """Zapisuje komendy zamiast wysylac je po Serial."""

    def __init__(self, fail_after: int | None = None, lines: list[str] | None = None):
        self.port = "/dev/fake"
        self.label = "Fake"
        self.lock = threading.Lock()
        self.events: list[tuple[float, str]] = []
        self.fail_after = fail_after
        self.closed = False
        self._count = 0
        self._start = time.monotonic()
        self._lines: list[str] = list(lines or [])

    # --- Transport ---
    def send(self, command: str) -> None:
        self._record(command)

    def play(self, hz: float) -> None:
        self._record(f"PLAY {hz:.2f}")

    def stop(self) -> None:
        self._record("STOP")

    def ping(self) -> None:
        self._record("PING")

    def poll_lines(self) -> list[str]:
        with self.lock:
            lines, self._lines = self._lines, []

        return lines

    def queue_line(self, line: str) -> None:
        with self.lock:
            self._lines.append(line)

    def close(self) -> None:
        self.closed = True

    # --- pomocnicze ---
    def _record(self, text: str) -> None:
        with self.lock:
            self._count += 1

            if self.fail_after is not None and self._count > self.fail_after:
                raise RuntimeError("port odlaczony")

            self.events.append((time.monotonic() - self._start, text))

    def texts(self) -> list[str]:
        with self.lock:
            return [text for _, text in self.events]

    def raw_texts(self) -> list[str]:
        """Wszystko, takze STATUS/DRUM (do testow bebna)."""
        with self.lock:
            return [text for _, text in self.events]

    def commands(self, exclude_ping: bool = True) -> list[tuple[float, str]]:
        with self.lock:
            return [
                (at, text)
                for at, text in self.events
                if not (exclude_ping and text == "PING")
            ]

    def plays(self) -> list[str]:
        return [text for text in self.texts() if text.startswith("PLAY")]

    @property
    def count(self) -> int:
        with self.lock:
            return self._count

    def fail_after_next(self, count: int = 1) -> None:
        """Uzbroj awarie: od nastepnej komendy wszystko sie nie udaje."""
        with self.lock:
            self.fail_after = self._count

    def fdd_since(self, index: int) -> list[str]:
        """Tylko komendy linii FDD (PLAY/STOP) - bez resetu bebna i PING."""
        return [
            text
            for _, text in self.since(index)
            if text.startswith(("PLAY", "STOP"))
        ]

    def since(self, index: int, exclude_ping: bool = True) -> list[tuple[float, str]]:
        with self.lock:
            return [
                (at, text)
                for at, text in self.events[index:]
                if not (exclude_ping and text == "PING")
            ]


def write_midi(path: Path, notes: list[tuple[float, float, int]], name: str = "Test") -> Path:
    """notes: [(start_s, end_s, midi_note), ...] -> plik .mid o znanym czasie."""
    midi = mido.MidiFile(type=0, ticks_per_beat=TPB)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name=name, time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=TEMPO, time=0))

    # (tick, kind, note): kind 0 = note_on, 1 = note_off.
    # Przy tym samym ticku note_off idzie pierwszy, zeby stykajace sie
    # nuty byly dwoma zdarzeniami (a nie jednym nachodzacym).
    events: list[tuple[int, int, int]] = []

    for start, end, note in notes:
        events.append((round(start * TICKS_PER_SECOND), 0, note))
        events.append((round(end * TICKS_PER_SECOND), 1, note))

    events.sort(key=lambda event: (event[0], event[1]))

    previous = 0
    for tick, kind, note in events:
        delta = tick - previous
        previous = tick
        track.append(
            mido.Message(
                "note_on" if kind == 0 else "note_off",
                note=note,
                velocity=100 if kind == 0 else 0,
                time=delta,
            )
        )

    midi.save(path)

    return path


class EngineTestCase(unittest.TestCase):
    """Baza: katalog tymczasowy + silnik z FakeTransport."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.transport = FakeTransport()
        self.engine = PlaybackEngine(
            connect_fn=lambda port: self.transport,
            keepalive=0.2,
        )
        self.engine.start()
        self.assertTrue(self.engine.connect())

    def tearDown(self):
        self.engine.shutdown()
        self._tmp.cleanup()

    def load(self, notes, name="Test", track_index=0):
        path = write_midi(self.tmp / f"{name}.mid", notes, name=name)
        self.engine.load_file(path, track_index)

        return path

    def wait_for_state(self, state: PlaybackState, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if self.engine.state is state:
                return True

            time.sleep(0.005)

        return False


# ============================================================
# PODSTAWY
# ============================================================


class TestPodstawy(EngineTestCase):
    def test_dlugosc_timeline(self):
        self.load([(0.0, 1.0, 60), (1.0, 2.0, 62), (2.0, 3.0, 64)])

        self.assertAlmostEqual(self.engine.duration, 3.0, places=2)

    def test_play_gra_i_konczy(self):
        self.load([(0.0, 0.2, 60), (0.3, 0.5, 62)])

        self.engine.play()
        self.assertTrue(self.wait_for_state(PlaybackState.STOPPED, timeout=2.0))

        plays = self.transport.plays()
        self.assertEqual(len(plays), 2)
        self.assertIn("STOP", self.transport.texts())

    def test_play_bez_utworu_to_blad(self):
        with self.assertRaises(EngineError):
            self.engine.play()

    def test_stop_zeruje_pozycje(self):
        self.load([(0.0, 2.0, 60), (2.5, 3.0, 62)])

        self.engine.play()
        time.sleep(0.15)
        self.engine.stop()

        self.assertIs(self.engine.state, PlaybackState.STOPPED)
        self.assertAlmostEqual(self.engine.position, 0.0, places=3)

    def test_snapshot_ma_pola_dla_ui(self):
        self.load([(0.0, 1.0, 64)])

        self.engine.play()
        time.sleep(0.1)

        snapshot = self.engine.snapshot()

        self.assertEqual(snapshot["state"], "playing")
        self.assertAlmostEqual(snapshot["duration"], 1.0, places=2)
        self.assertIsNotNone(snapshot["file"])
        self.assertEqual(snapshot["track"], 0)
        self.assertEqual(snapshot["trackName"], "Test")
        self.assertEqual(snapshot["noteName"], "E4")   # 64 = E4 = 329.63 Hz (w zakresie)
        self.assertGreater(snapshot["frequency"], 130.0)
        self.assertTrue(snapshot["hardware"]["connected"])

    def test_cisza_daje_rest(self):
        """Po zakonczeniu nuty, a przed nastepna, nie ma aktualnej nuty."""
        self.load([(0.0, 0.2, 60), (1.0, 1.2, 62)])

        self.engine.play()
        time.sleep(0.5)

        snapshot = self.engine.snapshot()

        self.assertIsNone(snapshot["noteName"])
        self.assertIsNone(snapshot["frequency"])
        self.assertEqual(snapshot["state"], "playing")


# ============================================================
# SEEK
# ============================================================


class TestSeek(EngineTestCase):
    def test_seek_do_ciszy(self):
        """Miedzy nutami nie ma czego wznawiac - czekamy na nastepna."""
        self.load([(0.0, 1.0, 60), (3.0, 4.0, 62)])

        self.engine.play()
        time.sleep(0.1)

        before = len(self.transport.events)
        self.engine.seek(2.0)

        self.assertAlmostEqual(self.engine.position, 2.0, places=2)

        time.sleep(0.2)
        nowe = self.transport.since(before)

        # Po seeku nie ma zadnego PLAY (w 2.0 s trwa cisza).
        self.assertEqual(self.transport.fdd_since(before), ["STOP"])

    def test_seek_do_srodka_nuty_gra_ja_od_razu(self):
        """119.2 NOTE_ON / 121.8 NOTE_OFF + seek 120 -> natychmiast ta nuta."""
        self.load([(119.2, 121.8, 52), (130.0, 131.0, 55)])

        self.engine.play()
        time.sleep(0.05)

        self.engine.seek(120.0)
        time.sleep(0.2)

        plays = self.transport.plays()

        # Dokladnie jedna nuta od razu po seeku (E3 = 164.81 Hz).
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0], "PLAY 164.81")

        # ...i nadal gra 1.8 s pozniej, bez ponownego PLAY.
        time.sleep(1.3)
        self.assertEqual(len(self.transport.plays()), 1)
        self.assertIsNotNone(self.engine.snapshot()["noteName"])

    def test_seek_podczas_grania(self):
        self.load([(0.0, 10.0, 60)])

        self.engine.play()
        time.sleep(0.1)
        self.engine.seek(5.0)

        self.assertIs(self.engine.state, PlaybackState.PLAYING)
        self.assertAlmostEqual(self.engine.position, 5.0, places=1)

    def test_seek_podczas_pauzy(self):
        self.load([(0.0, 10.0, 60)])

        self.engine.play()
        time.sleep(0.1)
        self.engine.pause()

        before = len(self.transport.events)
        self.engine.seek(7.0)
        time.sleep(0.15)

        self.assertIs(self.engine.state, PlaybackState.PAUSED)
        self.assertAlmostEqual(self.engine.position, 7.0, places=2)
        # Pauza + seek nie wysylaja zadnych nowych komend.
        self.assertEqual(self.transport.since(before), [])

    def test_seek_przy_stopnie_ustawia_pozycje(self):
        self.load([(0.0, 10.0, 60)])

        self.engine.seek(4.0)

        self.assertIs(self.engine.state, PlaybackState.STOPPED)
        self.assertAlmostEqual(self.engine.position, 4.0, places=2)

    def test_seek_poza_zakres_jest_klamrowany(self):
        self.load([(0.0, 3.0, 60)])

        self.engine.seek(999.0)
        self.assertAlmostEqual(self.engine.position, 3.0, places=2)

        self.engine.seek(-5.0)
        self.assertAlmostEqual(self.engine.position, 0.0, places=2)

    def test_wiele_szybkich_seekow(self):
        self.load([(0.0, 10.0, 60)])

        self.engine.play()

        for position in (1.0, 2.0, 3.0, 4.0, 5.0):
            self.engine.seek(position)

        time.sleep(0.1)

        self.assertIs(self.engine.state, PlaybackState.PLAYING)
        self.assertAlmostEqual(self.engine.position, 5.0, delta=0.2)

    def test_stary_scheduler_nie_wysyla_po_seeku(self):
        """Po seeku w przod nie moze przyjsc spozniony PLAY ze starej pozycji."""
        self.load([(0.0, 1.0, 60), (1.0, 2.0, 62), (2.0, 3.0, 64), (50.0, 51.0, 65)])

        self.engine.play()
        time.sleep(0.05)

        before = len(self.transport.events)
        self.engine.seek(49.0)
        time.sleep(0.4)

        nowe = [text for _, text in self.transport.since(before)]

        # Jedyna komenda linii FDD to STOP z seeka (drum ma wlasny reset).
        self.assertEqual(self.transport.fdd_since(before), ["STOP"])

    def test_stary_scheduler_nie_wysyla_po_stop(self):
        self.load([(0.0, 1.0, 60), (1.0, 2.0, 62), (2.0, 3.0, 64)])

        self.engine.play()
        time.sleep(0.1)

        before = len(self.transport.events)
        self.engine.stop()
        time.sleep(0.4)

        self.assertEqual(self.transport.fdd_since(before), ["STOP"])


# ============================================================
# PAUZA / WZNOWIENIE
# ============================================================


class TestPauza(EngineTestCase):
    def test_pauza_zatrzymuje_i_zamraza_pozycje(self):
        self.load([(0.0, 5.0, 60)])

        self.engine.play()
        time.sleep(0.15)
        self.engine.pause()

        position = self.engine.position
        self.assertIs(self.engine.state, PlaybackState.PAUSED)
        self.assertIn("STOP", self.transport.texts())
        self.assertIsNone(self.engine.snapshot()["noteName"])

        time.sleep(0.2)
        self.assertAlmostEqual(self.engine.position, position, places=3)

    def test_resume_wznawia_nute_w_toku(self):
        self.load([(0.0, 5.0, 60)])

        self.engine.play()
        time.sleep(0.15)
        self.engine.pause()

        before = len(self.transport.events)
        self.engine.resume()
        time.sleep(0.1)

        nowe = [text for _, text in self.transport.since(before)]

        # STOP (nowy plan) + natychmiastowe wznowienie trwajacej nuty.
        self.assertEqual(self.transport.fdd_since(before), ["STOP", "PLAY 261.63"])
        self.assertIs(self.engine.state, PlaybackState.PLAYING)

    def test_podwojna_pauza_i_podwojny_play(self):
        self.load([(0.0, 5.0, 60)])

        self.engine.play()
        self.engine.play()          # drugi play nic nie zmienia
        time.sleep(0.05)

        self.engine.pause()
        self.engine.pause()         # druga pauza nic nie zmienia

        self.assertIs(self.engine.state, PlaybackState.PAUSED)

    def test_pause_podczas_stop_nic_nie_psuje(self):
        self.load([(0.0, 5.0, 60)])

        self.engine.pause()
        self.assertIs(self.engine.state, PlaybackState.STOPPED)


# ============================================================
# TRACK / TRANSPOZYCJA
# ============================================================


class TestZmianaTracku(EngineTestCase):
    def _two_track_file(self) -> Path:
        midi = mido.MidiFile(type=1, ticks_per_beat=TPB)
        conductor = mido.MidiTrack()
        midi.tracks.append(conductor)
        conductor.append(mido.MetaMessage("set_tempo", tempo=TEMPO, time=0))

        for name, note in (("Bas", 48), ("Wysoki", 72)):
            track = mido.MidiTrack()
            midi.tracks.append(track)
            track.append(mido.MetaMessage("track_name", name=name, time=0))
            track.append(mido.Message("note_on", note=note, velocity=100, time=0))
            track.append(
                mido.Message("note_off", note=note, velocity=0, time=4 * TPB)
            )

        path = self.tmp / "dwa.mid"
        midi.save(path)

        return path

    def test_zmiana_tracku_zachowuje_pozycje_i_stan(self):
        self.engine.load_file(self._two_track_file(), 1)

        self.engine.play()
        time.sleep(0.15)
        self.engine.seek(1.0)
        time.sleep(0.05)

        before = len(self.transport.events)
        self.engine.set_track(2)
        time.sleep(0.15)

        self.assertEqual(self.engine.snapshot()["track"], 2)
        self.assertEqual(self.engine.snapshot()["trackName"], "Wysoki")
        self.assertIs(self.engine.state, PlaybackState.PLAYING)
        # Pozycja zachowana (utwor gral dalej przez chwile po seeku).
        self.assertGreaterEqual(self.engine.position, 1.0)
        self.assertLess(self.engine.position, 1.6)

        nowe = [text for _, text in self.transport.since(before)]

        # STOP + natychmiastowe PLAY nowej nuty (w 1.0 s trwa).
        self.assertEqual(self.transport.fdd_since(before), ["STOP", "PLAY 261.63"])

    def test_zmiana_tracku_w_pauzie_nie_gra(self):
        self.engine.load_file(self._two_track_file(), 1)

        self.engine.play()
        time.sleep(0.1)
        self.engine.pause()
        self.engine.seek(1.0)

        before = len(self.transport.events)
        self.engine.set_track(2)
        time.sleep(0.15)

        self.assertIs(self.engine.state, PlaybackState.PAUSED)
        self.assertEqual(self.transport.since(before), [])

    def test_zmiana_pliku_zeruje_pozycje(self):
        self.engine.load_file(self._two_track_file(), 1)
        self.engine.play()
        time.sleep(0.1)

        self.engine.load_file(self._two_track_file(), 2)

        self.assertIs(self.engine.state, PlaybackState.STOPPED)
        self.assertAlmostEqual(self.engine.position, 0.0, places=3)

    def test_zmiana_transpozycji_w_trakcie_grania(self):
        self.load([(0.0, 5.0, 72)])   # C5

        self.engine.play()
        time.sleep(0.1)

        before = len(self.transport.events)
        self.engine.set_transpose("low")
        time.sleep(0.15)

        nowe = [text for _, text in self.transport.since(before)]

        self.assertEqual(self.engine.snapshot()["transpose"], "low")
        self.assertIs(self.engine.state, PlaybackState.PLAYING)
        # W trybie low C5 gra jako C3 = 130.81 Hz.
        self.assertEqual(self.transport.fdd_since(before), ["STOP", "PLAY 130.81"])


# ============================================================
# SPRZET
# ============================================================


class TestSprzet(EngineTestCase):
    def test_play_bez_polaczenia_nie_udaje_grania(self):
        """PLAY bez Arduino: zostajemy w STOPPED i pokazujemy blad."""
        self.load([(0.0, 5.0, 60)])
        self.engine.disconnect()

        self.engine.play()

        snapshot = self.engine.snapshot()
        self.assertIs(self.engine.state, PlaybackState.STOPPED)
        self.assertFalse(snapshot["hardware"]["connected"])
        self.assertIsNotNone(snapshot["hardware"]["error"])

    def test_rozlaczenie_podczas_grania_pauzuje(self):
        """Rozlaczenie w trakcie utworu nie moze 'grac dalej w ciszy'."""
        self.load([(0.0, 5.0, 60)])

        self.engine.play()
        time.sleep(0.1)
        self.engine.disconnect()

        snapshot = self.engine.snapshot()

        self.assertIs(self.engine.state, PlaybackState.PAUSED)
        self.assertFalse(snapshot["hardware"]["connected"])
        self.assertTrue(self.transport.closed)

    def test_awaria_serial_pauzuje_i_raportuje(self):
        transport = FakeTransport()
        engine = PlaybackEngine(connect_fn=lambda port: transport, keepalive=0.2)
        engine.start()

        try:
            engine.connect()
            path = write_midi(
                self.tmp / "awaria.mid", [(0.0, 0.2, 60), (0.3, 5.0, 62)]
            )
            engine.load_file(path, 0)
            engine.play()
            time.sleep(0.15)

            self.assertIs(engine.state, PlaybackState.PLAYING)

            transport.fail_after_next(1)
            time.sleep(0.5)

            snapshot = engine.snapshot()

            self.assertIs(engine.state, PlaybackState.PAUSED)
            self.assertFalse(snapshot["hardware"]["connected"])
            self.assertIsNotNone(snapshot["hardware"]["error"])
            self.assertIsNone(snapshot["noteName"])
        finally:
            engine.shutdown()

    def test_keepalive_podtrzymuje_dluga_nute(self):
        self.load([(0.0, 2.0, 60)])

        self.engine.play()
        time.sleep(1.0)

        pings = [text for text in self.transport.texts() if text == "PING"]

        self.assertGreaterEqual(len(pings), 2)
        self.assertIs(self.engine.state, PlaybackState.PLAYING)

    def test_keepalive_dziala_na_prawdziwym_dry_run_linku(self):
        """Regresja: DryRunLink nie mial ping(), wiec watchdog silnika
        uznawal to za awarie sprzetu i pauzowal utwor po ~1 s."""
        from floppy_link import DryRunLink

        engine = PlaybackEngine(
            connect_fn=lambda port: DryRunLink(),
            keepalive=0.2,
        )
        engine.start()

        try:
            engine.connect()
            path = write_midi(self.tmp / "dryrun.mid", [(0.0, 1.5, 60)])
            engine.load_file(path, 0)
            engine.play()

            time.sleep(0.8)

            self.assertIs(engine.state, PlaybackState.PLAYING)
            self.assertIsNone(engine.snapshot()["hardware"]["error"])
        finally:
            engine.shutdown()


# ============================================================
# TIMING I WSPOLBIEZNOSC
# ============================================================


class TestTiming(EngineTestCase):
    def test_brak_narastajacego_dryfu(self):
        """16 nut po 0.1 s - koniec nie moze sie rozjechac z czasem utworu."""
        self.load([(index * 0.1, index * 0.1 + 0.09, 60 + index) for index in range(16)])

        duration = self.engine.duration
        started = time.monotonic()
        self.engine.play()

        self.assertTrue(self.wait_for_state(PlaybackState.STOPPED, timeout=5.0))
        actual = time.monotonic() - started

        self.assertLess(abs(actual - duration), 0.05, f"dryf {actual - duration:+.4f} s")

    def test_komendy_ida_w_czasie_utworu(self):
        self.load([(0.0, 0.2, 60), (0.5, 0.7, 62)])

        started = time.monotonic()
        self.engine.play()
        self.assertTrue(self.wait_for_state(PlaybackState.STOPPED, timeout=3.0))

        commands = self.transport.commands()
        plays = [(at, text) for at, text in commands if text.startswith("PLAY")]

        self.assertEqual(len(plays), 2)
        self.assertAlmostEqual(plays[0][0], 0.0, delta=0.06)
        self.assertAlmostEqual(plays[1][0], 0.5, delta=0.06)
        self.assertGreater(time.monotonic() - started, 0.6)

    def test_rownolegle_sterowanie_nie_psuje_stanu(self):
        self.load([(0.0, 5.0, 60), (5.0, 9.0, 62)])

        def hammer():
            for _ in range(30):
                self.engine.seek(1.0)
                self.engine.pause()
                self.engine.resume()
                self.engine.seek(2.0)

        threads = [threading.Thread(target=hammer) for _ in range(3)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        self.engine.stop()

        self.assertIs(self.engine.state, PlaybackState.STOPPED)
        self.assertAlmostEqual(self.engine.position, 0.0, places=3)

    def test_play_podczas_grania_nie_restartuje(self):
        self.load([(0.0, 5.0, 60)])

        self.engine.play()
        time.sleep(0.2)
        position = self.engine.position

        self.engine.play()
        time.sleep(0.05)

        self.assertGreaterEqual(self.engine.position, position)


if __name__ == "__main__":
    unittest.main()


# ============================================================
# VHS DRUM (manualne sterowanie)
# ============================================================


class TestDrum(EngineTestCase):
    def drum_state(self) -> dict:
        return self.engine.snapshot()["drum"]

    def test_connect_zeruje_beben(self):
        """Fail-safe: po polaczeniu beben ma byc zatrzymany."""
        self.assertIn("DRUM 0", self.transport.raw_texts())

    def test_set_drum_wysyla_komende(self):
        self.engine.set_drum(80)

        self.assertIn("DRUM 80", self.transport.raw_texts())
        self.assertEqual(self.drum_state()["value"], 80)
        self.assertTrue(self.drum_state()["running"])

    def test_stop_drum_zeruje(self):
        self.engine.set_drum(120)
        self.engine.stop_drum()

        self.assertEqual(self.transport.raw_texts()[-1], "DRUM 0")
        self.assertEqual(self.drum_state()["value"], 0)
        self.assertFalse(self.drum_state()["running"])

    def test_zakres_pwm_jest_sprawdzany(self):
        self.transport.events.clear()   # pomijamy DRUM 0 z fail-safe przy connect

        for bad in (-1, 256, 1000):
            with self.assertRaises(EngineError):
                self.engine.set_drum(bad)

        # Nic nie wyszlo po Serial.
        self.assertFalse(
            [text for text in self.transport.raw_texts() if text.startswith("DRUM ")]
        )

    def test_start_uzywa_ostatniej_niezerowej_wartosci(self):
        self.engine.set_drum(90)
        self.engine.stop_drum()
        self.engine.start_drum()

        self.assertEqual(self.transport.raw_texts()[-1], "DRUM 90")
        self.assertEqual(self.drum_state()["value"], 90)

    def test_start_bez_historii_uzywa_konserwatywnej_wartosci(self):
        self.engine.start_drum()

        self.assertEqual(self.transport.raw_texts()[-1], f"DRUM {DRUM_START_VALUE}")
        self.assertEqual(self.drum_state()["value"], DRUM_START_VALUE)

    def test_ton_bebna(self):
        self.engine.set_drum_tone(400)

        self.assertIn("DRUMF 400", self.transport.raw_texts())
        self.assertEqual(self.drum_state()["toneHz"], 400)

    def test_ton_zero_to_tryb_dc(self):
        self.engine.set_drum_tone(400)
        self.engine.set_drum_tone(0)

        self.assertEqual(self.transport.raw_texts()[-1], "DRUMF 0")
        self.assertEqual(self.drum_state()["toneHz"], 0)

    def test_zakres_tonu_jest_sprawdzany(self):
        for bad in (5, 19, 2001, -100):
            with self.assertRaises(EngineError):
                self.engine.set_drum_tone(bad)

    def test_reconnect_zatrzymuje_beben(self):
        """Po reconnect motor NIE moze sam ruszyc."""
        self.engine.set_drum(150)
        self.assertTrue(self.drum_state()["running"])

        self.transport.events.clear()
        self.engine.connect()

        self.assertIn("DRUM 0", self.transport.raw_texts())
        self.assertEqual(self.drum_state()["value"], 0)
        self.assertFalse(self.drum_state()["running"])

    def test_rozłączenie_zeruje_stan_bebna(self):
        self.engine.set_drum(100)
        self.engine.disconnect()

        state = self.drum_state()

        self.assertFalse(state["connected"])
        self.assertFalse(state["running"])
        self.assertEqual(state["value"], 0)
        self.assertIsNone(state["output"])

    def test_drum_bez_polaczenia_to_blad(self):
        self.engine.disconnect()

        with self.assertRaises(EngineError):
            self.engine.set_drum(50)

        with self.assertRaises(EngineError):
            self.engine.stop_drum()

        with self.assertRaises(EngineError):
            self.engine.set_drum_tone(400)

    def test_awaria_serial_przy_drum_raportuje(self):
        transport = FakeTransport()
        engine = PlaybackEngine(connect_fn=lambda port: transport, keepalive=0.2)
        engine.start()

        try:
            engine.connect()
            transport.fail_after_next(1)

            with self.assertRaises(EngineError):
                engine.set_drum(60)

            self.assertFalse(engine.snapshot()["hardware"]["connected"])
        finally:
            engine.shutdown()

    def test_status_z_firmware_potwierdza_pwm(self):
        """drum_out z STATUS trafia do stanu (firmware moze miec wlasny limit)."""
        self.transport.queue_line(
            "STATUS track=10 dir=away homed=1 playing=0 track0=0 hz=0.00 drum=200 drum_out=128 drumf=350"
        )

        time.sleep(0.35)   # watek roboczy odbiera STATUS na postoju

        state = self.drum_state()

        self.assertEqual(state["output"], 128)
        self.assertEqual(state["toneHz"], 350)

    def test_snapshot_ma_pelny_stan_bebna(self):
        state = self.drum_state()

        for key in ("value", "output", "toneHz", "lastValue", "running", "connected", "minHz", "maxHz"):
            self.assertIn(key, state)

    def test_drum_nie_zatrzymuje_sie_sam(self):
        """Beben jest reczny - watchdog krokow FDD nie moze go ruszac."""
        self.engine.set_drum(70)

        time.sleep(0.6)

        self.assertEqual(self.drum_state()["value"], 70)
        self.assertTrue(self.drum_state()["running"])


def write_two_track_midi(path, first, second, name_a="FDD", name_b="Drum") -> Path:
    """Plik z konduktorem + dwoma trackami (1 = FDD, 2 = drum)."""
    midi = mido.MidiFile(type=1, ticks_per_beat=TPB)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(mido.MetaMessage("set_tempo", tempo=TEMPO, time=0))

    for name, notes in ((name_a, first), (name_b, second)):
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage("track_name", name=name, time=0))

        events = []

        for start, end, note in notes:
            events.append((round(start * TICKS_PER_SECOND), 0, note))
            events.append((round(end * TICKS_PER_SECOND), 1, note))

        events.sort(key=lambda event: (event[0], event[1]))

        previous = 0

        for tick, kind, note in events:
            track.append(
                mido.Message(
                    "note_on" if kind == 0 else "note_off",
                    note=note,
                    velocity=100 if kind == 0 else 0,
                    time=tick - previous,
                )
            )
            previous = tick

    midi.save(path)

    return path


class DualVoiceTestCase(EngineTestCase):
    """Baza dla testow dwoch glosow (FDD + VHS drum, jeden zegar)."""

    def setUp(self):
        super().setUp()
        self.engine.shutdown()
        self.transport = FakeTransport()
        self.engine = PlaybackEngine(
            connect_fn=lambda port: self.transport,
            keepalive=0.2,
            drum_track_index=2,
        )
        self.engine.start()
        self.assertTrue(self.engine.connect())

    def load_dual(self, fdd_notes, drum_notes):
        path = write_two_track_midi(
            self.tmp / "dual.mid", fdd_notes, drum_notes
        )
        self.engine.load_file(path, 1)

        return path

    def drum_events(self) -> list[str]:
        return [
            text
            for text in self.transport.raw_texts()
            if text.startswith(("DRUM ", "DRUMF "))
        ]

    def fdd_events(self) -> list[str]:
        return [
            text
            for text in self.transport.raw_texts()
            if text.startswith(("PLAY ", "STOP"))
        ]


class TestWspolnyTimeline(DualVoiceTestCase):
    def test_timeline_ma_obie_linie_posortowane(self):
        self.load_dual([(0.0, 0.5, 60)], [(0.25, 0.75, 72)])

        timeline = self.engine._timeline
        lanes = {command.lane for command in timeline.commands}

        self.assertEqual(lanes, {"fdd", "drum"})

        times = [command.time for command in timeline.commands]
        self.assertEqual(times, sorted(times))

    def test_dwa_tracki_graja_rownoczesnie(self):
        self.load_dual([(0.0, 1.0, 60)], [(0.0, 1.0, 72)])
        self.transport.events.clear()

        self.engine.play()
        time.sleep(0.25)

        snapshot = self.engine.snapshot()

        self.assertEqual(snapshot["state"], "playing")
        self.assertIsNotNone(snapshot["noteName"])          # FDD gra
        self.assertEqual(snapshot["drum"]["controlledBy"], "midi")
        self.assertIsNotNone(snapshot["drum"]["midiNoteName"])  # beben gra
        self.assertIn("PLAY 261.63", self.fdd_events())
        self.assertIn(f"DRUM {DRUM_DRIVE_DEFAULT}", self.drum_events())

    def test_beben_dostaje_drive_i_ton(self):
        self.load_dual([(0.0, 1.0, 60)], [(0.0, 1.0, 69)])   # A4 = 440 Hz
        self.transport.events.clear()

        self.engine.play()
        time.sleep(0.2)

        events = self.drum_events()

        self.assertIn("DRUMF 110", events)
        self.assertIn(f"DRUM {DRUM_DRIVE_DEFAULT}", events)
        self.assertEqual(self.engine.snapshot()["drum"]["value"], DRUM_DRIVE_DEFAULT)

    def test_cisza_w_bebnie_daje_drum_0(self):
        """Przerwa w tracku bebna -> DRUM 0."""
        self.load_dual([(0.0, 2.0, 60)], [(0.0, 0.2, 72), (1.0, 1.2, 74)])
        self.transport.events.clear()

        self.engine.play()
        time.sleep(0.6)

        self.assertIn("DRUM 0", self.drum_events())

    def test_legato_nie_wysyla_zbednego_drum_0(self):
        """Nuty stykajace sie: tylko DRUMF, bez przerwy w dzwieku."""
        self.load_dual([(0.0, 2.0, 60)], [(0.0, 0.3, 72), (0.3, 0.6, 74)])
        self.transport.events.clear()

        self.engine.play()
        time.sleep(0.75)

        events = self.drum_events()

        # Dokladnie ta sekwencja: reset, pierwsza nuta, ZMIANA TONU bez
        # przerwy, i DRUM 0 dopiero po ostatniej nucie.
        self.assertEqual(
            events,
            ["DRUM 0", "DRUMF 131", f"DRUM {DRUM_DRIVE_DEFAULT}", "DRUMF 147", "DRUM 0"],
        )

    def test_none_wylacza_midi_dla_bebna(self):
        self.engine.set_drum_track(None)
        self.load_dual([(0.0, 0.5, 60)], [(0.0, 1.0, 72)])
        self.transport.events.clear()

        self.engine.play()
        time.sleep(0.3)

        snapshot = self.engine.snapshot()

        self.assertIsNone(snapshot["drum"]["midiTrack"])
        self.assertEqual(snapshot["drum"]["controlledBy"], "manual")
        self.assertFalse(
            [event for event in self.drum_events() if event.startswith("DRUMF ")]
        )


class TestDrumPitch(DualVoiceTestCase):
    def test_octave_folding_beben_w_gore(self):
        from playback.timeline import build_drum_schedule

        commands, _ = build_drum_schedule(
            [NoteSpan(0.0, 1.0, 33, 100, 0)],   # A1 = 55 Hz
            min_hz=110.0,
            max_hz=880.0,
        )

        self.assertAlmostEqual(commands[0].hz, 110.0, places=1)

    def test_octave_folding_beben_w_dol(self):
        from playback.timeline import build_drum_schedule

        commands, _ = build_drum_schedule(
            [NoteSpan(0.0, 1.0, 105, 100, 0)],  # A7 = 3520 Hz
            min_hz=110.0,
            max_hz=880.0,
        )

        self.assertAlmostEqual(commands[0].hz, 880.0, places=1)

    def test_zakres_bebna_jest_niezalezny_od_fdd(self):
        self.load_dual([(0.0, 1.0, 69)], [(0.0, 1.0, 69)])   # ta sama nuta A4

        self.engine.play()
        time.sleep(0.2)

        snapshot = self.engine.snapshot()

        # FDD (130-330) sklada A4 do A3 = 220 Hz, a beben domyslnie w trybie
        # "low" (110-220) sklada ja do A2 = 110 Hz - kazdy mapper jest inny.
        self.assertEqual(snapshot["noteName"], "A3")
        self.assertEqual(snapshot["drum"]["toneHz"], 110.0)

    def test_zakres_bebna_w_stanie(self):
        drum = self.engine.snapshot()["drum"]

        self.assertEqual(drum["range"], {"minHz": 110.0, "maxHz": 880.0})
        self.assertEqual(drum["drive"], DRUM_DRIVE_DEFAULT)


class TestSeekDwochLinii(DualVoiceTestCase):
    def test_seek_w_srodek_nuty_bebna(self):
        # Dwie rozne nuty bebna - seek w druga wymaga zmiany tonu.
        self.load_dual([(0.0, 10.0, 60)], [(0.0, 2.0, 72), (2.0, 6.0, 74)])

        self.engine.play()
        time.sleep(0.3)

        before = len(self.transport.events)
        self.engine.seek(3.5)
        time.sleep(0.2)

        drum = [text for _, text in self.transport.since(before) if text.startswith("DRUM")]

        # Reset + natychmiastowe wznowienie nuty bebna (nowa wysokosc).
        self.assertEqual(drum, ["DRUM 0", "DRUMF 147", f"DRUM {DRUM_DRIVE_DEFAULT}"])

        snapshot = self.engine.snapshot()

        self.assertEqual(snapshot["drum"]["controlledBy"], "midi")
        self.assertIsNotNone(snapshot["drum"]["midiNoteName"])

    def test_seek_w_cisze_bebna(self):
        self.load_dual([(0.0, 10.0, 60)], [(2.0, 3.0, 72)])

        self.engine.play()
        time.sleep(0.1)

        before = len(self.transport.events)
        self.engine.seek(5.0)
        time.sleep(0.2)

        drum = [text for _, text in self.transport.since(before) if text.startswith("DRUM")]

        # W 5 s beben milczy - tylko reset.
        self.assertEqual(drum, ["DRUM 0"])
        self.assertFalse(self.engine.snapshot()["drum"]["running"])

    def test_seek_wznawia_obie_linie(self):
        self.load_dual([(0.0, 10.0, 60)], [(0.0, 10.0, 72)])

        self.engine.play()
        time.sleep(0.1)

        before = len(self.transport.events)
        self.engine.seek(4.0)
        time.sleep(0.2)

        sent = [text for _, text in self.transport.since(before)]

        self.assertIn("PLAY 261.63", sent)
        self.assertIn(f"DRUM {DRUM_DRIVE_DEFAULT}", sent)
        self.assertEqual(self.engine.snapshot()["drum"]["toneHz"], 131.0)


class TestTransportDwochLinii(DualVoiceTestCase):
    def test_pauza_zatrzymuje_oba(self):
        self.load_dual([(0.0, 5.0, 60)], [(0.0, 5.0, 72)])

        self.engine.play()
        time.sleep(0.15)

        before = len(self.transport.events)
        self.engine.pause()
        time.sleep(0.1)

        sent = [text for _, text in self.transport.since(before)]

        self.assertIn("STOP", sent)
        self.assertIn("DRUM 0", sent)
        self.assertIs(self.engine.state, PlaybackState.PAUSED)
        self.assertEqual(self.engine.snapshot()["drum"]["controlledBy"], "manual")

    def test_resume_wznawia_oba(self):
        self.load_dual([(0.0, 5.0, 60)], [(0.0, 5.0, 72)])

        self.engine.play()
        time.sleep(0.15)
        self.engine.pause()

        before = len(self.transport.events)
        self.engine.resume()
        time.sleep(0.15)

        sent = [text for _, text in self.transport.since(before)]
        fdd = [text for text in sent if text.startswith(("PLAY", "STOP"))]
        drum = [text for text in sent if text.startswith("DRUM")]

        self.assertEqual(fdd, ["STOP", "PLAY 261.63"])
        # Reset, a potem wznowienie napedu. Tonu nie powtarzamy, bo firmware
        # go nie zgubil (cache) - i to jest wlasnie zamierzone.
        self.assertEqual(drum, ["DRUM 0", f"DRUM {DRUM_DRIVE_DEFAULT}"])

        snapshot = self.engine.snapshot()

        self.assertEqual(snapshot["drum"]["toneHz"], 131.0)
        self.assertEqual(snapshot["drum"]["controlledBy"], "midi")

    def test_stop_zatrzymuje_oba_i_zeruje(self):
        self.load_dual([(0.0, 5.0, 60)], [(0.0, 5.0, 72)])

        self.engine.play()
        time.sleep(0.15)

        before = len(self.transport.events)
        self.engine.stop()
        time.sleep(0.1)

        sent = [text for _, text in self.transport.since(before)]

        self.assertIn("STOP", sent)
        self.assertIn("DRUM 0", sent)
        self.assertIs(self.engine.state, PlaybackState.STOPPED)
        self.assertAlmostEqual(self.engine.position, 0.0, places=3)

    def test_rozlaczenie_zatrzymuje_beben(self):
        self.load_dual([(0.0, 5.0, 60)], [(0.0, 5.0, 72)])

        self.engine.play()
        time.sleep(0.15)

        before = len(self.transport.events)
        self.engine.disconnect()
        time.sleep(0.1)

        sent = [text for _, text in self.transport.since(before)]

        self.assertIn("DRUM 0", sent)
        self.assertFalse(self.engine.snapshot()["drum"]["connected"])

    def test_manualne_sterowanie_zablokowane_podczas_midi(self):
        self.load_dual([(0.0, 5.0, 60)], [(0.0, 5.0, 72)])

        self.engine.play()
        time.sleep(0.15)

        self.assertEqual(self.engine.snapshot()["drum"]["controlledBy"], "midi")

        for call in (
            lambda: self.engine.set_drum(50),
            lambda: self.engine.stop_drum(),
            lambda: self.engine.set_drum_tone(300),
        ):
            with self.assertRaises(EngineError):
                call()

    def test_po_stopie_manualWraca(self):
        self.load_dual([(0.0, 5.0, 60)], [(0.0, 5.0, 72)])

        self.engine.play()
        time.sleep(0.1)
        self.engine.stop()
        time.sleep(0.1)

        self.engine.set_drum(90)
        self.engine.set_drum_tone(400)

        drum = self.engine.snapshot()["drum"]

        self.assertEqual(drum["controlledBy"], "manual")
        self.assertEqual(drum["value"], 90)
        self.assertEqual(drum["toneHz"], 400.0)

    def test_zmiana_tracku_bebna_w_trakcie_grania(self):
        self.load_dual([(0.0, 5.0, 60)], [(0.0, 5.0, 72)])

        self.engine.play()
        time.sleep(0.15)

        self.engine.set_drum_track(None)
        time.sleep(0.1)

        snapshot = self.engine.snapshot()

        self.assertIsNone(snapshot["drum"]["midiTrack"])
        self.assertIs(snapshot["state"], "playing")


class FakeSerial:
    """Minimalny zamiennik serial.Serial - do testow FloppyLink."""

    def __init__(self):
        self.written: list[str] = []
        self._incoming = b""

    @property
    def in_waiting(self) -> int:
        return len(self._incoming)

    def read(self, size: int) -> bytes:
        chunk, self._incoming = self._incoming[:size], self._incoming[size:]
        return chunk

    def write(self, data: bytes) -> int:
        self.written.append(data.decode("ascii").strip())
        return len(data)

    def close(self) -> None:
        pass

    def feed(self, *lines: str) -> None:
        self._incoming += ("".join(line + "\n" for line in lines)).encode("ascii")


def make_link() -> tuple:
    from floppy_link import FloppyLink

    link = FloppyLink.__new__(FloppyLink)     # bez otwierania portu
    link.port = "/dev/fake"
    link.baud = 115200
    link._buffer = ""
    link._serial = FakeSerial()

    return link, link._serial


class TestHomingRetry(EngineTestCase):
    """Retry homingu: kazda proba to znowu pelny budzet krokow w strone TRACK0."""

    def test_retry_po_home_failed(self):
        link, serial = make_link()
        serial.feed("HOMING", "ERR HOME_FAILED", "HOMING", "READY")

        self.assertTrue(link.wait_ready(timeout=2.0, echo=lambda line: None))
        self.assertEqual(serial.written.count("HOME"), 1)

    def test_dwa_razy_failed_potem_ready(self):
        link, serial = make_link()
        serial.feed(
            "HOMING", "ERR HOME_FAILED",
            "HOMING", "ERR HOME_FAILED",
            "HOMING", "READY",
        )

        self.assertTrue(link.wait_ready(timeout=2.0, echo=lambda line: None))
        self.assertEqual(serial.written.count("HOME"), 2)

    def test_po_wyczerpaniu_prob_podnosi_blad(self):
        link, serial = make_link()
        serial.feed(*(["ERR HOME_FAILED"] * 10))

        from floppy_link import SerialLinkError

        with self.assertRaises(SerialLinkError):
            link.wait_ready(timeout=2.0, echo=lambda line: None)

        self.assertEqual(serial.written.count("HOME"), 2)

    def test_inny_blad_nie_jest_ponawiany(self):
        link, serial = make_link()
        serial.feed("ERR POS_LOST")

        from floppy_link import SerialLinkError

        with self.assertRaises(SerialLinkError):
            link.wait_ready(timeout=2.0, echo=lambda line: None)

        self.assertEqual(serial.written, [])


class TestHomingAction(EngineTestCase):
    def test_metoda_home_w_silniku(self):
        self.transport.queue_line("HOMING")
        self.transport.queue_line("READY")

        self.assertTrue(self.engine.home())
        self.assertIn("HOME", self.transport.raw_texts())
        self.assertIsNone(self.engine.snapshot()["hardware"]["error"])

    def test_home_bez_polaczenia(self):
        self.engine.disconnect()

        with self.assertRaises(EngineError):
            self.engine.home()


class TestBlindHomingFallback(EngineTestCase):
    """Gdy czujnik TRACK0 padnie, stacja i tak musi wstac (HOME BLIND)."""

    def test_fallback_na_slepo_po_wyczerpaniu_prob(self):
        link, serial = make_link()
        serial.feed(
            "HOMING", "ERR HOME_FAILED",
            "HOMING", "ERR HOME_FAILED",
            "HOMING", "ERR HOME_FAILED",
            "HOMING_BLIND", "READY",
        )

        self.assertTrue(link.wait_ready(timeout=3.0, echo=lambda line: None))
        self.assertEqual(serial.written.count("HOME"), 2)
        self.assertEqual(serial.written.count("HOME BLIND"), 1)

    def test_fallback_mozna_wylaczyc(self):
        link, serial = make_link()
        serial.feed(*(["ERR HOME_FAILED"] * 8))

        from floppy_link import SerialLinkError

        with self.assertRaises(SerialLinkError):
            link.wait_ready(timeout=2.0, echo=lambda line: None, blind_fallback=False)

        # Retry czujnika dziala dalej, ale NIE ma awaryjnego homingu na slepo.
        self.assertEqual(serial.written, ["HOME", "HOME"])
        self.assertNotIn("HOME BLIND", serial.written)

    def test_sam_home_blind_tez_dziala(self):
        link, serial = make_link()
        serial.feed("OK", "HOMING_BLIND", "READY")

        self.assertTrue(link.wait_ready(timeout=2.0, echo=lambda line: None))


class TestHdd(EngineTestCase):
    """Trzecia linia: HDD perkusja (one-shot, bez wysokosci dzwieku)."""

    def setUp(self):
        super().setUp()
        self.engine.shutdown()
        self.transport = FakeTransport()
        self.engine = PlaybackEngine(
            connect_fn=lambda port: self.transport,
            keepalive=0.2,
            hdd_track_index=2,
        )
        self.engine.start()
        self.assertTrue(self.engine.connect())

    def load_dual(self, fdd_notes, hdd_notes):
        path = write_two_track_midi(self.tmp / "hdd.mid", fdd_notes, hdd_notes)
        self.engine.load_file(path, 1)

        return path

    def hdd_events(self) -> list[str]:
        return [text for text in self.transport.raw_texts() if text == "HIT"]

    def test_hdd_track_wysyla_uderzenia(self):
        self.load_dual([(0.0, 2.0, 60)], [(0.0, 0.3, 36), (0.8, 1.1, 42)])
        self.transport.events.clear()

        self.engine.play()
        time.sleep(1.5)

        self.assertEqual(len(self.hdd_events()), 2)
        self.assertEqual(self.engine.snapshot()["hdd"]["count"], 2)

    def test_akord_zlewa_sie_w_jedno_uderzenie(self):
        # 3 nuty w tym samym momencie = akord -> jedno uderzenie.
        self.load_dual(
            [(0.0, 1.0, 60)],
            [(0.0, 0.5, 60), (0.0, 0.5, 64), (0.0, 0.5, 67)],
        )
        self.transport.events.clear()

        self.engine.play()
        time.sleep(0.4)

        self.assertEqual(len(self.hdd_events()), 1)

    def test_none_wylacza_hdd(self):
        self.engine.set_hdd_track(None)
        self.load_dual([(0.0, 1.0, 60)], [(0.0, 1.0, 36)])
        self.transport.events.clear()

        self.engine.play()
        time.sleep(0.4)

        self.assertEqual(self.hdd_events(), [])
        self.assertIsNone(self.engine.snapshot()["hdd"]["midiTrack"])

    def test_seek_nie_wznawia_uderzenia(self):
        # HDD to one-shot: seek w srodek utworu nie powinien sztucznie
        # uderzyc, nawet jesli jakas nuta "brzmi" w tym miejscu.
        self.load_dual([(0.0, 10.0, 60)], [(0.0, 0.3, 36)])
        self.engine.play()
        time.sleep(0.1)

        self.transport.events.clear()
        self.engine.seek(5.0)
        time.sleep(0.2)

        self.assertEqual(self.hdd_events(), [])

    def test_stop_zatrzymuje_hdd(self):
        # Reset instrumentow wysyla HDD 0 (przerwanie sekwencji).
        self.load_dual([(0.0, 5.0, 60)], [(0.0, 1.0, 36)])
        self.transport.events.clear()

        self.engine.play()
        time.sleep(0.1)
        self.engine.stop()
        time.sleep(0.1)

        self.assertIn("HDD 0", self.transport.raw_texts())
        self.assertIs(self.engine.state, PlaybackState.STOPPED)

    def test_budowa_schedule_zlewa_szybkie_powtorki(self):
        from playback.timeline import build_hdd_schedule

        spans = [
            NoteSpan(0.0, 0.1, 60, 100, 9),
            NoteSpan(0.05, 0.15, 62, 100, 9),   # blizej niz 110 ms -> zlane
            NoteSpan(0.3, 0.4, 64, 100, 9),
        ]

        commands, stats = build_hdd_schedule(spans)

        self.assertEqual(len(commands), 2)
        self.assertEqual(stats.notes, 2)
        self.assertEqual(stats.skipped, 1)
        self.assertEqual([c.kind for c in commands], ["hit", "hit"])


class TestHddNote(EngineTestCase):
    """Filtr nuty HDD: caly zestaw na jeden instrument = terkot.

    HDD ma jeden dzwiek uderzeniowy, wiec z tracku perkusyjnego wybiera sie
    jedna-nute o charakterze rytmicznym (np. werbel 40 albo stopa 36).
    """

    def setUp(self):
        super().setUp()
        self.engine.shutdown()
        self.transport = FakeTransport()
        self.engine = PlaybackEngine(
            connect_fn=lambda port: self.transport,
            keepalive=0.2,
            hdd_track_index=2,
        )
        self.engine.start()
        self.assertTrue(self.engine.connect())

    def load(self, hdd_notes):
        path = write_two_track_midi(
            self.tmp / "hddnote.mid", [(0.0, 4.0, 60)], hdd_notes
        )
        self.engine.load_file(path, 1)

    def hdd_hits(self):
        return [
            command
            for command in self.engine._timeline.commands
            if command.lane == "hdd"
        ]

    def test_bez_filtra_wszystkie_nuty(self):
        self.load([(0.0, 0.2, 36), (0.5, 0.7, 40), (1.0, 1.2, 42)])

        self.assertEqual(len(self.hdd_hits()), 3)

    def test_filtr_przepuszcza_tylko_wybrana_nute(self):
        self.load([(0.0, 0.2, 36), (0.5, 0.7, 40), (1.0, 1.2, 42)])

        self.engine.set_hdd_note(40)
        hits = self.hdd_hits()

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].note, 40)

    def test_none_przywraca_wszystkie_nuty(self):
        self.load([(0.0, 0.2, 36), (0.5, 0.7, 40)])

        self.engine.set_hdd_note(40)
        self.engine.set_hdd_note(None)

        self.assertEqual(len(self.hdd_hits()), 2)

    def test_lista_dostepnych_nut_w_stanie(self):
        self.load([(0.0, 0.2, 36), (0.5, 0.7, 40), (0.8, 1.0, 40)])

        notes = self.engine.snapshot()["hdd"]["notes"]
        by_note = {option["note"]: option for option in notes}

        self.assertEqual(by_note[40]["count"], 2)
        self.assertEqual(by_note[40]["name"], "Werbel")
        self.assertEqual(by_note[36]["name"], "Stopa")

    def test_nuta_poza_zakresem_daje_blad(self):
        self.load([(0.0, 0.2, 36)])

        with self.assertRaises(EngineError):
            self.engine.set_hdd_note(200)


class TestHddRate(EngineTestCase):
    """Limiter gestosci HDD: werbel na 170 BPM to 1,3 uderzenia/s.

    Utwor szybki (backbeat co 2,2 beatu) - limiter pozwala zejsc do
    half-time (1 uderzenie/s) albo rzadziej, bez zmiany nuty.
    """

    def setUp(self):
        super().setUp()
        self.engine.shutdown()
        self.transport = FakeTransport()
        self.engine = PlaybackEngine(
            connect_fn=lambda port: self.transport,
            keepalive=0.2,
            hdd_track_index=2,
        )
        self.engine.start()
        self.assertTrue(self.engine.connect())

    def load(self, hdd_notes):
        path = write_two_track_midi(
            self.tmp / "hddrate.mid", [(0.0, 6.0, 60)], hdd_notes
        )
        self.engine.load_file(path, 1)

    def hits(self):
        return [c for c in self.engine._timeline.commands if c.lane == "hdd"]

    def test_bez_limitu_wszystkie_uderzenia(self):
        self.load([(t / 2.0, t / 2.0 + 0.1, 40) for t in range(10)])

        self.assertEqual(len(self.hits()), 10)

    def test_limit_1_na_sekunde_przerzedza(self):
        # uderzenia co 0,5 s -> przy limicie 1/s zostaje co drugie
        self.load([(t / 2.0, t / 2.0 + 0.1, 40) for t in range(10)])

        self.engine.set_hdd_rate(1.0)

        self.assertEqual(len(self.hits()), 5)

    def test_limit_nie_lamie_mechaniki(self):
        # nawet "bez limitu" nie schodzi ponizej cyklu park+strike (110 ms)
        self.load([(t / 20.0, t / 20.0 + 0.02, 40) for t in range(20)])

        self.engine.set_hdd_rate(None)

        self.assertLessEqual(len(self.hits()), 20)

    def test_none_przywraca_bez_limitu(self):
        self.load([(t / 2.0, t / 2.0 + 0.1, 40) for t in range(10)])

        self.engine.set_hdd_rate(1.0)
        self.engine.set_hdd_rate(None)

        self.assertEqual(len(self.hits()), 10)

    def test_gestosc_poza_zakresem_daje_blad(self):
        self.load([(0.0, 0.1, 40)])

        for bad in (0.0, -1.0, 100.0):
            with self.assertRaises(EngineError):
                self.engine.set_hdd_rate(bad)


class TestHomeRatujePolaczenie(EngineTestCase):
    """Udany HOME po bledzie musi przywrocic flage connected.

    Bez tego UI pokazywalo "Arduino disconnected" i przycisk Home
    nie ratowal sytuacji, mimo ze stacja wlasnie sie zahomowala.
    """

    def test_home_przywraca_connected(self):
        self.transport.queue_line("HOMING")
        self.transport.queue_line("READY")

        # symulujemy wczesniejsza awarie lacza
        with self.engine._lock:
            self.engine._hardware.connected = False

        self.assertTrue(self.engine.home())

        snapshot = self.engine.snapshot()
        self.assertTrue(snapshot["hardware"]["connected"])
        self.assertIsNone(snapshot["hardware"]["error"])

    def test_udany_home_czysci_blad(self):
        self.transport.queue_line("HOMING")
        self.transport.queue_line("READY")

        with self.engine._lock:
            self.engine._hardware.error = "Arduino: ERR HOME_FAILED"
            self.engine._hardware.connected = False

        self.engine.home()

        hardware = self.engine.snapshot()["hardware"]
        self.assertIsNone(hardware["error"])
        self.assertTrue(hardware["connected"])


# ============================================================
# ARANZACJA: JEDEN DOKUMENT, DWA WYJSCIA
# ============================================================


class TestArrangementOutput(EngineTestCase):
    """Import aranzacji nie moze zalezec od zakladki ani wymuszac wirtualizacji."""

    def document(self, devices, rules):
        from playback.arrangement import midi_identity

        return {"schemaVersion": 1, "midi": midi_identity(self.engine.source), "name": "Test",
                "devices": devices, "rules": rules}

    def device(self, ident, kind, mode="virtual", **fields):
        return {"id": ident, "type": kind, "mode": mode, **fields}

    def route(self, ident, track, target):
        return {"id": ident, "source": {"track": track}, "destination": {"deviceId": target},
                "transform": {}}

    def test_all_virtual_document_never_touches_the_serial_port(self):
        self.load([(0, .4, 60), (.5, .9, 64)])
        self.engine.set_arrangement(self.document(
            [self.device("fdd", "FDD"), self.device("hdd", "HDD_VCM")],
            [self.route("a", 0, "fdd"), self.route("b", 0, "hdd")]))

        snapshot = self.engine.snapshot()
        self.assertTrue(snapshot["virtual"]["enabled"])
        self.assertFalse(snapshot["arrangementHardware"]["active"])
        self.assertEqual(snapshot["arrangementHardware"]["lanes"], {})

        before = len(self.transport.events)
        self.engine.play()
        self.assertTrue(self.wait_for_state(PlaybackState.STOPPED))

        self.assertEqual(self.transport.since(before), [])

    def test_real_device_import_keeps_the_users_output_choice(self):
        self.load([(0, .4, 60), (.5, .9, 64)])
        # Uzytkownik ma wylaczony podglad: sam sprzet.
        with self.engine._lock:
            self.engine._virtual_mode = False

        self.engine.set_arrangement(self.document(
            [self.device("fdd", "FDD", "real")], [self.route("a", 0, "fdd")]))

        snapshot = self.engine.snapshot()
        self.assertFalse(snapshot["virtual"]["enabled"],
                         "dokument sprzetowy nie moze wymusic wirtualizacji")
        self.assertTrue(snapshot["arrangementHardware"]["active"])
        self.assertEqual(list(snapshot["arrangementHardware"]["lanes"]), ["fdd"])

    def test_mixed_document_keeps_the_preview_audible(self):
        self.load([(0, .4, 60), (.5, .9, 64)])
        self.engine.set_arrangement(self.document(
            [self.device("fdd", "FDD", "real"), self.device("other", "FDD", "virtual")],
            [self.route("a", 0, "fdd"), self.route("b", 0, "other")]))

        snapshot = self.engine.snapshot()
        self.assertTrue(snapshot["virtual"]["enabled"],
                        "instancje wirtualne musza byc slyszalne mimo sprzetowych w dokumencie")
        self.assertEqual(snapshot["arrangementHardware"]["lanes"]["fdd"]["deviceId"], "fdd")

    def test_taken_lane_is_reported_instead_of_silently_ignored(self):
        self.load([(0, .4, 60)])
        self.engine.set_arrangement(self.document(
            [self.device("fdd-1", "FDD", "real"), self.device("fdd-2", "FDD", "real")],
            [self.route("a", 0, "fdd-1"), self.route("b", 0, "fdd-2")]))

        hardware = self.engine.snapshot()["arrangementHardware"]
        self.assertEqual(hardware["lanes"]["fdd"]["deviceId"], "fdd-1")
        self.assertEqual([item["deviceId"] for item in hardware["unmapped"]], ["fdd-2"])
        self.assertEqual(hardware["unmapped"][0]["reason"], "LANE_TAKEN")

    def test_real_devices_drive_the_serial_port(self):
        self.load([(0, .2, 60), (.4, .6, 62), (.8, 1.0, 64)])
        self.engine.set_arrangement(self.document(
            [self.device("fdd", "FDD", "real")], [self.route("a", 0, "fdd")]))

        with self.engine._lock:
            self.engine._position_base = 0.0
            self.engine._state = PlaybackState.STOPPED

        before = len(self.transport.events)
        self.engine.play()
        self.assertTrue(self.wait_for_state(PlaybackState.STOPPED))

        # Byl reset linii (STOP/DRUM/HDD), a potem nuty z aranzacji.
        played = [text for _, text in self.transport.since(before) if text.startswith("PLAY")]
        self.assertEqual(len(played), 3)


# ============================================================
# HOMING: KLIK "PLAY" NIE MOZE PRZEPASC
# ============================================================


class SlowHomingTransport(FakeTransport):
    """Arduino, ktory potrzebuje chwili na dojazd do track 0."""

    def __init__(self, homing: float = 0.4, ready: bool = True):
        super().__init__()
        self.port = "/dev/fake-homing"
        self.label = "Fake homing"
        self.homing = homing
        self.ready = ready
        self.homed = 0

    def wait_ready(self, timeout: float = 10.0, echo=print, **_kwargs) -> bool:
        echo("HOMING")
        time.sleep(self.homing)
        self.homed += 1

        if not self.ready:
            return False

        echo("READY")

        return True


class TestHomingQueue(unittest.TestCase):
    """Play w trakcie homingu musi trafic do kolejki, a nie zniknac."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.path = write_midi(self.tmp / "Song.mid", [(0, .3, 60), (.4, .7, 62)])

    def tearDown(self):
        self._tmp.cleanup()

    def engine(self, homing=0.4, ready=True):
        transport = SlowHomingTransport(homing=homing, ready=ready)
        engine = PlaybackEngine(connect_fn=lambda port: transport, wait_ready=True)
        engine.start()
        engine.load_file(self.path)

        return engine, transport

    def wait_until(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if predicate():
                return True

            time.sleep(0.01)

        return predicate()

    def test_snapshot_reports_connecting_during_homing(self):
        engine, _ = self.engine(homing=0.5)
        thread = threading.Thread(target=engine.connect, daemon=True)

        try:
            thread.start()
            self.assertTrue(self.wait_until(lambda: engine.snapshot()["hardware"]["connecting"]))
            self.assertFalse(engine.snapshot()["hardware"]["connected"])
        finally:
            thread.join()
            engine.shutdown()

    def test_play_during_homing_is_queued_and_starts_on_ready(self):
        engine, _ = self.engine(homing=0.5)
        thread = threading.Thread(target=engine.connect, daemon=True)

        try:
            thread.start()
            self.assertTrue(self.wait_until(lambda: engine.snapshot()["hardware"]["connecting"]))

            # Klik w trakcie dojazdu: bez bledu, ale jeszcze nie gra.
            engine.play()
            self.assertEqual(engine.state, PlaybackState.STOPPED)
            self.assertTrue(engine.snapshot()["hardware"]["pendingPlay"])

            thread.join()
            self.assertTrue(self.wait_until(lambda: engine.state is PlaybackState.PLAYING))
            self.assertFalse(engine.snapshot()["hardware"]["pendingPlay"])
        finally:
            thread.join()
            engine.shutdown()

    def test_stop_cancels_play_queued_during_homing(self):
        engine, _ = self.engine(homing=0.5)
        thread = threading.Thread(target=engine.connect, daemon=True)
        try:
            thread.start()
            self.assertTrue(self.wait_until(lambda: engine.snapshot()["hardware"]["connecting"]))
            engine.play()
            self.assertTrue(engine.snapshot()["hardware"]["pendingPlay"])
            engine.stop()
            self.assertFalse(engine.snapshot()["hardware"]["pendingPlay"])
            thread.join()
            self.assertEqual(engine.state, PlaybackState.STOPPED)
        finally:
            thread.join()
            engine.shutdown()

    def test_failed_homing_does_not_pretend_to_play(self):
        engine, _ = self.engine(homing=0.2, ready=False)
        thread = threading.Thread(target=engine.connect, daemon=True)

        try:
            thread.start()
            self.assertTrue(self.wait_until(lambda: engine.snapshot()["hardware"]["connecting"]))
            engine.play()
            self.assertTrue(engine.snapshot()["hardware"]["pendingPlay"])
            thread.join()
        finally:
            thread.join()

        try:
            self.assertFalse(self.wait_until(lambda: engine.state is PlaybackState.PLAYING, timeout=0.5))
            self.assertFalse(engine.snapshot()["hardware"]["pendingPlay"])
            self.assertIsNotNone(engine.snapshot()["hardware"]["error"])
        finally:
            engine.shutdown()

    def test_play_without_any_connection_still_reports_the_error(self):
        engine = PlaybackEngine(connect_fn=lambda port: FakeTransport(), wait_ready=False)
        engine.start()

        try:
            engine.load_file(self.path)
            engine.play()  # brak transportu i brak homingu
            self.assertEqual(engine.state, PlaybackState.STOPPED)
            self.assertIn("brak polaczenia", engine.snapshot()["hardware"]["error"])
        finally:
            engine.shutdown()

    def test_play_after_ready_is_immediate(self):
        engine, transport = self.engine(homing=0.05)

        try:
            self.assertTrue(engine.connect())
            self.assertFalse(engine.snapshot()["hardware"]["connecting"])
            engine.play()
            self.assertEqual(engine.state, PlaybackState.PLAYING)
            self.assertFalse(engine.snapshot()["hardware"]["pendingPlay"])
            self.assertTrue(self.wait_until(lambda: any(t.startswith("PLAY") for t in transport.texts())))
        finally:
            engine.shutdown()
