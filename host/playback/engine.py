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
import copy
import json
import enum
import threading
import time
from pathlib import Path
from typing import Callable, Protocol

from midi_source import MidiSource, MidiSourceError, drum_name
from orchestra_link import StopConfirmationError
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
    LANES,
    LANE_DRUM,
    LANE_HDD,
    Command,
    Timeline,
    make_timeline,
)
from .virtual import PROFILES, VirtualDeviceInstance, VirtualOrchestra, WavePreview
from .arrangement import Arrangement, ArrangementError, midi_identity
from .hardware import bind_devices, build_commands, build_plan_commands
from .hardware_profiles import HardwareContext, HardwareRegistry, execution_command
from .allocator import allocate, manual_pins
from .duplicates import normalize
from .orchestra import OrchestraConfig, default_orchestra, parse_orchestra

# Ostatnie 1.5 ms czekania to aktywne krecenie - dzieki temu komendy
# wychodza wtedy, kiedy maja, a nie "mniej wiecej".
SPIN_MARGIN_S = 0.0015

# Co ile sekund wysylamy PING, gdy do nastepnej komendy jest daleko.
# Arduino ma watchdog (bez komend przez ~3 s zatrzymuje kroki), wiec
# dlugie nuty i przerwy musza byc podtrzymywane.
KEEPALIVE_S = 1.0

# Device/protocol errors pause playback; Serial remains connected.
DEVICE_ERRORS = (
    "ERR NOT_HOMED",
    "ERR POS_LOST",
    "ERR HOME_FAILED",
    "ERR TRACK0_STUCK",
    "ERR HOST_TIMEOUT",
)
FATAL_ERRORS = DEVICE_ERRORS  # Backward-compatible export; these do not disconnect Serial.

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
    homed: bool = False
    fdd_status: str = "not_homed"
    position_resyncs: int = 0
    last_position_resync: str | None = None
    port: str | None = None
    label: str | None = None
    error: str | None = None
    warning: str | None = None
    log: list[str] = dataclasses.field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "connected": self.connected,
            "homed": self.homed,
            "fddStatus": self.fdd_status,
            "positionResyncs": self.position_resyncs,
            "lastPositionResync": self.last_position_resync,
            "port": self.port,
            "label": self.label,
            "error": self.error,
            "warning": self.warning,
            "log": self.log[-3:],
        }


def default_connect(port: str | None = None):
    """Domyslne lacze: wykryj Arduino i otworz port (bez pytania w terminalu)."""
    from floppy_link import resolve_port
    from orchestra_link import OrchestraLink

    candidate = resolve_port(port, interactive=False)
    link = OrchestraLink(candidate.device)
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
        auto_arrange: bool = False,
        preview_mode: bool | None = None,
    ):
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._shutdown = False
        self._thread: threading.Thread | None = None

        self._connect_fn = connect_fn or default_connect
        self._controller_target = 'uno'
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
        self._home_lock = threading.Lock()
        self._handshake = False
        self._wait_ready = wait_ready
        # Auto Arranger jako domyslne wyjscie: MIDI -> plan -> orkiestra.
        # Domyslnie OFF, bo CLI i testy silnika uzywaja recznego trybu PLAYER.
        self._auto_arrange = auto_arrange
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
        self._late_commands = 0
        self._end_discarded_commands = 0
        self._max_dispatch_lag = 0.0
        self._scheduler_lag = 0.0
        self._late_events = 0
        self._collapsed_events = 0
        self._late_reasons = {}
        self._ble_batches = self._ble_commands = self._max_batch_commands = 0
        self._last_batch_duration = self._batch_total_duration = 0.0
        self._timing_timeline = None
        self._next_lane_command = []
        self._current: Command | None = None

        self._transport: Transport | None = None
        self._runtime_preview = preview_mode
        self._virtual_mode = bool(preview_mode)
        self._virtual = VirtualOrchestra()
        self._audio_revision = 0
        self._preview = WavePreview(clocked=True)
        self._preview_generation = 0
        self._preview_request: tuple[int, VirtualOrchestra, float] | None = None
        self._preview_worker_running = False
        self._arrangement: Arrangement | None = None      # reczny override (JSON)
        self._orchestra: OrchestraConfig = default_orchestra()
        self._plan = None                                  # PerformancePlan
        self._normalized = None                            # NormalizedSource
        self._plan_report: dict | None = None
        self._arrangement_notes: list[dict] = []
        self._arrangement_revision = 0
        # Instancje aranzacji podpięte do fizycznych linii Serial. Pusty
        # slownik = czysty podglad wirtualny, nie wolno wtedy dotykac sprzetu.
        self._hardware_bound: dict[str, VirtualDeviceInstance] = {}
        self._hardware_unmapped: list[dict] = []
        self._hardware_active = False
        self._hardware = HardwareStatus()
        # Klik "Play" w trakcie homingu nie moze przepasc: zapamietujemy
        # zamiar i startujemy od razu, gdy Arduino zglosi READY.
        self._pending_play = False
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
            self._preview_generation += 1
            self._preview_request = None
            self._preview.close()
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
        """Open Serial, finish boot handshake, then explicitly home FDD."""
        self.disconnect()
        with self._lock:
            self._handshake = True
        try:
            if self._controller_target == 'esp32':
                from ble_link import BleOrchestraLink
                transport = BleOrchestraLink()
            else:
                transport = self._connect_fn(port)
        except Exception as exc:
            with self._lock:
                self._hardware = HardwareStatus(error=str(exc), port=port)
                self._handshake = False
            return False
        with self._lock:
            self._transport = transport
            self._hardware = HardwareStatus(connected=True,
                port=getattr(transport, 'port', port), label=getattr(transport, 'label', None),
                fdd_status='homing')
        try:
            if self._wait_ready and hasattr(transport, 'wait_ready'):
                wait = getattr(transport, 'wait_boot', transport.wait_ready)
                if not wait(timeout=self._ready_timeout, echo=self._record_handshake):
                    with self._lock:
                        self._hardware.error = 'Brak READY podczas handshake Arduino. Spróbuj Retry Home.'
                        self._hardware.fdd_status = 'error'
                        self._handshake = False
                        self._pending_play = False
                    return False
            if getattr(transport, 'protocol_version', 1) == 2:
                with self._lock:
                    if self._source is not None:
                        self._rebuild_locked(keep_position=True)
            return self.home()
        except Exception as exc:
            with self._lock:
                self._handshake = False
                self._fail_locked(f'blad transportu: {exc}')
            return False

    def set_controller_target(self, target: str) -> None:
        if target not in ('uno', 'esp32'):
            raise EngineError('Nieznany kontroler')
        if target != self._controller_target:
            self.disconnect()
            with self._lock:
                self._controller_target = target
                self._hardware = HardwareStatus()

    def _record_handshake(self, line: str) -> None:
        with self._lock:
            self._hardware.log = (self._hardware.log + [line])[-20:]
        if self._on_handshake is not None:
            self._on_handshake(line)

    def _start_home_locked(self) -> None:
        if self._handshake or self._transport is None or not self._hardware.connected:
            return
        self._handshake = True
        self._hardware.homed = False
        self._hardware.fdd_status = 'homing'
        threading.Thread(target=self.home, name='fdd-home', daemon=True).start()

    def home(self) -> bool:
        """Recover position on the existing Serial connection; leave playback paused."""
        with self._lock:
            if self._transport is None or not self._hardware.connected:
                raise EngineError('brak polaczenia z Arduino')
        if not self._home_lock.acquire(blocking=False):
            return False
        transport = None
        try:
            with self._lock:
                transport = self._transport
                if transport is None or not self._hardware.connected:
                    raise EngineError('brak polaczenia z Arduino')
                self._handshake = True
                self._hardware.homed = False
                self._hardware.fdd_status = 'homing'
                if self._state is PlaybackState.PLAYING:
                    self._position_base = self._position_locked()
                    self._state = PlaybackState.PAUSED
                self._preview.stop()
                self._reset_instruments_locked()
                if not self._hardware.connected:
                    return False
                if getattr(transport, 'protocol_version', 1) == 2:
                    self._sync_v2_devices_locked(force=True)
                    transport.send('FDD ALL HOME')
                else:
                    transport.send('HOME')
            wait = getattr(transport, 'wait_homed', getattr(transport, 'wait_ready', None))
            ok = bool(wait(timeout=self._ready_timeout, echo=self._record_handshake)) if wait and self._wait_ready else True
            with self._lock:
                if self._transport is not transport:
                    return False
                self._hardware.homed = ok
                self._hardware.fdd_status = 'ready' if ok else 'error'
                self._hardware.error = None if ok else 'FDD: homing nieudany. Sprawdź mechanikę i TRACK0; Retry Home.'
                self._hardware.warning = 'Pozycja FDD odzyskana; możesz wznowić odtwarzanie.' if ok and self._state is PlaybackState.PAUSED else None
                self._last_io = time.monotonic()
                self._drum_value = 0
                self._drum_drive_sent = 0
                self._drum_tone_sent = -1
                self._apply_drum_locked(tone_hz=self._drum_tone_hz, force=True)
                self._request_status_locked(force=True)
                if ok and getattr(transport, 'protocol_version', 1)==2:
                    self._sync_v2_devices_locked()
                ok = ok and self._hardware.connected
                self._handshake = False
                pending = self._pending_play
                self._pending_play = False
            if ok and pending:
                self.play()
            return ok
        except EngineError:
            return False
        except Exception as exc:
            with self._lock:
                if self._transport is transport:
                    self._fail_locked(f'blad transportu podczas HOME: {exc}')
            return False
        finally:
            with self._lock:
                if self._transport is transport:
                    self._handshake = False
            self._home_lock.release()

    def disconnect(self) -> None:
        with self._lock:
            was_playing = self._state is PlaybackState.PLAYING
            self._pending_play = False

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
        self._execution_profiles = {}

        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

        self._hardware.connected = False
        self._hardware.homed = False
        self._hardware.fdd_status = 'not_homed'
        self._handshake = False

    # ==========================================================
    # WCZYTANIE UTWORU
    # ==========================================================

    @staticmethod
    def _read_saved_arrangement(source: MidiSource) -> dict | None:
        """`<nazwa>.orchestra.json` obok pliku MIDI, jesli jest poprawnym JSON-em."""
        path = source.path.with_suffix('.orchestra.json')

        if not path.is_file():
            return None

        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None

        return document if isinstance(document, dict) else None

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

        # Zapisana aranzacja obok pliku to OPCJONALNY override. Jesli istnieje
        # i pasuje do tego MIDI, wygrywa z auto-aranzacja; jesli nie - cichy
        # powrot do auto, bo reczny JSON nigdy nie moze zablokowac odtwarzania.
        saved = self._read_saved_arrangement(source)

        with self._lock:
            self._preview.close()
            self._arrangement = None
            self._plan = None
            self._plan_report = None
            self._normalized = None
            self._arrangement_notes = []
            self._arrangement_revision += 1
            self._safe_send_stop_locked()

            self._source = source
            self._file_name = Path(path).name
            self._track_index = track_index
            self._state = PlaybackState.STOPPED
            self._position_base = 0.0
            self._current = None

            if saved is not None:
                try:
                    self._configure_arrangement_locked(saved)
                except (ArrangementError, ValueError, TypeError):
                    self._arrangement = None

            self._rebuild_locked(keep_position=False)
            self._wake.set()

    def set_track(self, track_index: int) -> None:
        """Zmiana tracku zachowuje pozycje i stan (gra dalej od tego samego miejsca)."""
        with self._lock:
            self._auto_arrange = False
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
            self._auto_arrange = False
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
            self._auto_arrange = False
            if strategy == self._strategy:
                return

            self._strategy = strategy
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    # ---------- druga linia: VHS drum z MIDI ----------

    def set_drum_track(self, track_index: int | None) -> None:
        """Przypisuje track MIDI do bebna (None = beben tylko reczny)."""
        with self._lock:
            self._auto_arrange = False
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
            self._auto_arrange = False
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
            self._auto_arrange = False
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
            self._auto_arrange = False
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
            self._auto_arrange = False
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
            self._auto_arrange = False
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
        self._preview_generation += 1
        self._preview_request = None

        if self._auto_arrange or self._physical_context_locked() is not None:
            self._rebuild_plan_locked(position)
            return

        if self._virtual_mode:
            was_playing = self._state is PlaybackState.PLAYING
            if not was_playing:
                self._preview.close()
            self._timeline = self._virtual.simulate(self._source)
            self._arrangement_notes = []
            self._hardware_active = False
            self._hardware_bound = {}
            self._hardware_unmapped = []
            position = max(0.0, min(position, self._timeline.duration))
            if was_playing:
                # Keep the old preview and monotonic playhead running while a
                # replacement WAV is rendered off the engine lock.
                self._next_index = self._timeline.index_after(position)
                self._request_preview_locked(self._virtual, self._timeline.duration)
            else:
                self._position_base = position
                self._next_index = self._timeline.index_after(position)
            return

        self._hardware_active = True
        self._hardware_bound = {}
        self._hardware_unmapped = []

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

    def _physical_context_locked(self):
        # The preview stays legacy. Explicit real/hybrid instances opt into the
        # physical planner even while disconnected (which yields NO_DEVICE).
        if self._controller_target != 'esp32' or not any(d.drives_hardware for d in self._orchestra.instances()):
            return None
        if not hasattr(self, '_physical_registry'):
            self._physical_registry = HardwareRegistry()
        return HardwareContext(self._hardware.connected, self._physical_registry,
                               self._orchestra.hardware.get('inventory'))

    def _build_plan_locked(self) -> None:
        """MIDI + orkiestra -> plan wykonania. Bez tego nie ma czego grac."""
        if self._source is None:
            self._plan = None

            return

        if self._normalized is None:
            # Double-tracking -> partie logiczne. Liczone raz na plik.
            self._normalized = normalize(self._source)

        pins = (manual_pins(self._arrangement, self._normalized)
                if self._arrangement is not None else {})
        self._plan = allocate(
            self._normalized, self._orchestra, pins=pins,
            name=self._source.path.stem,
            origin='manual' if self._arrangement is not None else 'auto',
            hardware_context=self._physical_context_locked())

    def _plan_notes_locked(self) -> list[dict]:
        """Widok nut dla UI: zrodlo + decyzja arrangera + faktyczny czas."""
        if self._plan is None:
            return []

        notes = []

        for event in self._plan.events:
            notes.append({
                'id': event.id,
                'track': event.track,
                'trackName': event.track_name,
                'channel': event.channel,
                'note': event.note,
                'name': event.name,
                'start': round(event.start, 6),
                'duration': round(event.duration, 6),
                'velocity': event.velocity,
                'isDrum': event.role == 'percussion',
                'status': event.status,
                'outcome': event.outcome,
                'role': event.role,
                'deviceId': event.device_id,
                'playedNote': event.played_note,
                'actualStart': round(event.actual_start, 6),
                'actualDuration': round(event.actual_duration, 6),
                'delayMs': round(event.delay * 1000, 2),
                'reassigned': event.reassigned,
                'folded': event.folded,
                'preferredDevice': event.preferred_device,
                'reason': event.reason,
                'hardware': event.hardware,
                'sourceTracks': list(event.source_tracks),
                'duplicateGroupId': event.duplicate_group_id,
                'routes': [] if event.device_id is None else [{
                    'ruleId': event.rule_id or 'auto',
                    'deviceId': event.device_id,
                    'status': event.status,
                    'outcome': event.outcome,
                    'articulation': event.articulation,
                    'reason': event.reason,
                    'originalNote': event.note,
                    'playedNote': event.played_note,
                    'deviceAvailableAt': None,
                }],
            })

        return notes

    def _rebuild_plan_locked(self, position: float) -> None:
        """Timeline z PerformancePlan: symulacja + (opcjonalnie) fizyczne linie.

        Plan jest jedynym zrodlem decyzji. Renderer odtwarza go 1:1, a komendy
        sprzetowe powstaja z tych samych zdarzen - wirtualizacja i sprzet nie
        moga sie rozjechac.
        """
        was_playing = self._state is PlaybackState.PLAYING

        if not was_playing:
            self._preview.close()

        self._build_plan_locked()

        timeline = self._virtual.render_plan(self._plan)

        # Bez podlaczonego Arduino Auto Arranger gra na Virtual Orchestra.
        # Bez tego "wrzuc MIDI i nacisnij Play" konczylo sie bledem
        # "brak polaczenia z Arduino", mimo ze plan jest gotowy.
        if self._runtime_preview is None and self._transport is None and any(
                device.get('mode', 'virtual') in ('virtual', 'hybrid')
                for device in self._plan.devices):
            self._virtual_mode = True
        notes = self._plan_notes_locked()
        # Raport liczymy raz na przebudowe - snapshot leci po WebSocketcie
        # przy kazdej zmianie stanu i nie moze za kazdym razem chodzic po
        # wszystkich zdarzeniach planu.
        self._plan_report = self._plan.report()

        bound, unmapped = bind_devices(self._orchestra.instances() if self._plan.hardware else self._virtual.devices, getattr(self._transport, 'protocol_version', 1))
        if self._plan.hardware:
            allowed = set(self._plan.hardware['physicalLanes'].values())
            bound = {lane:d for lane,d in bound.items() if lane in allowed}
        self._hardware_bound = bound
        self._hardware_unmapped = unmapped
        if getattr(self._transport, 'protocol_version', 1) == 2:
            self._sync_v2_devices_locked()
        hardware_commands = (build_plan_commands(self._plan, bound) if self._plan.hardware
                             else build_commands(self._virtual, bound))
        self._hardware_active = bool(hardware_commands)

        merged = list(timeline.commands) + hardware_commands
        self._timeline = Timeline.from_commands(merged, timeline.stats)

        self._arrangement_notes = notes
        self._arrangement_revision += 1

        position = max(0.0, min(position, self._timeline.duration))

        if was_playing:
            self._next_index = self._timeline.index_after(position)
            if self._virtual_mode:
                self._request_preview_locked(self._virtual, self._timeline.duration)
        else:
            self._position_base = position
            self._next_index = self._timeline.index_after(position)

    def _request_preview_locked(self, orchestra: VirtualOrchestra, duration: float) -> None:
        self._preview_request = (self._preview_generation, orchestra, duration)
        if self._preview_worker_running:
            return
        self._preview_worker_running = True
        threading.Thread(target=self._render_preview_worker, name='virtual-preview-refresh', daemon=True).start()

    def _render_preview_worker(self) -> None:
        """Coalesce rapid edits; swap audio at the current position when ready."""
        while True:
            with self._lock:
                request = self._preview_request
                self._preview_request = None
                if request is None or self._shutdown:
                    self._preview_worker_running = False
                    return
            generation, orchestra, duration = request
            preview = WavePreview(clocked=True)
            try:
                preview.render(orchestra, duration)
            except Exception:
                preview.close()
                continue
            with self._lock:
                if generation != self._preview_generation or self._shutdown or not self._virtual_mode:
                    preview.close()
                    continue
                old_preview = self._preview
                preview.master_volume = self._virtual.master_volume
                try:
                    if self._state is PlaybackState.PLAYING:
                        preview.play(self._position_locked())
                except Exception:
                    preview.close()
                    continue
                self._preview = preview
                self._audio_revision += 1
                old_preview.close()

    def _runtime_config(self, payload: dict) -> dict:
        """Startup owns output mode; old per-device mode is only an internal detail."""
        if self._runtime_preview is None:
            return payload
        payload = copy.deepcopy(payload)
        payload['enabled'] = self._runtime_preview
        if payload.get('devices') is not None:
            for device in payload['devices']:
                device['mode'] = 'virtual' if self._runtime_preview else 'real'
        return payload

    def configure_virtual(self, payload: dict) -> None:
        """Switch output without replacing MIDI source, tempo map or worker clock."""
        payload = self._runtime_config(payload)
        candidate = VirtualOrchestra()
        candidate.set_config(payload)
        with self._lock:
            enabled = bool(payload.get('enabled', True))
            # Output gain does not change the plan or require WAV regeneration.
            previous = self._virtual.config()
            proposed = candidate.config()
            if enabled == self._virtual_mode and all(
                proposed[key] == previous[key] for key in proposed if key not in ('masterVolume', 'hddMode', 'tonalMode')
            ):
                mode_changed = (self._virtual.hdd_mode != candidate.hdd_mode
                                or self._virtual.tonal_mode != candidate.tonal_mode)
                self._virtual.hdd_mode = candidate.hdd_mode
                self._virtual.tonal_mode = candidate.tonal_mode
                self._virtual.master_volume = candidate.master_volume
                self._preview.master_volume = candidate.master_volume
                if mode_changed and self._virtual_mode and self._timeline:
                    self._preview_generation += 1
                    self._request_preview_locked(copy.copy(self._virtual), self._timeline.duration)
                elif self._virtual_mode and self._state is PlaybackState.PLAYING:
                    self._preview.play(self._position_locked())
                self._wake.set()
                return

            if not enabled and self._state is PlaybackState.PLAYING and self._transport is None:
                raise EngineError('stop or pause before disabling virtual output without connected hardware')
            if self._arrangement is not None and self._source is not None:
                doc = self._arrangement.as_dict().copy()
                doc['devices'] = [dataclasses.asdict(d) for d in candidate.devices]
                ids = {d.id for d in candidate.devices}
                doc['rules'] = [rule for rule in doc['rules'] if rule['destination']['deviceId'] is None or rule['destination']['deviceId'] in ids]
                existing = {rule['destination']['deviceId'] for rule in doc['rules']}
                for device in candidate.devices:
                    if device.id not in existing and device.track is not None:
                        doc['rules'].append({'id': f'route-{device.id}', 'source': {'track': device.track},
                                             'destination': {'deviceId': device.id}})
                self._arrangement = Arrangement.parse(doc, self._source)
            if not self._virtual_mode:
                self._reset_instruments_locked()
            self._virtual = candidate
            # UI Virtual Orchestra jest edytorem rzeczywistego OrchestraConfig.
            # Bez synchronizacji Auto Arranger nadal alokowalby stara pule.
            self._orchestra = parse_orchestra({
                'name': candidate.name,
                'hardware': payload.get('hardware', self._orchestra.hardware),
                'devices': candidate.config()['devices'],
                'policy': {**self._orchestra.policy, 'sourceContinuity': candidate.source_continuity, 'sourceContinuityAmount': candidate.source_continuity_amount},
                'dvdMode': candidate.dvd_mode, 'trayEnabled': candidate.tray_enabled, 'idleReinforcement': candidate.idle_reinforcement,
            })
            if candidate.dvd_mode == 'reinforcement' or candidate.idle_reinforcement.get('enabled') or candidate.source_continuity:
                # Reinforcement runs after the normal PerformancePlan is built.
                self._auto_arrange = True
            self._virtual_mode = enabled
            if not enabled:
                self._preview.close()
            self._rebuild_locked(keep_position=True)
            if getattr(self._transport, 'protocol_version', 1) == 2:
                self._sync_v2_devices_locked()
            self._wake.set()

    def _configure_arrangement_locked(self, payload: dict, *, allow_mismatch: bool = False) -> None:
        """Ustawia orkiestre i override z dokumentu. Nie przebudowuje planu.

        Urzadzenia z dokumentu staja sie orkiestra, a reguly - preferencjami
        allokatora. Regula NIE przybija nuty na stale: gdy wskazane urzadzenie
        jest zajete, inne wolne i tak ja uratuje.
        """
        payload = self._runtime_config(payload)
        arrangement = Arrangement.parse(payload, self._source, allow_mismatch=allow_mismatch)
        orchestra = parse_orchestra({
            'name': str(payload.get('name') or arrangement.data.get('name') or 'Arrangement'),
            'devices': arrangement.data['devices'],
            'hardware': payload.get('hardware', {}),
            'policy': payload.get('policy'),
            'dvdMode': payload.get('dvdMode'), 'trayEnabled': payload.get('trayEnabled', True), 'idleReinforcement': payload.get('idleReinforcement'),
        })
        bound, _ = bind_devices(orchestra.instances(), getattr(self._transport, 'protocol_version', 1))
        preview_devices = [device for device in orchestra.instances() if device.in_preview]

        if not self._virtual_mode and not bound:
            self._reset_instruments_locked()

        self._arrangement = arrangement
        self._orchestra = orchestra
        self._auto_arrange = True

        # Import nie przelacza na sile wirtualizacji - patrz komentarz przy
        # render_plan. Podglad musi dzialac, gdy dokument ma cokolwiek do
        # uslyszenia albo nie ma gdzie wyslac komend sprzetowych.
        if self._runtime_preview is None and (preview_devices or not bound or self._transport is None):
            self._virtual_mode = True

    def set_arrangement(self, payload: dict, *, allow_mismatch: bool = False) -> None:
        """Reczny override aranzacji (import JSON) - reszta nadal przez allocator."""
        with self._lock:
            if self._source is None:
                raise EngineError('load MIDI before importing an arrangement')

            self._configure_arrangement_locked(payload, allow_mismatch=allow_mismatch)
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    def has_arrangement_override(self) -> bool:
        """Czy uzytkownik wczytal wlasny JSON (a nie tylko auto-aranzacja)."""
        with self._lock:
            return self._arrangement is not None

    def set_orchestra(self, payload: dict) -> None:
        """Zmiana dostepnego sprzetu - plan powstaje od nowa."""
        with self._lock:
            self._orchestra = parse_orchestra(self._runtime_config(payload))
            self._orchestra.devices = self._runtime_config({'devices': self._orchestra.devices})['devices']
            self._auto_arrange = True
            self._arrangement = None
            self._rebuild_locked(keep_position=True)
            self._wake.set()

    def initialize_arrangement(self) -> None:
        with self._lock:
            if self._source is None:
                raise EngineError('load MIDI first')

            # "Zainicjalizuj aranzacje" = wlacz Auto Arrangera i zbuduj plan.
            self._auto_arrange = True

            if self._plan is None:
                self._rebuild_locked(keep_position=True)

    def _document_locked(self) -> dict | None:
        """Dokument aranzacji: orkiestra + polityka + reczne reguly.

        Reguly sa PUSTE przy auto-aranzacji - plan jest deterministyczny, wiec
        ten sam plik MIDI + ta sama orkiestra odtworza go bez zapisywania
        tysiecy przypisan nuta-po-nucie.
        """
        if self._source is None or self._plan is None:
            return None

        return {
            'schemaVersion': 1,
            'midi': midi_identity(self._source),
            'name': self._plan.name,
            'devices': self._orchestra.devices,
            'rules': list(self._arrangement.data['rules']) if self._arrangement is not None else [],
            'policy': self._orchestra.policy,
            'dvdMode': self._orchestra.dvd_mode, 'trayEnabled': self._orchestra.tray_enabled, 'idleReinforcement': self._orchestra.idle_reinforcement,
            'origin': self._plan.origin,
        }

    def _source_tracks(self) -> list:
        """Partie logiczne, jesli zrodlo jest juz znormalizowane."""
        if self._normalized is not None:
            return self._normalized.tracks

        return list(self._source.tracks) if self._source is not None else []

    def _reinforcement_notes_locked(self) -> list:
        if not self._plan:
            return []
        sources = {e.id: e for e in self._plan.events}
        notes = []
        for index, extra in enumerate(self._plan.reinforcements):
            source = sources[extra.source_id]
            notes.append({**extra.as_dict(), 'id': f'reinforcement:{index}:{extra.source_id}',
                'track': source.track, 'trackName': source.track_name, 'channel': source.channel,
                'note': source.played_note if source.played_note is not None else source.note,
                'name': source.name, 'isDrum': source.role == 'percussion',
                'reinforcement': True, 'eventKind': 'reinforcement',
                'deviceId': extra.device_id, 'status': 'ACCEPTED',
                'routes': [{'ruleId': 'reinforcement', 'deviceId': extra.device_id,
                            'status': 'ACCEPTED', 'reason': extra.reason}]})
        return notes

    def telemetry_view(self) -> dict:
        """Read-only renderer metadata. No plan initialization or playback changes."""
        with self._lock:
            sources = {e.id: e for e in self._plan.events} if self._plan else {}
            trays = {(e.device_id, e.start): e for e in self._plan.tray_events} if self._plan else {}
            intervals = {(device, start): end for device, rows in self._virtual.activity.items() for start, end in rows}
            def project(rows, audible=False):
                events = []
                for i, event in enumerate(rows):
                    if event.kind not in ('tone', 'hit', 'tray'):
                        continue
                    source = sources.get(event.source_id)
                    tray = trays.get((event.device, event.time))
                    art = event.tonal_articulation
                    events.append({
                        'id': f'{event.device}:{i}', 'deviceId': event.device,
                        'start': event.time, 'duration': event.duration if audible else intervals.get((event.device, event.time), event.time + event.duration) - event.time,
                        'kind': event.kind, 'hz': event.hz,
                        'note': round(hz_to_midi(event.hz)) if event.kind == 'tone' and event.hz > 0 else event.source_note,
                        'sourceNote': tray.note if tray else event.source_note,
                        'track': tray.source_track_name if tray else event.source_track,
                        'velocity': event.velocity, 'role': source.role if source else '',
                        'reinforcement': event.reinforcement or tray is not None,
                        'profile': art.profile if art else None,
                        'articulation': event.hdd_articulation.kind if event.hdd_articulation else None,
                        'direction': event.direction,
                        'frequencyCurve': {'times': art.frequency.times, 'values': art.frequency.values} if art else None,
                    })
                events.sort(key=lambda e: e['start'])
                return events
            return {'file': self._file_name, 'revision': self._arrangement_revision,
                    'events': project(self._virtual.events),
                    'audioEvents': project(self._preview.audio_events, audible=True) if self._preview.path else [],
                    'audioRevision': self._audio_revision, 'activity': self._virtual.activity,
                    'report': self._plan_report if self._plan else None}

    def arrangement_view(self) -> dict:
        with self._lock:
            return {
                'arrangement': self._document_locked(),
                'notes': self._arrangement_notes,
                'trayNotes': [{**event.as_dict(), 'id': f'tray:{event.device_id}:{event.source_id}',
                    'trackName': event.source_track_name or 'DVD tray reinforcement', 'name': f'GM {event.note} · tray',
                    'isDrum': True, 'routes': [{'ruleId': 'tray-reinforcement', 'deviceId': event.device_id,
                        'status': 'ACCEPTED', 'reason': 'TRAY_REINFORCEMENT'}], 'deviceId': event.device_id,
                    'actualStart': event.start, 'actualDuration': event.duration,
                    'status': 'ACCEPTED', 'reason': 'TRAY_REINFORCEMENT'}
                    for event in (self._plan.tray_events if self._plan else [])],
                'reinforcementNotes': self._reinforcement_notes_locked(),
                'midiIdentity': midi_identity(self._source) if self._source else None,
                'tracks': [{'index': t.index, 'name': t.name, 'isDrums': t.is_drums,
                            'noteCount': t.note_count,
                            'sourceTracks': list(getattr(t, 'source_tracks', (t.index,))),
                            'groupId': getattr(t, 'group_id', None),
                            'duplicateConfidence': getattr(t, 'duplicate_confidence', None)}
                           for t in self._source_tracks()],
                'revision': self._arrangement_revision,
                'report': self._plan.report() if self._plan is not None else None,
                'orchestra': {
                    'name': self._orchestra.name,
                    'policy': self._orchestra.policy,
                    'dvdMode': self._orchestra.dvd_mode, 'trayEnabled': self._orchestra.tray_enabled, 'idleReinforcement': self._orchestra.idle_reinforcement,
                    'devices': [{'id': d['id'], 'type': d['type'], 'name': d['name']}
                                for d in self._orchestra.devices],
                },
            }

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

            # Podglad renderujemy TYLKO gdy go nie ma (albo jest nieaktualny).
            # Wczesniej lecial od nowa przy kazdym Play - przy 6 urzadzeniach
            # to ~6 s, przy 40 ~20 s zamrozonego UI i locka silnika.
            self._begin_locked(position)

    def pause(self) -> None:
        with self._lock:
            self._pending_play = False
            if self._state is not PlaybackState.PLAYING:
                self._preview.stop()
                self._reset_instruments_locked(force_hardware=True)
                return

            position = self._position_locked()
            self._preview.stop()
            self._reset_instruments_locked(force_hardware=True)
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
        """Stop all connected hardware and preview; reset playhead to zero."""
        with self._lock:
            self._pending_play = False
            self._preview.stop()
            if not self._reset_instruments_locked(force_hardware=True) and self._hardware.connected:
                self._position_base = self._position_locked()
                self._state = PlaybackState.PAUSED
                self._wake.set()
                return
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

        if self._transport is None and not self._virtual_mode:
            # Homing/reconnect trwa (do ready_timeout). Zamiast cicho nie
            # zrobic nic albo straszyc bledem - zapamietujemy zamiar
            # i zagramy, gdy tylko pojawi sie READY.
            if self._handshake:
                self._pending_play = True
                self._wake.set()
                return

            self._fail_locked("brak polaczenia z Arduino")
            return

        if not self._virtual_mode or self._hardware_active:
            if self._handshake:
                self._pending_play = True
                return
            if self._transport is not None and not self._hardware.connected:
                raise EngineError(self._hardware.error or 'brak polaczenia z Arduino')
            if self._transport is not None and not self._hardware.homed:
                if self._hardware.fdd_status == 'error':
                    raise EngineError(self._hardware.error or 'FDD: Retry Home')
                self._pending_play = True
                self._start_home_locked()
                return
            if self._hardware.connected and self._hardware.homed:
                self._hardware.error = None

        if self._plan and self._plan.hardware and self._transport is not None:
            self._sync_v2_devices_locked()
        if self._virtual_mode:
            if self._preview.path is None:
                self._preview.render(self._virtual, timeline.duration)
                self._audio_revision += 1
            self._preview.play(position)

            if not (self._hardware_active and self._transport is not None):
                # Czysty podglad wirtualny: sprzet zostaje nietkniety.
                self._next_index = timeline.index_after(position)
                self._origin = time.monotonic() - position
                self._position_base = position
                self._state = PlaybackState.PLAYING
                self._wake.set()
                return

            # Tryb hybrydowy: podglad gra dalej, a ponizszy kod wysyla stan
            # linii sprzetowych. _reset_instruments_locked nie zatrzymuje
            # wtedy preview.

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
            if ':' in command.lane and command.kind in ('hit', 'tray_pulse'):
                self._send_locked(command)
            elif command.lane == LANE_HDD and command.kind == "hit":
                self._send_raw_locked("HIT")
                self._hdd_current = command
                self._hdd_count += 1

        self._next_index = timeline.index_after(position)
        self._wake.set()

    def _reset_instruments_locked(self, *, force_hardware: bool = False) -> bool:
        """STOP + DRUM 0 + HDD 0 (wspolny punkt startu po seek/pauza/stop).

        Nic nie wysyla, gdy zaden plan nie uzywa fizycznych linii: czysty
        podglad wirtualny nie moze szarpac podlaczonym sprzetem.
        Jawny Stop wymusza zatrzymanie sprzetu niezaleznie od planu.
        """
        if self._transport is None:
            return True

        if not force_hardware and self._virtual_mode and not self._hardware_active and not self._handshake:
            return True

        if getattr(self._transport, 'protocol_version', 1) == 2:
            stop_ok = self._safe_send_stop_locked()
            if stop_ok:
                self._drum_value = 0
                self._drum_drive_sent = 0
                self._drum_current = None
                self._hdd_current = None
                self._hdd_busy = False
            return stop_ok
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
                "hardware": {
                    **self._hardware.as_dict(),
                    # connecting: trwa homing/reconnect (Play poczeka w kolejce).
                    "connecting": self._handshake,
                    "controllerTarget": self._controller_target,
                    "transport": 'ble' if self._controller_target == 'esp32' else 'serial',
                    "connectionStatus": 'connected' if self._hardware.connected else 'connecting' if self._handshake else 'disconnected',
                    "pendingPlay": self._pending_play,
                    "ready": self._hardware.connected and self._hardware.homed and not self._handshake,
                    "board": getattr(self._transport, "board", "uno"),
                    "protocol": getattr(self._transport, "protocol_version", 1),
                    "devices": getattr(self._transport, "device_status", {}),
                    "timingDiagnostics": {
                        "lateCommands": self._late_commands,
                        "discardedAtEnd": self._end_discarded_commands,
                        "maxObservedLagMs": round(self._max_dispatch_lag * 1000, 3),
                        "scope": "engine lifetime",
                        "schedulerLagMs": round(self._scheduler_lag * 1000, 3),
                        "maxSchedulerLagMs": round(self._max_dispatch_lag * 1000, 3),
                        "lateEvents": self._late_events,
                        "droppedLateEvents": self._late_commands,
                        "backlogCollapsedEvents": self._collapsed_events,
                        "dropReasons": dict(self._late_reasons),
                        "bleBatches": self._ble_batches,
                        "bleCommands": self._ble_commands,
                        "maxCommandsPerBatch": self._max_batch_commands,
                        "lastBatchDurationMs": round(self._last_batch_duration * 1000, 3),
                        "meanBatchDurationMs": round(self._batch_total_duration * 1000 / self._ble_batches, 3) if self._ble_batches else 0.0,
                    },
                },
                "drum": self._drum_snapshot_locked(),
                "hdd": self._hdd_snapshot_locked(),
                "arrangementRevision": self._arrangement_revision,
                "arrangementActive": self._plan is not None,
                "arrangementOrigin": self._plan.origin if self._plan is not None else None,
                "hardwarePlanning": self._plan.hardware if self._plan else {},
                "arrangementTotals": self._plan_report['totals'] if self._plan_report else None,
                "arrangementHardware": {
                    # active = aranzacja kieruje cokolwiek na fizyczne linie,
                    # connected = czy jest gdzie to wyslac (Arduino).
                    "active": self._hardware_active,
                    "connected": self._transport is not None,
                    "lanes": {lane: {"deviceId": device.id, "name": device.name, "type": device.type}
                              for lane, device in self._hardware_bound.items()},
                    "unmapped": self._hardware_unmapped,
                },
                "virtual": {"audioRevision": self._audio_revision,
                            "audioPosition": self._preview.clock_position() if playing else position,
                            "audioClockRunning": self._preview.clock_running,
                            "enabled": self._virtual_mode,
                            "runtimeMode": "virtual" if self._virtual_mode else "hardware",
                            "config": {**self._virtual.config(), "devices": self._orchestra.devices, "hardware":self._orchestra.hardware},
                            "report": self._virtual.report,
                            "trayStatus": self._virtual.tray_state_at(position) if playing else {},
                            "tonalDebug": {e['deviceId']: e for e in getattr(self._preview, 'tonal_stats', {}).get('events', [])
                                           if playing and e['start'] <= position < e['start'] + e['audioDuration']},
                            "activity": (self._virtual.active_at(position, visual_hold=0.25) if self._virtual_mode and playing
                                         else {device.id: False for device in self._virtual.devices}),
                            "profiles": [profile.as_dict() for profile in PROFILES.values()]},
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
            audio = self._preview.clock_position() if self._virtual_mode and not (self._hardware_active and self._transport is not None) else None
            position = audio if audio is not None else time.monotonic() - self._origin
        else:
            position = self._position_base

        return max(0.0, min(position, duration))

    # ==========================================================
    # WYSYLKA
    # ==========================================================

    def _sync_v2_devices_locked(self, force: bool = False) -> None:
        bound, _ = bind_devices(self._orchestra.instances(), 2)
        context = self._physical_context_locked()
        if context is not None:
            filtered={}
            for lane,d in bound.items():
                profile=context.profile_for(d,lane)
                if not context.present(lane) or profile is None:continue
                if profile.name in ('FDD','DVD_SLED','HDD_PERCUSSION') and execution_command(profile,lane) is None:continue
                if profile.name=='FDD' and profile.get('travelSteps') is None:continue
                filtered[lane]=d
            bound=filtered
        for family, count in (('fdd', 4), ('sled', 4), ('hdd', 4), ('tray', 2), ('drum', 1)):
            for ident in range(1, count+1):
                on = f'{family}:{ident}' in bound
                prefix = 'VHS' if family == 'drum' else f'{family.upper()} {ident}'
                status_key = 'VHS' if family == 'drum' else f'{family.upper()}:{ident}'
                known = self._transport.device_status.get(status_key, {}).get('enabled')
                profile_status = getattr(self._transport, 'controller_status', {}).get('hardware_profiles')
                if on and context is not None and profile_status == '1':
                    profile = context.profile_for(bound[f'{family}:{ident}'], f'{family}:{ident}')
                    command = execution_command(profile, f'{family}:{ident}')
                    cache = getattr(self, '_execution_profiles', {})
                    if command and (force or cache.get(prefix) != command):
                        active=self._transport.device_status.get(status_key,{})
                        if active.get('playing')=='1' or active.get('homing')=='1':
                            self._pause_fdd_locked('Zmiana profilu hardware wymaga zatrzymania urządzenia')
                            return
                        if not self._send_raw_locked(command):
                            raise EngineError('blad transportu podczas konfiguracji profilu')
                        cache[prefix] = command
                        self._execution_profiles = cache
                if force or known != str(int(on)):
                    if not self._send_raw_locked(f'{prefix} ENABLE {int(on)}'):
                        raise EngineError('blad Serial podczas konfiguracji urządzeń')
                    if family == 'fdd' and on:
                        self._hardware.homed = False
                        self._hardware.fdd_status = 'not_homed'
                    self._transport.device_status.setdefault(status_key, {})['enabled'] = str(int(on))

    def _v2_lines_locked(self, command: Command):
        family, ident = command.lane.split(':')
        prefix = 'VHS' if family == 'drum' else f'{family.upper()} {ident}'
        if self._plan and self._plan.hardware and command.kind in ('play','hit'):
            context=self._physical_context_locked()
            device=self._hardware_bound.get(command.lane)
            profile=context.profile_for(device,command.lane) if context and device else None
            expected=execution_command(profile,command.lane) if profile else None
            if (getattr(self._transport, 'controller_status', {}).get('hardware_profiles')!='1'
                    or not expected or getattr(self,'_execution_profiles',{}).get(prefix)!=expected):
                self._pause_fdd_locked('Hardware: brak potwierdzonej wersji/konfiguracji profili; wymagane nowe firmware i konfiguracja')
                return False
        if command.kind == 'play': text = f'{prefix} PLAY {command.hz:.2f}'
        elif command.kind == 'hit': text = f'{prefix} HIT'
        elif command.kind == 'tray_pulse': text = f'{prefix} PULSE FWD {int(command.hz)}'
        elif command.kind == 'drum_on':
            return [f'VHS AMP {DRUM_DRIVE_DEFAULT}', f'VHS FREQ {command.hz:.2f}']
        else: text = f'{prefix} STOP'
        return [text]

    def _v2_command_locked(self, command: Command):
        lines = self._v2_lines_locked(command)
        if lines is False:
            return False
        for text in lines:
            self._transport.send(text)

    def _late_reason_locked(self, index, position):
        """Classify stale commands against immutable per-lane timeline state."""
        command = self._timeline.commands[index]
        if command.lane == 'virtual':
            return None
        lag = max(0.0, position - command.time)
        self._scheduler_lag = lag
        self._max_dispatch_lag = max(self._max_dispatch_lag, lag)
        if lag <= 1e-9:
            return None
        self._late_events += 1
        if command.kind in ('hit', 'tray_pulse'):
            return 'LATE_EXPIRED' if lag > .100 else None
        if command.kind not in ('play', 'drum_on'):
            return None  # Never remove a device STOP.
        if self._timing_timeline is not self._timeline:
            self._timing_timeline = self._timeline
            self._next_lane_command = [None] * len(self._timeline.commands)
            next_lane = {}
            for i in range(len(self._timeline.commands) - 1, -1, -1):
                c = self._timeline.commands[i]
                self._next_lane_command[i] = next_lane.get(c.lane)
                next_lane[c.lane] = i
        next_index = self._next_lane_command[index]
        if next_index is not None:
            following = self._timeline.commands[next_index]
            if following.time <= position + 1e-9:
                return 'LATE_SUPERSEDED' if following.kind in ('play', 'drum_on') else 'LATE_EXPIRED'
        return None  # Late, but still the required sounding state.

    def _record_late_drop_locked(self, reason):
        self._late_commands += 1
        self._late_reasons[reason] = self._late_reasons.get(reason, 0) + 1
        if reason == 'LATE_SUPERSEDED':
            self._collapsed_events += 1
            self._late_reasons['BACKLOG_COLLAPSED'] = self._late_reasons.get('BACKLOG_COLLAPSED', 0) + 1

    def _send_due_batch_locked(self, position):
        """Only identical, already-due timestamps. No lookahead/quantization."""
        commands = self._timeline.commands
        timestamp = commands[self._next_index].time
        index = self._next_index
        accepted, lines = [], []
        while index < len(commands) and commands[index].time == timestamp:
            command = commands[index]
            if command.lane != 'virtual' and ':' not in command.lane:
                break
            if command.lane != 'virtual':
                reason = self._late_reason_locked(index, position)
                if reason:
                    self._record_late_drop_locked(reason)
                else:
                    if command.kind == 'play' and (not self._hardware.homed or self._handshake):
                        self._pause_fdd_locked('FDD: oczekiwanie na poprawny homing')
                        if self._hardware.fdd_status != 'error': self._start_home_locked()
                        return False
                    try:
                        wire = self._v2_lines_locked(command)
                    except Exception as exc:
                        self._fail_locked(f'blad transportu: {exc}')
                        return False
                    if wire is False: return False
                    lines.extend(wire)
                    accepted.append(command)
            index += 1
        if lines:
            started = time.monotonic()
            try:
                self._transport.send_batch(lines)
            except Exception as exc:
                self._fail_locked(f'blad transportu: {exc}')
                return False
            self._last_io = time.monotonic()
            self._last_batch_duration = self._last_io - started
            self._batch_total_duration += self._last_batch_duration
            self._ble_batches += 1
            self._ble_commands += len(lines)
            self._max_batch_commands = max(self._max_batch_commands, len(lines))
            if self._on_command:
                for command in accepted:
                    try: self._on_command(command)
                    except Exception: pass
        self._next_index = index
        return True

    def _send_locked(self, command: Command) -> bool:
        """Wysyla komende. False = lacze padlo (stan -> PAUSED + blad)."""
        transport = self._transport

        if transport is None:
            self._fail_locked("brak polaczenia z Arduino")
            return False

        if command.kind == 'play' and (not self._hardware.homed or self._handshake):
            self._pause_fdd_locked('FDD: oczekiwanie na poprawny homing')
            if self._hardware.fdd_status != 'error':
                self._start_home_locked()
            return False

        try:
            if ':' in command.lane and getattr(transport, 'protocol_version', 1) == 2:
                if self._v2_command_locked(command) is False:
                    return False
            elif command.kind == "play":
                transport.play(command.hz)
            else:
                transport.stop()
        except Exception as exc:
            self._fail_locked(f"blad transportu: {exc}")
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
            if getattr(self._transport, 'protocol_version', 1) == 2:
                confirmed = getattr(self._transport, 'controller_status', {}).get('stop_ack') == '1'
                if confirmed and not self._handshake:
                    self._transport.all_stop_confirmed()
                else:
                    self._transport.send('ALL STOP')
            else:
                self._transport.stop()
        except StopConfirmationError as exc:
            self._hardware.error = str(exc)
            self._hardware.warning = 'Sprzęt nie potwierdził zatrzymania.'
            return False
        except Exception as exc:
            self._fail_locked(f"blad transportu: {exc}")
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
            self._fail_locked(f"blad transportu: {exc}")
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
        if getattr(self._transport, 'protocol_version', 1) == 2:
            if line == 'STATUS END':
                fdds = [v for k, v in self._transport.device_status.items()
                        if k.startswith('FDD:') and v.get('enabled') == '1']
                self._hardware.homed = all(v.get('homed') == '1' for v in fdds)
                self._hardware.fdd_status = 'ready' if self._hardware.homed else 'not_homed'
            return
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
            elif key == "homed":
                self._hardware.homed = value == "1"
                if self._hardware.homed or self._hardware.fdd_status != "error":
                    self._hardware.fdd_status = "ready" if self._hardware.homed else "not_homed"
            elif key == "hdd":
                self._hdd_busy = value == "1"

    def _fail_locked(self, message: str) -> None:
        """Awaria lacza: nie udajemy, ze utwor gra dalej."""
        # A read failure can leave writes usable. One best-effort global STOP;
        # no recursive failure handler and no claim of delivery on a broken link.
        transport = self._transport
        if transport is not None:
            try:
                if getattr(transport, 'protocol_version', 1) == 2:
                    transport.send('ALL STOP')
                else:
                    transport.stop()
                    transport.send('DRUM 0')
                    transport.send('HDD 0')
            except Exception:
                pass
        self._pending_play = False
        self._preview.stop()
        self._hardware.connected = False
        self._hardware.homed = False
        self._hardware.fdd_status = "not_homed"
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

    def _pause_fdd_locked(self, message: str) -> None:
        if self._state is PlaybackState.PLAYING:
            self._position_base = self._position_locked()
            self._state = PlaybackState.PAUSED
        self._preview.stop()
        self._hardware.error = message
        self._current = None
        self._pending_play = False
        self._reset_instruments_locked(force_hardware=True)
        self._wake.set()

    def _poll_lines_locked(self) -> None:
        transport = self._transport

        if transport is None:
            return

        try:
            lines = transport.poll_lines()
        except Exception as exc:
            self._fail_locked(f"blad odczytu transportu: {exc}")
            return

        for line in lines:
            self._hardware.log = (self._hardware.log + [line])[-5:]

            if line.startswith('POSITION_RESYNC '):
                self._hardware.position_resyncs += 1
                self._hardware.last_position_resync = line
                continue

            if line.startswith("STATUS"):
                self._parse_status_locked(line)
                continue

            if line.startswith('READY protocol=2') or line == 'READY' or line == 'HOMING' or line.startswith('electromechanical-midi floppy controller'):
                self._pause_fdd_locked('Arduino: reset/homing — odzyskiwanie pozycji')
                self._hardware.homed = False
                self._start_home_locked()
                break
            if line.startswith(('ERR TRAVEL_UNKNOWN','ERR PROFILE','ERR BUSY')):
                self._execution_profiles={}
                self._pause_fdd_locked(f'Hardware planner: {line}; sprawdź profil urządzenia')
                continue
            if line.startswith(DEVICE_ERRORS):
                self._pause_fdd_locked(f"Arduino: {line}")
                if line.startswith('ERR HOST_TIMEOUT'):
                    continue
                self._hardware.homed = False
                self._hardware.fdd_status = 'error' if line.startswith(('ERR HOME_FAILED', 'ERR TRACK0_STUCK')) else 'not_homed'
                if not line.startswith(('ERR HOME_FAILED', 'ERR TRACK0_STUCK')):
                    self._start_home_locked()
                    break

    def _keepalive_locked(self) -> None:
        if self._handshake:
            return
        if self._virtual_mode and not self._hardware_active:
            return
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
            self._fail_locked(f"blad transportu: {exc}")
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
                if not self._handshake and self._transport is not None and (not self._virtual_mode or self._hardware_active):
                    self._poll_lines_locked()

                if (
                    self._state is not PlaybackState.PLAYING
                    or self._handshake
                    or self._timeline is None
                    or (self._transport is None and not self._virtual_mode)
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
                    if not self._handshake and (not self._virtual_mode or self._hardware_active):
                        self._poll_lines_locked()

                self._wake.wait(timeout=WORKER_IDLE_POLL_S)
                self._wake.clear()
                continue

            self._wait(timeout)
            self._wake.clear()

            with self._lock:
                if not self._handshake:
                    self._keepalive_locked()

    def _plan_locked(self) -> float | None:
        """Wysyla wszystkie komendy, ktorych czas juz nadszedl.

        Zwraca ile sekund czekac do nastepnej komendy (None = nic nie gramy).
        """
        timeline = self._timeline

        if timeline is None:
            return None

        now = time.monotonic()
        audio_clock = self._realtime and self._virtual_mode and not (self._hardware_active and self._transport is not None) and self._preview.clock_position() is not None
        position = self._position_locked() if audio_clock else now - self._origin if self._realtime else float("inf")
        commands = timeline.commands
        physical_realtime = (self._realtime and self._transport is not None
                             and (not self._virtual_mode or self._hardware_active) and not audio_clock)

        while self._next_index < len(commands):
            # The MIDI deadline wins over draining history on a slow link.
            if physical_realtime and position >= timeline.duration:
                self._end_discarded_commands += len(commands) - self._next_index
                for expired in commands[self._next_index:]:
                    if expired.lane != 'virtual' and expired.kind in ('play', 'drum_on', 'hit', 'tray_pulse'):
                        self._record_late_drop_locked('LATE_EXPIRED')
                self._next_index = len(commands)
                break
            command = commands[self._next_index]

            if command.time > position + 1e-9:
                break

            if (physical_realtime and ':' in command.lane
                    and getattr(self._transport, 'protocol_version', 1) == 2
                    and getattr(self._transport, 'is_ble', False)
                    and callable(getattr(self._transport, 'send_batch', None))):
                if not self._send_due_batch_locked(position):
                    return None
                position = time.monotonic() - self._origin
                if time.monotonic() - now >= .050:
                    break
                continue

            if physical_realtime:
                reason = self._late_reason_locked(self._next_index, position)
                if reason:
                    self._record_late_drop_locked(reason)
                    self._next_index += 1
                    continue

            if command.lane in LANES and self._transport is None:
                # Podglad wirtualny bez podlaczonego sprzetu: linie sprzetowe
                # zostaja w planie (zagraja po podlaczeniu), ale nie mamy
                # gdzie ich teraz wyslac.
                pass
            elif ':' in command.lane:
                if not self._send_locked(command):
                    return None
            elif command.lane == LANE_DRUM:
                if not self._dispatch_drum_locked(command):
                    return None
            elif command.lane == LANE_HDD:
                if not self._send_raw_locked("HIT"):
                    return None

                self._hdd_current = command
                self._hdd_count += 1
            elif command.lane == 'virtual':
                pass  # PCM was rendered from accepted mechanical events.
            else:
                if not self._send_locked(command):
                    return None

                self._current = command if command.kind == "play" else None

            self._next_index += 1

            if self._realtime:
                position = self._position_locked() if audio_clock else time.monotonic() - self._origin
            # Release the engine lock regularly so pause/STOP and error polling
            # can interrupt catch-up. The next pass keeps the same MIDI origin.
            if physical_realtime and time.monotonic() - now >= .050:
                break

        audio_finished = not audio_clock or self._preview.process is None or self._preview.process.poll() is not None
        if self._next_index >= len(commands) and position >= timeline.duration and audio_finished:
            # End of playback must silence hardware even if a final note-off is absent.
            self._state = PlaybackState.STOPPED
            self._pending_play = False
            self._preview.stop()
            stop_ok = self._reset_instruments_locked(force_hardware=True)
            if not stop_ok and self._hardware.connected:
                self._state = PlaybackState.PAUSED
                self._position_base = timeline.duration
                return None
            self._position_base = timeline.duration
            self._current = None
            self._drum_current = None
            self._hdd_current = None
            return None

        if self._next_index < len(commands):
            target = self._origin + commands[self._next_index].time
        else:
            target = self._origin + timeline.duration

        if audio_clock:
            # Output clock may be waiting for the audio device to start. No busy spin.
            return max(.005, min(.05, target - self._origin - position))
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
