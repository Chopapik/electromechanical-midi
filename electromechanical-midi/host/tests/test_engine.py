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

from midi_source import MidiSource  # noqa: E402
from playback.engine import (  # noqa: E402
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
        self.assertEqual([text for _, text in nowe], ["STOP"])

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

        # Jedyne komendy to STOP (z seeka) i PLAY nuty, ktora jeszcze nie trwa.
        self.assertEqual(nowe, ["STOP"])

    def test_stary_scheduler_nie_wysyla_po_stop(self):
        self.load([(0.0, 1.0, 60), (1.0, 2.0, 62), (2.0, 3.0, 64)])

        self.engine.play()
        time.sleep(0.1)

        before = len(self.transport.events)
        self.engine.stop()
        time.sleep(0.4)

        nowe = [text for _, text in self.transport.since(before)]

        self.assertEqual(nowe, ["STOP"])


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
        self.assertEqual(nowe, ["STOP", "PLAY 261.63"])
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
        self.assertEqual(nowe, ["STOP", "PLAY 261.63"])

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
        self.assertEqual(nowe, ["STOP", "PLAY 130.81"])


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
