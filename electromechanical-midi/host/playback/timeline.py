"""Harmonogram odtwarzania: nuty -> komendy PLAY/STOP + obsluga pozycji.

Ten modul jest wspolny dla CLI (``host/player.py``) i web playera
(``host/web/server.py``). Nie zna Serial ani WebSocketow - operuje
wylacznie na czasie w sekundach od poczatku utworu.

``Timeline`` to niemutowalny plan odtwarzania. Dzieki temu, ze zna
wszystkie komendy z gory, umie odpowiedziec na najwazniejsze pytanie
playera: **co powinno grac w danej chwili** - bez tego seek do srodka
nuty nie mialby z czego odtworzyc stanu.
"""

from __future__ import annotations

import bisect
import dataclasses

from midi_source import MidiSource, NoteSpan
from pitch import COMFORT_MAX_HZ, COMFORT_MIN_HZ, fold_note

# ------------------------------------------------------------
# Strojenie harmonogramu
# ------------------------------------------------------------

TIME_EPS = 1e-4        # 0.1 ms - ponizej tego traktujemy czasy jako rowne
SAME_HZ_EPS = 0.01     # ponizej tego to ta sama wysokosc dzwieku
MIN_NOTE_S = 0.010     # krotszych nut mechanika i tak nie zagra

# Powtorka tej samej nuty musi miec realna przerwe. Samo STOP+PLAY w tej
# samej chwili nic nie daje: obie komendy dochodza do Arduino razem, wiec
# glowica nie zdazy sie zatrzymac i slychac jedna ciagla nuta. Dlatego
# STOP leci ARTICULATION_S przed poczatkiem powtorki.
ARTICULATION_S = 0.012

DEFAULT_GATE = 1.0


@dataclasses.dataclass(frozen=True)
class Command:
    """Jedna komenda do Arduino w absolutnym czasie odtwarzania."""

    time: float
    kind: str                      # "play" | "stop"
    hz: float | None = None
    note: int | None = None        # nuta zrodlowa z pliku MIDI

    @property
    def text(self) -> str:
        if self.kind == "play":
            return f"PLAY {self.hz:.2f}"

        return "STOP"


@dataclasses.dataclass
class ScheduleStats:
    """Co sie stalo z nutami przy budowaniu harmonogramu."""

    notes: int = 0
    skipped: int = 0
    folded: int = 0
    out_of_range: int = 0
    play_commands: int = 0
    stop_commands: int = 0
    duration: float = 0.0
    min_hz: float = 0.0
    max_hz: float = 0.0

    def summary(self) -> str:
        range_text = ""

        if self.notes:
            range_text = f", wyslane {self.min_hz:.1f}-{self.max_hz:.1f} Hz"

        return (
            f"nut: {self.notes} "
            f"(zlozone oktawowo: {self.folded}, pominiete: {self.skipped}"
            f"{range_text})\n"
            f"   komendy: {self.play_commands} PLAY / {self.stop_commands} STOP\n"
            f"   dlugosc utworu: {self.duration:.2f} s"
        )

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def build_schedule(
    spans: list[NoteSpan],
    *,
    min_hz: float = COMFORT_MIN_HZ,
    max_hz: float = COMFORT_MAX_HZ,
    mode: str = "auto",
    gate: float = DEFAULT_GATE,
) -> tuple[list[Command], ScheduleStats]:
    """Zamienia nuty (juz monofoniczne) na liste komend PLAY/STOP.

    Zasady:
      * kazda nuta -> PLAY <hz> zlozone oktawowo do [min_hz, max_hz],
      * przerwa w zapisie -> STOP na koncu poprzedniej nuty,
      * nuty stykajace sie -> tylko PLAY (legato, bez sztucznej przerwy),
      * powtorka tej samej wysokosci -> STOP ARTICULATION_S przed powtorka
        i PLAY w jej poczatku, bo inaczej mechanika zagralaby jedna
        ciagla nuta zamiast dwoch.
    """
    commands: list[Command] = []
    stats = ScheduleStats()

    current_hz: float | None = None
    current_start = 0.0
    last_end = 0.0

    for span in spans:
        start = max(0.0, span.start, last_end)
        end = start + span.duration * gate

        if (end - start) < MIN_NOTE_S:
            stats.skipped += 1
            continue

        folded = fold_note(span.note, min_hz, max_hz, mode)

        stats.notes += 1

        if folded.octave_shift:
            stats.folded += 1

        if not folded.in_range:
            stats.out_of_range += 1

        if stats.min_hz == 0.0 or folded.hz < stats.min_hz:
            stats.min_hz = folded.hz

        if folded.hz > stats.max_hz:
            stats.max_hz = folded.hz

        if current_hz is not None and start > last_end + TIME_EPS:
            commands.append(Command(last_end, "stop"))
            current_hz = None

        if current_hz is not None and abs(folded.hz - current_hz) <= SAME_HZ_EPS:
            # Powtorka tej samej wysokosci wymaga realnej przerwy, ale nie
            # mozemy przy tym skrocic poprzedniej nuty ponizej MIN_NOTE_S.
            gap_start = min(
                start,
                max(start - ARTICULATION_S, current_start + MIN_NOTE_S),
            )

            commands.append(Command(gap_start, "stop"))
            current_hz = None

        commands.append(Command(start, "play", hz=folded.hz, note=span.note))

        current_hz = folded.hz
        current_start = start
        last_end = end

    if current_hz is not None:
        commands.append(Command(last_end, "stop"))

    stats.play_commands = sum(1 for command in commands if command.kind == "play")
    stats.stop_commands = len(commands) - stats.play_commands
    stats.duration = commands[-1].time if commands else 0.0

    return commands, stats


@dataclasses.dataclass(frozen=True)
class Timeline:
    """Niemutowalny plan odtwarzania jednego tracku."""

    commands: tuple[Command, ...] = ()
    stats: ScheduleStats = dataclasses.field(default_factory=ScheduleStats)
    times: tuple[float, ...] = ()

    @classmethod
    def from_commands(
        cls,
        commands: list[Command] | tuple[Command, ...],
        stats: ScheduleStats | None = None,
    ) -> "Timeline":
        frozen = tuple(commands)

        return cls(
            commands=frozen,
            stats=stats or ScheduleStats(),
            times=tuple(command.time for command in frozen),
        )

    def __len__(self) -> int:
        return len(self.commands)

    def __bool__(self) -> bool:
        return bool(self.commands)

    @property
    def duration(self) -> float:
        return self.commands[-1].time if self.commands else 0.0

    # ---------- pozycja ----------

    def index_after(self, position: float) -> int:
        """Indeks pierwszej komendy, ktora wypada PO danej pozycji."""
        return bisect.bisect_right(self.times, position)

    def command_at(self, position: float) -> Command | None:
        """Ostatnia komenda o czasie <= position."""
        index = self.index_after(position)

        return self.commands[index - 1] if index > 0 else None

    def sounding_at(self, position: float) -> Command | None:
        """Komenda PLAY, ktora powinna wlasnie grac (None = cisza)."""
        command = self.command_at(position)

        return command if command is not None and command.kind == "play" else None

    def resume_command(self, position: float) -> Command | None:
        """PLAY do wyslania NATYCHMIAST po seeku.

        Jesli w danej chwili trwa nuta (NOTE_ON byl wczesniej, NOTE_OFF
        jeszcze nie), zwracamy ja z czasem rownym pozycji - dzieki temu
        seek w srodek nuty od razu ja gra, zamiast czekac na nastepny
        NOTE_ON. Zwraca None, gdy w tym miejscu jest cisza.
        """
        playing = self.sounding_at(position)

        if playing is None:
            return None

        return dataclasses.replace(playing, time=position)

    def note_at(self, position: float) -> tuple[int | None, float | None]:
        """(nuta zrodlowa, Hz) brzmiace w danej chwili albo (None, None)."""
        playing = self.sounding_at(position)

        if playing is None:
            return (None, None)

        return (playing.note, playing.hz)


def make_timeline(
    source: MidiSource,
    track_index: int,
    *,
    strategy: str = "highest",
    min_hz: float = COMFORT_MIN_HZ,
    max_hz: float = COMFORT_MAX_HZ,
    mode: str = "auto",
    gate: float = DEFAULT_GATE,
) -> Timeline:
    """Nuty tracku -> monofonia -> komendy PLAY/STOP -> Timeline."""
    spans = source.selected_notes(track_index, strategy)

    commands, stats = build_schedule(
        spans,
        min_hz=min_hz,
        max_hz=max_hz,
        mode=mode,
        gate=gate,
    )

    return Timeline.from_commands(commands, stats)
