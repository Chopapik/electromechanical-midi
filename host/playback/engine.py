"""Silnik odtwarzania - jedno zrodlo prawdy dla CLI i web playera.

Architektura:

    watek wywołujacy (CLI / FastAPI)     watek roboczy (scheduler)
    ---------------------------------    ------------------------------
    play/pause/stop/seek/set_track  -->  planowanie i wysylka PLAY/STOP
    snapshot() (tylko odczyt)            keepalive PING + nasluch ERR

Zasady, ktore chronia przed wyscigami:

1. **Jeden zamek** (``_lock``) obejmuje zarowno zmiane stanu, jak i
   wysylke komend do Serial. Dzieki temu seek/stop nie moga wcisnac sie
   miedzy "zaplanuj" i "wyslij" - stary plan nie ma jak wyslac spoznionego
   PLAY po seeku.
2. **Watek roboczy jest jedynym, ktory planuje** - metody sterujace tylko
   zmieniaja stan i budza watek (``_wake``). Dzieki temu nie ma dwoch
   rownoleglych schedulerow.
3. Pozycja liczona jest z **monotonicznego, absolutnego origin**:
   ``origin = monotonic() - pozycja``. Seek przestawia origin, a nie
   "przesuwa" kolejnych sleepow, wiec dryf sie nie kumuluje.
4. Nieudana wysylka nigdy nie udaje, ze utwor gra dalej: stan przechodzi
   w PAUSED, a ``hardware.error`` opisuje przyczyne.
"""

from __future__ import annotations

import dataclasses
import enum
import threading
import time
from pathlib import Path
from typing import Callable, Protocol

from midi_source import MidiSource, MidiSourceError, drum_name
from pitch import (
    COMFORT_MAX_HZ,
    COMFORT_MIN_HZ,
    FOLD_MODES,
    hz_to_midi,
    note_name,
)

from .timeline import (
    DEFAULT_GATE,
    DRUM_DRIVE_DEFAULT,
    DRUM_MAX_HZ_DEFAULT,
    DRUM_MIN_HZ_DEFAULT,
    LANE_DRUM,
    LANE_HDD,
    Command,
    Timeline,
    make_timeline,
)

# Ostatnie 1.5 ms czekania to aktywne krecenie - dzieki temu komendy
# wychodza wtedy, kiedy maja, a nie "mniej wiecej".
SPIN_MARGIN_S = 0.0015

# Co ile sekund wysylamy PING, gdy do nastepnej komendy jest daleko.
# Arduino ma watchdog (bez komend przez ~3 s zatrzymuje kroki), wiec
# dlugie nuty i przerwy musza byc podtrzymywane.
KEEPALIVE_S = 1.0

# Bledy Arduino, po ktorych dalsze granie nie ma sensu (stan mechaniki
# wymaga homingu) - utwor zostaje wstrzymany, a nie "gra w ciszy".
FATAL_ERRORS = (
    "ERR NOT_HOMED",
    "ERR POS_LOST",
    "ERR HOME_FAILED",
    "ERR HOST_TIMEOUT",
)

WORKER_IDLE_SLEEP_S = 0.2

# Jak czesto watek roboczy zaglada do Serial, gdy nic nie gra (musi odbierac
# STATUS/ERR takze przy recznym sterowaniu bebna).
WORKER_IDLE_POLL_S = 0.1

# --- VHS drum (manualne sterowanie, niezalezne od MIDI) ---
#
# DRUM  <0-255>  = amplituda (wypelnienie), 0 = stop
# DRUMF <hz>     = czestotliwosc kluczowania = WYSOKOSC dzwieku,
#                  0 = tryb DC (zwykly PWM 973 Hz), 20..2000 Hz
#
# Empirycznie (na tym egzemplarzu): silnik rusza od ~24, wypelnienie zmienia
# glosnosc, a DRUMF zmienia wysokosc. Dlatego start z 64 jest bezpieczny
# i od razu slyszalny.
DRUM_START_VALUE = 64
DRUM_MIN_HZ = 20
DRUM_MAX_HZ = 2000

# STATUS wysylamy najwyzej tyle razy na sekunde (suwak i tak jest dlawiony).
STATUS_MIN_INTERVAL_S = 0.05


class PlaybackState(str, enum.Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class TransportError(RuntimeError):
    """Nie udalo sie wyslac komendy do kontrolera."""


class EngineError(RuntimeError):
    """Operacja niemozliwa do wykonania (np. brak utworu)."""


class Transport(Protocol):
    """Minimum, ktore musi umiec lacze do Arduino."""

    def send(self, command: str) -> None: ...
    def play(self, hz: float) -> None: ...
    def stop(self) -> None: ...
    def ping(self) -> None: ...
    def poll_lines(self) -> list[str]: ...
    def close(self) -> None: ...


BLIND_HOME_WARNING = (
    "homing NA ŚLEPO: czujnik TRACK0 stacji nie odpowiada "
    "(sprawdź taśmę / czujnik) — pozycja liczona z dojazdu do oporu"
)


@dataclasses.dataclass
class HardwareStatus:
    connected: bool = False
    port: str | None = None
    label: str | None = None
    error: str | None = None
    warning: str | None = None
    log: list[str] = dataclasses.field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "connected": self.connected,
            "port": self.port,
            "label": self.label,
            "error": self.error,
            "warning": self.warning,
            "log": self.log[-3:],
        }


def default_connect(port: str | None = None):
    """Domyslne lacze: wykryj Arduino i otworz port (bez pytania w terminalu)."""
    from floppy_link import FloppyLink, resolve_port

    candidate = resolve_port(port, interactive=False)
    link = FloppyLink(candidate.device)
    link.label = candidate.label  # do wyswietlenia w UI

    return link


class PlaybackEngine:
    """Odtwarzacz z jednym, autorytatywnym stanem.

    ``connect_fn(port) -> transport`` mozna podmienic (testy, --dry-run).
    """

    def __init__(
        self,
        *,
        connect_fn: Callable[[str | None], Transport] | None = None,
        min_hz: float = COMFORT_MIN_HZ,
        max_hz: float = COMFORT_MAX_HZ,
        transpose: str = "auto",
        strategy: str = "highest",
        gate: float = DEFAULT_GATE,
        drum_track_index: int | None = None,
        # Domyslnie "low": to okno dokladnie jednej oktawy (110-220 Hz), wiec
        # melodia NIGDY nie przeskakuje o oktave - zachowane sa interwaly.
        drum_transpose: str = "low",
        drum_strategy: str | None = None,
        drum_min_hz: float = DRUM_MIN_HZ_DEFAULT,
        drum_max_hz: float = DRUM_MAX_HZ_DEFAULT,
        drum_drive: int = DRUM_DRIVE_DEFAULT,
        hdd_track_index: int | None = None,
        hdd_note: int | None = None,
        hdd_rate: float | None = None,
        keepalive: float = KEEPALIVE_S,
        spin_margin: float = SPIN_MARGIN_S,
        ready_timeout: float = 12.0,
        on_command: Callable[[Command], None] | None = None,
        on_handshake: Callable[[str], None] | None = None,
        wait_ready: bool = True,
        realtime: bool = True,
    ):
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._shutdown = False
        self._thread: threading.Thread | None = None

        self._connect_fn = connect_fn or default_connect
        self._min_hz = min_hz
        self._max_hz = max_hz
        self._transpose = transpose
        self._strategy = strategy
        self._gate = gate
        self._keepalive = keepalive
        self._spin_margin = spin_margin
        self._ready_timeout = ready_timeout
        self._on_command = on_command
        self._on_handshake = on_handshake
        # Trwa blokujacy handshake (connect/home) - wtedy linie z Seriala
        # naleza WYLACZNIE do wait_ready(). Bez tego watek roboczy podkradal
        # ERR/READY, oznaczal sprzet jako awaryjny ("Arduino disconnected")
        # i retry homingu nigdy nie dochodzil do skutku.
        self._handshake = False
        self._wait_ready = wait_ready
        # realtime=False: wysylaj wszystko od razu (tylko --dry-run / testy)
        self._realtime = realtime

        self._source: MidiSource | None = None
        self._file_name: str | None = None
        self._track_index: int | None = None
        self._timeline: Timeline | None = None

        # --- druga linia: VHS drum sterowany z MIDI ---
        self._drum_track_index = drum_track_index
        self._drum_transpose = drum_transpose
        self._drum_strategy = drum_strategy
        self._drum_min_hz = drum_min_hz
        self._drum_max_hz = drum_max_hz
        self._drum_drive = drum_drive
        self._drum_current: Command | None = None

        # --- trzecia linia: HDD perkusja (one-shot, bez wysokosci dzwieku) ---
        # _hdd_note = filtr nuty: None = wszystkie, albo numer nuty
        # perkusyjnej (np. 40 = werbel). Caly zestaw na jeden instrument
        # brzmi jak terkot, bo hi-hat sam ma ~3,5 uderzenia/s.
        self._hdd_track_index = hdd_track_index
        self._hdd_note = hdd_note
        # Maks. uderzen na sekunde (None = tylko limit mechaniki ~9/s).
        self._hdd_rate = hdd_rate
        self._hdd_notes: list[dict] = []   # dostepne nuty w tracku (do UI)
        self._hdd_current: Command | None = None
        self._hdd_busy = False          # potwierdzone przez firmware (STATUS hdd=)
        self._hdd_count = 0             # ile uderzen poszlo (do podgladu)

        self._state = PlaybackState.STOPPED
        self._origin = time.monotonic()
        self._position_base = 0.0
        self._next_index = 0
        self._current: Command | None = None

        self._transport: Transport | None = None
        self._hardware = HardwareStatus()
        self._last_io = 0.0

        # --- VHS drum ---
        self._drum_value = 0                 # co zadal host (0-255)
        self._drum_output: int | None = None  # co potwierdzil firmware (STATUS)
        self._drum_tone_hz = 0.0             # 0 = tryb DC
        self._drum_last_nonzero = DRUM_START_VALUE
        self._status_request_at = 0.0

        # Co juz poszlo do firmware (zeby nie wysylac tego samego i nie
        # restartowac niepotrzebnie timera tonu). -1 = nie wiemy.
        self._drum_drive_sent = -1
        self._drum_tone_sent = -1

    # ==========================================================
    # CYKL ZYCIA
    # ==========================================================

    def start(self) -> None:
        """Uruchamia watek roboczy (scheduler)."""
        with self._lock:
            if self._thread is not None:
                return

            self._shutdown = False
            self._thread = threading.Thread(
                target=self._run,
                name="playback-engine",
                daemon=True,
            )
            self._thread.start()

    def shutdown(self, timeout: float = 2.0) -> None:
        """Zatrzymuje granie i konczy watek roboczy."""
        with self._lock:
            self._shutdown = True
            self._safe_send_stop_locked()
            self._apply_drum_locked(drive=0, force=True)
            self._send_raw_locked("HDD 0")
            self._drum_value = 0
            self._drum_current = None
            self._hdd_current = None
            self._state = PlaybackState.STOPPED
            self._position_base = 0.0
            self._current = None
            self._wake.set()

        thread = self._thread

        if thread is not None:
            thread.join(timeout=timeout)

        with self._lock:
            self._thread = None
            self._close_transport_locked()

    # ==========================================================
    # HARDWARE
    # ==========================================================

    def connect(self, port: str | None = None) -> bool:
        """Otwiera port i czeka na READY. BLOKUJE - wolac z watku/w to_thread."""
        self.disconnect()

        try:
            transport = self._connect_fn(port)
        except Exception as exc:  # SerialLinkError i wszystko inne
            with self._lock:
                self._hardware = HardwareStatus(
                    connected=False,
                    port=port,
                    error=str(exc),
                )

            return False

        log: list[str] = []
        ready = True
        error: str | None = None
        blind = False

        def echo(line: str) -> None:
            nonlocal blind
            log.append(line)

            if "NA SLEPO" in line:
                blind = True

            if self._on_handshake is not None:
                try:
                    self._on_handshake(line)
                except Exception:
                    pass

        if self._wait_ready and hasattr(transport, "wait_ready"):
            with self._lock:
                self._handshake = True

            try:
                ready = bool(
                    transport.wait_ready(
                        timeout=self._ready_timeout,
                        echo=echo,
                    )
                )
            except Exception as exc:
                ready = False
                error = str(exc)
            finally:
                with self._lock:
                    self._handshake = False

            if not ready and error is None:
                error = "brak READY po homingu (stacja nie odpowiedziala)"

        device = getattr(transport, "port", port)
        label = getattr(transport, "label", None)

        with self._lock:
            self._transport = transport
            self._hardware = HardwareStatus(
                connected=True,
                port=str(device) if device else port,
                label=label,
                error=error,
                warning=BLIND_HOME_WARNING if blind else None,
                log=log,
            )
            self._last_io = time.monotonic()
            self._drum_output = None
            self._drum_current = None

            # FAIL-SAFE: po (re)connect beben ma byc ZATRZYMOWANY i nie ma
            # prawa ruszyc sam. Najpierw stop, potem odtworzenie ustawien.
            self._drum_value = 0
            self._drum_drive_sent = -1
            self._drum_tone_sent = -1

            self._send_raw_locked("DRUM 0")
            self._drum_drive_sent = 0
            self._apply_drum_locked(tone_hz=self._drum_tone_hz, force=True)
            self._request_status_locked(force=True)

        return ready

    def home(self) -> bool:
        """Ponowny homing BEZ zrywania polaczenia. BLOKUJE - wolac z watku.

        Locka trzymamy tylko na czas zatrzymania i sprzatania; sam homing
        (moze potrwac kilka sekund) leci bez niego, zeby API i WebSocket
        dalej odpowiadaly.
        """
        with self._lock:
            transport = self._transport

            if transport is None:
                raise EngineError("brak polaczenia z Arduino")

            self._safe_send_stop_locked()
            self._apply_drum_locked(drive=0, force=True)
            self._send_raw_locked("HDD 0")
            self._state = PlaybackState.STOPPED
            self._position_base = 0.0
            self._next_index = 0
            self._current = None
            self._drum_current = None
            self._hdd_current = None

        log: list[str] = []
        blind = False

        def note(line: str) -> None:
            nonlocal blind
            log.append(line)

            if "NA SLEPO" in line:
                blind = True

        try:
            transport.send("HOME")
        except Exception as exc:
            with self._lock:
                self._fail_locked(f"nie udalo sie wyslac HOME: {exc}")

            return False

        wait = getattr(transport, "wait_ready", None)
        ok = True
        error: str | None = None

        if wait is not None:
            with self._lock:
                self._handshake = True

            try:
                ok = bool(wait(timeout=self._ready_timeout, echo=note))
            except Exception as exc:
                ok, error = False, str(exc)
            finally:
                with self._lock:
                    self._handshake = False

            if not ok and error is None:
                error = "brak READY po homingu (stacja nie odpowiedziala)"

        with self._lock:
            self._hardware.error = error
            self._hardware.log = log

            # Udany homing = sprzet znow gotowy. Bez tego flaga connected
            # zostawala False po wczesniejszym bledzie i przycisk "Home"
            # nie ratowal sytuacji (UI dalej pokazywal rozlaczenie).
            if ok:
                self._hardware.connected = self._transport is not None

            if ok and blind:
                self._hardware.warning = BLIND_HOME_WARNING

        return ok

    def disconnect(self) -> None:
        with self._lock:
            was_playing = self._state is PlaybackState.PLAYING

            if was_playing:
                self._position_base = self._position_locked()
                self._state = PlaybackState.PAUSED
                self._current = None

            # FAIL-SAFE: nie zostawiamy krecacego sie bebna ani trwajacej
            # sekwencji uderzen HDD za soba.
            if self._transport is not None:
                self._safe_send_stop_locked()
                self._apply_drum_locked(drive=0, force=True)
                self._send_raw_locked("HDD 0")

            self._drum_value = 0
            self._drum_output = None
            self._drum_current = None
            self._hdd_current = None
            self._close_transport_locked()
            self._wake.set()

    def _close_transport_locked(self) -> None:
        transport = self._transport
        self._transport = None

        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

        self._hardware.connected = False

    # ==========================================================
    # WCZYTANIE UTWORU
    # ==========================================================

    def load_file(self, path: str | Path, track_index: int | None = None) -> None:
        """Wczytuje plik MIDI. Zmiana pliku = STOP i powrot na pozycje 0."""
        source = MidiSource(path)  # moze rzucic MidiSourceError

        if track_index is None:
            playable = [track.index for track in source.tracks if track.note_count]

            if not playable:
                raise EngineError("plik nie ma zadnego tracku z nutami")

            track_index = playable[0]

        if not 0 <= track_index < len(source.tracks):
            raise EngineError(f"track {track_index} nie istnieje")

        with self._lock:
            self._safe_send_stop_locked()

            self._source = source
            self._file_name = Path(path).name
            self._track_index = track_index
            self._state = PlaybackState.STOPPED
            self._position_base = 0.0
            self._current = None
            self._rebuild_locked(keep_position=False)
            self._wake.set()

    def set_track(self, track_index: int) -> None:
        """Zmiana tracku zachowuje pozycje i stan (gra dalej od tego samego miejsca)."""
        with self._lock:
            if self._source is None:
                raise EngineError("najpierw wybierz plik MIDI")

            if not 0 <= track_index < len(self._source.tracks):
                raise EngineError(f"track {track_index} nie istnieje")

            if track_index == self._track_index:
                return

            self._track_index = track_index
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    def set_transpose(self, mode: str) -> None:
        if mode not in FOLD_MODES:
            raise EngineError(f"nieznany tryb transpozycji {mode!r}")

        with self._lock:
            if mode == self._transpose:
                return

            self._transpose = mode
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    def set_strategy(self, strategy: str) -> None:
        from midi_source import STRATEGIES

        if strategy not in STRATEGIES:
            raise EngineError(f"nieznana strategia {strategy!r}")

        with self._lock:
            if strategy == self._strategy:
                return

            self._strategy = strategy
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    # ---------- druga linia: VHS drum z MIDI ----------

    def set_drum_track(self, track_index: int | None) -> None:
        """Przypisuje track MIDI do bebna (None = beben tylko reczny)."""
        with self._lock:
            if track_index is not None:
                if self._source is None:
                    raise EngineError("najpierw wybierz plik MIDI")

                if not 0 <= track_index < len(self._source.tracks):
                    raise EngineError(f"track {track_index} nie istnieje")

            if track_index == self._drum_track_index:
                return

            self._drum_track_index = track_index
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    def set_drum_transpose(self, mode: str) -> None:
        if mode not in FOLD_MODES:
            raise EngineError(f"nieznany tryb transpozycji {mode!r}")

        with self._lock:
            if mode == self._drum_transpose:
                return

            self._drum_transpose = mode
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    def set_drum_strategy(self, strategy: str) -> None:
        from midi_source import STRATEGIES

        if strategy not in STRATEGIES:
            raise EngineError(f"nieznana strategia {strategy!r}")

        with self._lock:
            if strategy == self._drum_strategy:
                return

            self._drum_strategy = strategy
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    # ---------- trzecia linia: HDD perkusja z MIDI ----------

    def set_hdd_track(self, track_index: int | None) -> None:
        """Przypisuje track MIDI do perkusji HDD (None = HDD nie gra).

        HDD to instrument uderzeniowy bez wysokosci dzwieku: kazda nuta
        wybranego tracku (niezaleznie od wysokosci) = jedno uderzenie.
        """
        with self._lock:
            if track_index is not None:
                if self._source is None:
                    raise EngineError("najpierw wybierz plik MIDI")

                if not 0 <= track_index < len(self._source.tracks):
                    raise EngineError(f"track {track_index} nie istnieje")

            if track_index == self._hdd_track_index:
                return

            self._hdd_track_index = track_index
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    def set_hdd_note(self, note: int | None) -> None:
        """Wybiera, ktora nuta perkusyjna ma uderzac w HDD (None = wszystkie).

        HDD to jeden instrument uderzeniowy. Caly track perkusyjny naraz
        brzmi jak terkot (hi-hat + ride + stopa + werbel zlewaja sie w jeden
        dzwiek), dlatego wybiera sie jedna-nute o charakterze rytmicznym.
        """
        with self._lock:
            note = None if note is None else int(note)

            if note is not None and not 0 <= note <= 127:
                raise EngineError(f"nuta {note} poza zakresem 0..127")

            if note == self._hdd_note:
                return

            self._hdd_note = note
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    def set_hdd_rate(self, rate: float | None) -> None:
        """Maksymalna gestosc uderzen HDD (uderzen na sekunde).

        None = tylko limit mechaniki (~9/s). Mniejsza wartosc przerzedza
        uderzenia - np. 1.0 zostawia maksymalnie jedno na sekunde.
        """
        with self._lock:
            if rate is not None:
                rate = float(rate)

                if not 0.05 <= rate <= 50.0:
                    raise EngineError(f"gestosc {rate} poza zakresem 0.05..50 /s")

            if rate == self._hdd_rate:
                return

            self._hdd_rate = rate
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    def _rebuild_locked(self, *, keep_position: bool) -> None:
        """Buduje timeline na nowo i ustawia wskaznik na wlasciwe miejsce.

        Przy zmianie tracku/transpozycji zachowujemy pozycje i stan:
        jesli gralismy, gramy dalej od tego samego miejsca, a jezeli
        w nowym miejscu trwa nuta - wznawiamy ja natychmiast.
        """
        if self._source is None or self._track_index is None:
            self._timeline = None
            return

        position = self._position_locked() if keep_position else 0.0

        self._timeline = make_timeline(
            self._source,
            self._track_index,
            strategy=self._strategy,
            min_hz=self._min_hz,
            max_hz=self._max_hz,
            mode=self._transpose,
            gate=self._gate,
            drum_track_index=self._drum_track_index,
            drum_strategy=self._drum_strategy,
            drum_min_hz=self._drum_min_hz,
            drum_max_hz=self._drum_max_hz,
            drum_mode=self._drum_transpose,
            drum_drive=self._drum_drive,
            hdd_track_index=self._hdd_track_index,
            hdd_note=self._hdd_note,
            hdd_rate=self._hdd_rate,
        )

        self._hdd_notes = self._hdd_note_options_locked()

        position = max(0.0, min(position, self._timeline.duration))

        if self._state is PlaybackState.PLAYING:
            self._begin_locked(position)
            return

        self._position_base = position
        self._next_index = self._timeline.index_after(position)
        self._current = None

    # ==========================================================
    # STEROWANIE
    # ==========================================================

    def play(self) -> None:
        """Start od biezacej pozycji (0 po STOP, albo tam, gdzie wskazal seek)."""
        with self._lock:
            if self._timeline is None or not self._timeline.commands:
                raise EngineError("nie ma czego grac - wybierz plik i track")

            if self._state is PlaybackState.PLAYING:
                return

            position = self._position_locked()

            if position >= self._timeline.duration:
                position = 0.0

            self._begin_locked(position)

    def pause(self) -> None:
        with self._lock:
            if self._state is not PlaybackState.PLAYING:
                return

            position = self._position_locked()
            self._reset_instruments_locked()
            self._position_base = position
            self._state = PlaybackState.PAUSED
            self._current = None
            self._drum_current = None
            self._wake.set()

    def resume(self) -> None:
        with self._lock:
            if self._state is PlaybackState.PLAYING:
                return

            if self._timeline is None or not self._timeline.commands:
                raise EngineError("nie ma czego grac - wybierz plik i track")

            self._begin_locked(self._position_locked())

    def stop(self) -> None:
        """STOP + DRUM 0, playhead = 0, stan STOPPED."""
        with self._lock:
            self._reset_instruments_locked()
            self._state = PlaybackState.STOPPED
            self._position_base = 0.0
            self._next_index = 0
            self._current = None
            self._drum_current = None
            self._wake.set()

    def seek(self, position: float) -> None:
        """Przeskok do pozycji (sekundy). Granie jest kontynuowane."""
        with self._lock:
            if self._timeline is None:
                return

            position = max(0.0, min(float(position), self._timeline.duration))

            if self._state is PlaybackState.PLAYING:
                # STOP + ewentualne natychmiastowe wznowienie nuty w tym miejscu
                self._begin_locked(position)
                return

            self._position_base = position
            self._next_index = self._timeline.index_after(position)
            self._current = None
            self._wake.set()

    def _begin_locked(self, position: float) -> None:
        """Wspolna droga play/resume/seek/zmiana tracku w trakcie grania."""
        timeline = self._timeline

        if timeline is None:
            return

        if self._transport is None:
            self._fail_locked("brak polaczenia z Arduino")
            return

        # Zawsze STOP + DRUM 0 przed nowym planem - zaden instrument nie
        # moze zostac z dzwiekiem ze starego planu.
        if not self._reset_instruments_locked():
            return

        self._next_index = timeline.index_after(position)
        self._origin = time.monotonic() - position
        self._position_base = position
        self._state = PlaybackState.PLAYING
        self._current = None
        self._drum_current = None
        self._hdd_current = None

        # Wznowienie stanu WSZYSTKICH linii w tym miejscu.
        # HDD nie ma stanu do wznowienia: to one-shot, a seek w srodek
        # sekwencji nie powinien sztucznie uderzac.
        for command in timeline.resume_commands(position):
            if command.lane == LANE_DRUM:
                self._dispatch_drum_locked(command)
            else:
                self._send_locked(command)
                self._current = command

        # One-shot "hit" DOKLADNIE w chwili startu/seeku: index_after je
        # pominie, a wznowienie ich nie obejmuje (to nie nuty). Wysylamy je tu.
        for command in timeline.commands_at(position):
            if command.lane == LANE_HDD and command.kind == "hit":
                self._send_raw_locked("HIT")
                self._hdd_current = command
                self._hdd_count += 1

        self._next_index = timeline.index_after(position)
        self._wake.set()

    def _reset_instruments_locked(self) -> bool:
        """STOP + DRUM 0 + HDD 0 (wspolny punkt startu po seek/pauza/stop)."""
        stop_ok = self._safe_send_stop_locked()
        drum_ok = self._apply_drum_locked(drive=0, force=True)
        hdd_ok = self._send_raw_locked("HDD 0")

        self._drum_current = None
        self._hdd_current = None

        return stop_ok and drum_ok and hdd_ok

    # ==========================================================
    # VHS DRUM (manualne sterowanie - NIE jest zwiazane z MIDI)
    #
    # DRUM  = amplituda (0-255), 0 = stop
    # DRUMF = czestotliwosc kluczowania = wysokosc dzwieku (0 = tryb DC)
    # ==========================================================

    def _drum_midi_active_locked(self) -> bool:
        """Czy beben jest wlasnie sterowany przez MIDI (a nie recznie)."""
        return self._state is PlaybackState.PLAYING and self._drum_track_index is not None

    def _guard_manual_drum_locked(self) -> None:
        if self._drum_midi_active_locked():
            raise EngineError(
                "beben jest sterowany przez MIDI - zatrzymaj albo wstrzymaj odtwarzanie"
            )

    def set_drum(self, value: int) -> int:
        """Ustawia amplitude bebna (0-255). 0 = stop. Tylko tryb reczny."""
        value = int(value)

        if not 0 <= value <= 255:
            raise EngineError(f"PWM bebna musi byc w zakresie 0..255, jest {value}")

        with self._lock:
            self._guard_manual_drum_locked()

            if self._transport is None:
                raise EngineError("brak polaczenia z Arduino")

            if not self._apply_drum_locked(drive=value, force=True):
                raise EngineError("nie udalo sie wyslac komendy do Arduino")

            self._request_status_locked()

        return value

    def start_drum(self) -> int:
        """Start z ostatnia niezerowa wartoscia (albo konserwatywnym startem)."""
        with self._lock:
            self._guard_manual_drum_locked()
            value = self._drum_last_nonzero or DRUM_START_VALUE

        return self.set_drum(value)

    def stop_drum(self) -> int:
        return self.set_drum(0)

    def set_drum_tone(self, hz: float) -> float:
        """Wysokosc dzwieku bebna (0 = tryb DC, 20..2000 Hz). Tylko recznie."""
        hz = float(hz)

        if hz != 0 and not DRUM_MIN_HZ <= hz <= DRUM_MAX_HZ:
            raise EngineError(
                f"czestotliwosc bebna: 0 albo {DRUM_MIN_HZ}..{DRUM_MAX_HZ} Hz, jest {hz}"
            )

        with self._lock:
            self._guard_manual_drum_locked()

            if self._transport is None:
                raise EngineError("brak polaczenia z Arduino")

            if not self._apply_drum_locked(tone_hz=hz, force=True):
                raise EngineError("nie udalo sie wyslac komendy do Arduino")

            self._request_status_locked()

        return hz

    # ---------- wewnetrzne ----------

    def _apply_drum_locked(
        self,
        *,
        tone_hz: float | None = None,
        drive: int | None = None,
        force: bool = False,
    ) -> bool:
        """Wysyla do firmware tylko to, co faktycznie sie zmienilo.

        Dzieki temu legato (kolejna nuta bez przerwy) wysyla sam DRUMF i nie
        restartuje timera tonu, a powtorzona ta sama wartosc nie leci wcale.
        """
        if tone_hz is not None:
            target = int(round(tone_hz))

            if target < DRUM_MIN_HZ:
                target = 0

            if force or target != self._drum_tone_sent:
                if not self._send_raw_locked(f"DRUMF {target}"):
                    return False

                self._drum_tone_sent = target
                self._drum_tone_hz = float(target) if target else 0.0

        if drive is not None and (force or drive != self._drum_drive_sent):
            if not self._send_raw_locked(f"DRUM {drive}"):
                return False

            self._drum_drive_sent = drive
            self._drum_value = drive

            if drive > 0:
                self._drum_last_nonzero = drive

        return True

    def _dispatch_drum_locked(self, command: Command) -> bool:
        """Wykonuje komende linii bebna z timeline'u."""
        if command.kind == "drum_on":
            if not self._apply_drum_locked(tone_hz=command.hz, drive=self._drum_drive):
                return False

            self._drum_current = command
            return True

        if not self._apply_drum_locked(drive=0):
            return False

        self._drum_current = None
        return True

    # ==========================================================
    # ODCZYT STANU
    # ==========================================================

    def snapshot(self) -> dict:
        with self._lock:
            timeline = self._timeline
            duration = timeline.duration if timeline else 0.0
            position = self._position_locked()

            playing = self._state is PlaybackState.PLAYING
            current = self._current if playing else None

            frequency = current.hz if current is not None else None
            midi_note = None

            if frequency:
                midi_note = int(round(hz_to_midi(frequency)))

            return {
                "state": self._state.value,
                "position": round(position, 3),
                "duration": round(duration, 3),
                "file": self._file_name,
                "track": self._track_index,
                "trackName": self.track_name,
                "midiNote": midi_note,
                "noteName": note_name(midi_note) if midi_note is not None else None,
                "sourceNote": current.note if current is not None else None,
                "frequency": round(frequency, 2) if frequency else None,
                "transpose": self._transpose,
                "strategy": self._strategy,
                "range": {"minHz": self._min_hz, "maxHz": self._max_hz},
                "stats": timeline.stats.as_dict() if timeline else None,
                "hardware": self._hardware.as_dict(),
                "drum": self._drum_snapshot_locked(),
                "hdd": self._hdd_snapshot_locked(),
            }

    def _drum_snapshot_locked(self) -> dict:
        connected = self._transport is not None
        midi_active = self._drum_midi_active_locked()
        current = self._drum_current if midi_active else None

        tone = float(self._drum_tone_hz)
        played_note = int(round(hz_to_midi(tone))) if tone > 0 else None

        return {
            "value": self._drum_value,
            "output": self._drum_output if connected else None,
            "toneHz": round(tone, 2),
            "lastValue": self._drum_last_nonzero,
            "running": bool(self._drum_value > 0 and connected),
            "connected": connected,
            "minHz": DRUM_MIN_HZ,
            "maxHz": DRUM_MAX_HZ,
            # --- tryb pracy: reczny czy z MIDI ---
            "controlledBy": "midi" if midi_active else "manual",
            "drive": self._drum_drive,
            "range": {"minHz": self._drum_min_hz, "maxHz": self._drum_max_hz},
            "transpose": self._drum_transpose,
            "strategy": self._drum_strategy or self._strategy,
            "midiTrack": self._drum_track_index,
            "midiTrackName": self.drum_track_name,
            "midiNote": current.note if current is not None else None,
            "midiNoteName": note_name(played_note) if played_note is not None else None,
            "midiFrequency": round(current.hz, 2) if current is not None and current.hz else None,
        }

    def _hdd_note_options_locked(self) -> list[dict]:
        """Nuty dostepne w wybranym tracku HDD (do wyboru jednej w UI).

        Sortowane od najczestszej - to zwykle te, ktore niosa rytm
        (werbel, stopa), a nie te, ktore tylko szumia (hi-hat).
        """
        if self._source is None or self._hdd_track_index is None:
            return []

        counts: dict[int, int] = {}

        for span in self._source.notes(self._hdd_track_index):
            counts[span.note] = counts.get(span.note, 0) + 1

        return [
            {
                "note": note,
                "name": drum_name(note) or note_name(note),
                "count": count,
            }
            for note, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _hdd_snapshot_locked(self) -> dict:
        connected = self._transport is not None
        midi_active = (
            self._state is PlaybackState.PLAYING and self._hdd_track_index is not None
        )
        current = self._hdd_current if midi_active else None

        return {
            "connected": connected,
            "busy": self._hdd_busy if connected else False,
            "count": self._hdd_count,
            "controlledBy": "midi" if midi_active else "off",
            "midiTrack": self._hdd_track_index,
            "midiTrackName": self.hdd_track_name,
            "note": self._hdd_note,
            "rate": self._hdd_rate,
            "notes": self._hdd_notes,
            "lastNote": current.note if current is not None else None,
            "lastNoteName": (
                note_name(current.note) if current is not None and current.note is not None else None
            ),
        }

    @property
    def state(self) -> PlaybackState:
        with self._lock:
            return self._state

    @property
    def position(self) -> float:
        with self._lock:
            return self._position_locked()

    @property
    def duration(self) -> float:
        with self._lock:
            return self._timeline.duration if self._timeline else 0.0

    @property
    def track_name(self) -> str | None:
        if self._source is None or self._track_index is None:
            return None

        track = self._source.tracks[self._track_index]

        return track.name

    @property
    def drum_track_name(self) -> str | None:
        if self._source is None or self._drum_track_index is None:
            return None

        return self._source.tracks[self._drum_track_index].name

    @property
    def hdd_track_name(self) -> str | None:
        if self._source is None or self._hdd_track_index is None:
            return None

        return self._source.tracks[self._hdd_track_index].name

    @property
    def source(self) -> MidiSource | None:
        return self._source

    def _position_locked(self) -> float:
        duration = self._timeline.duration if self._timeline else 0.0

        if self._state is PlaybackState.PLAYING:
            position = time.monotonic() - self._origin
        else:
            position = self._position_base

        return max(0.0, min(position, duration))

    # ==========================================================
    # WYSYLKA
    # ==========================================================

    def _send_locked(self, command: Command) -> bool:
        """Wysyla komende. False = lacze padlo (stan -> PAUSED + blad)."""
        transport = self._transport

        if transport is None:
            self._fail_locked("brak polaczenia z Arduino")
            return False

        try:
            if command.kind == "play":
                transport.play(command.hz)
            else:
                transport.stop()
        except Exception as exc:
            self._fail_locked(f"blad Serial: {exc}")
            return False

        self._last_io = time.monotonic()

        if self._on_command is not None:
            try:
                self._on_command(command)
            except Exception:
                pass

        return True

    def _safe_send_stop_locked(self) -> bool:
        if self._transport is None:
            return False

        try:
            self._transport.stop()
        except Exception as exc:
            self._fail_locked(f"blad Serial: {exc}")
            return False

        self._last_io = time.monotonic()

        return True

    def _send_raw_locked(self, text: str) -> bool:
        """Wysyla dowolna komende tekstowa (DRUM/DRUMF/STATUS)."""
        transport = self._transport

        if transport is None:
            return False

        send = getattr(transport, "send", None)

        if send is None:
            return False

        try:
            send(text)
        except Exception as exc:
            self._fail_locked(f"blad Serial: {exc}")
            return False

        self._last_io = time.monotonic()

        return True

    def _request_status_locked(self, force: bool = False) -> bool:
        now = time.monotonic()

        if not force and now - self._status_request_at < STATUS_MIN_INTERVAL_S:
            return False

        self._status_request_at = now

        return self._send_raw_locked("STATUS")

    def _parse_status_locked(self, line: str) -> None:
        """STATUS ... drum=<n> drum_out=<n> drumf=<n> -> stan potwierdzony."""
        for token in line.split()[1:]:
            key, separator, value = token.partition("=")

            if not separator:
                continue

            if key == "drum_out":
                try:
                    self._drum_output = int(value)
                except ValueError:
                    pass
            elif key == "drumf":
                try:
                    self._drum_tone_hz = int(value)
                except ValueError:
                    pass
            elif key == "hdd":
                self._hdd_busy = value == "1"

    def _fail_locked(self, message: str) -> None:
        """Awaria lacza: nie udajemy, ze utwor gra dalej."""
        self._hardware.connected = False
        self._hardware.error = message

        if self._state is PlaybackState.PLAYING:
            self._position_base = max(0.0, time.monotonic() - self._origin)
            self._state = PlaybackState.PAUSED

        self._current = None
        self._drum_current = None
        self._hdd_current = None

        # Stan bebna jest teraz nieznany - po reconnect wszystko pojdzie od nowa.
        self._drum_value = 0
        self._drum_drive_sent = -1
        self._drum_tone_sent = -1
        self._hdd_busy = False
        self._wake.set()

    def _poll_lines_locked(self) -> None:
        transport = self._transport

        if transport is None:
            return

        try:
            lines = transport.poll_lines()
        except Exception as exc:
            self._fail_locked(f"blad odczytu Serial: {exc}")
            return

        for line in lines:
            self._hardware.log = (self._hardware.log + [line])[-5:]

            if line.startswith("STATUS"):
                self._parse_status_locked(line)
                continue

            if line.startswith(FATAL_ERRORS):
                self._fail_locked(f"Arduino: {line}")

    def _keepalive_locked(self) -> None:
        transport = self._transport

        if transport is None or self._state is not PlaybackState.PLAYING:
            return

        # Brak metody ping to blad programisty, a nie awaria sprzetu -
        # nie mozemy za to pauzowac utworu.
        ping = getattr(transport, "ping", None)

        if ping is None:
            return

        now = time.monotonic()

        if now - self._last_io < self._keepalive:
            return

        try:
            ping()
        except Exception as exc:
            self._fail_locked(f"blad Serial: {exc}")
            return

        self._last_io = now
        self._poll_lines_locked()

    # ==========================================================
    # WATEK ROBOCZY
    # ==========================================================

    def _run(self) -> None:
        while True:
            with self._lock:
                if self._shutdown:
                    return

                if (
                    self._state is not PlaybackState.PLAYING
                    or self._timeline is None
                    or self._transport is None
                ):
                    timeout: float | None = None
                else:
                    timeout = self._plan_locked()

                    if timeout is not None:
                        timeout = min(timeout, self._keepalive)

            if timeout is None:
                # Nic nie gramy - ale i tak trzeba odbierac Serial: przy
                # recznym sterowaniu bebna przychodza tu STATUS-y i bledy.
                # Podczas handshake'u NIE dotykamy bufora (patrz _handshake).
                with self._lock:
                    if not self._handshake:
                        self._poll_lines_locked()

                self._wake.wait(timeout=WORKER_IDLE_POLL_S)
                self._wake.clear()
                continue

            self._wait(timeout)
            self._wake.clear()

            with self._lock:
                self._keepalive_locked()

    def _plan_locked(self) -> float | None:
        """Wysyla wszystkie komendy, ktorych czas juz nadszedl.

        Zwraca ile sekund czekac do nastepnej komendy (None = nic nie gramy).
        """
        timeline = self._timeline

        if timeline is None:
            return None

        now = time.monotonic()
        position = now - self._origin if self._realtime else float("inf")
        commands = timeline.commands

        while self._next_index < len(commands):
            command = commands[self._next_index]

            if command.time > position + 1e-9:
                break

            if command.lane == LANE_DRUM:
                if not self._dispatch_drum_locked(command):
                    return None
            elif command.lane == LANE_HDD:
                if not self._send_raw_locked("HIT"):
                    return None

                self._hdd_current = command
                self._hdd_count += 1
            else:
                if not self._send_locked(command):
                    return None

                self._current = command if command.kind == "play" else None

            self._next_index += 1

            if self._realtime:
                position = time.monotonic() - self._origin

        if self._next_index >= len(commands) and position >= timeline.duration:
            # Koniec utworu: playhead zostaje na koncu (STOP jawnie zeruje).
            self._state = PlaybackState.STOPPED
            self._position_base = timeline.duration
            self._current = None
            return None

        if self._next_index < len(commands):
            target = self._origin + commands[self._next_index].time
        else:
            target = self._origin + timeline.duration

        return max(0.0, target - time.monotonic())

    def _wait(self, timeout: float) -> bool:
        """Czeka do timeout, ale natychmiast reaguje na _wake.

        Ostatnie SPIN_MARGIN_S krecimy sie aktywnie - to daje dokladnosc
        rzedu mikrosekund przy zachowaniu przerwalnosci.
        """
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()

            if remaining <= 0.0:
                return False

            if remaining <= self._spin_margin:
                while time.monotonic() < deadline:
                    if self._wake.is_set():
                        return True

                return False

            if self._wake.wait(timeout=remaining - self._spin_margin):
                return True
