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

# --- linie instrumentalne (jeden wspolny timeline, jeden zegar) ---
LANE_FDD = "fdd"
LANE_DRUM = "drum"
LANE_HDD = "hdd"
LANES = (LANE_FDD, LANE_DRUM, LANE_HDD) + tuple(
    f'{kind}:{i}' for kind, count in (('fdd', 4), ('sled', 4), ('hdd', 4), ('tray', 2), ('drum', 1))
    for i in range(1, count + 1))

# HDD to instrument UDERZENIOWY (one-shot): ramie po kazdym uderzeniu trzeba
# odwiezc do parku, wiec pelny cykl trwa ~105 ms. Nuty blizsze niz to
# zlewamy w jedno uderzenie (mechanika i tak by ich nie oddzielila).
HDD_MIN_PERIOD_S = 0.11

# Napęd bębna VHS w trybie MIDI (0-255).
# 38 = 15% wypełnienia - ciszej i mniej szumu mechanicznego niz przy 74 (~29%).
# To jedna stala do strojenia: podniesienie jej = głośniejszy, ale bardziej
# "brzęczący" bęben.
DRUM_DRIVE_DEFAULT = 38

# Muzyczny zakres bębna VHS (osobny mapper, niezależny od FDD).
DRUM_MIN_HZ_DEFAULT = 110.0
DRUM_MAX_HZ_DEFAULT = 880.0


@dataclasses.dataclass(frozen=True)
class Command:
    """Jedna komenda do Arduino w absolutnym czasie odtwarzania."""

    time: float
    kind: str                      # "play" | "stop" | "drum_on" | "drum_off" | "hit"
    hz: float | None = None
    note: int | None = None        # nuta zrodlowa z pliku MIDI
    lane: str = LANE_FDD           # "fdd" | "drum" | "hdd"

    @property
    def is_note_on(self) -> bool:
        # "hit" to zdarzenie jednorazowe (one-shot), nie nuta brzmiaca -
        # dlatego nie wznawiamy go po seeku (seek w srodek nie uderza).
        return self.kind in ("play", "drum_on")

    @property
    def text(self) -> str:
        if self.kind == "play":
            return f"PLAY {self.hz:.2f}"

        if self.kind == "drum_on":
            return f"DRUM {DRUM_DRIVE_DEFAULT} + DRUMF {self.hz:.2f}"

        if self.kind == "drum_off":
            return "DRUM 0"

        if self.kind == "hit":
            return "HIT"

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
    """Niemutowalny plan odtwarzania (wszystkie linie, jeden zegar)."""

    commands: tuple[Command, ...] = ()
    stats: ScheduleStats = dataclasses.field(default_factory=ScheduleStats)
    times: tuple[float, ...] = ()

    # --- konfiguracja, z ktora timeline powstal (do UI/seek) ---
    track_index: int | None = None
    drum_track_index: int | None = None
    hdd_track_index: int | None = None

    @classmethod
    def from_commands(
        cls,
        commands: list[Command] | tuple[Command, ...],
        stats: ScheduleStats | None = None,
        *,
        track_index: int | None = None,
        drum_track_index: int | None = None,
        hdd_track_index: int | None = None,
    ) -> "Timeline":
        frozen = tuple(sorted(commands, key=lambda command: command.time))

        return cls(
            commands=frozen,
            stats=stats or ScheduleStats(),
            times=tuple(command.time for command in frozen),
            track_index=track_index,
            drum_track_index=drum_track_index,
            hdd_track_index=hdd_track_index,
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

    def commands_at(self, position: float) -> tuple[Command, ...]:
        """Komendy wypadajace dokladnie w danej chwili (w granicach TIME_EPS).

        Potrzebne do one-shot'ow (np. uderzenie HDD), ktore nie sa nutami
        i nie sa obejmowane wznowieniem stanu po play/seek.
        """
        left = bisect.bisect_left(self.times, position - TIME_EPS)
        right = bisect.bisect_right(self.times, position + TIME_EPS)

        return self.commands[left:right]

    def last_command_at(self, lane: str, position: float) -> Command | None:
        """Ostatnia komenda DANEJ LINII o czasie <= position."""
        last = None

        for command in self.commands:
            if command.time > position:
                break

            if command.lane == lane:
                last = command

        return last

    def sounding_at(self, position: float, lane: str = LANE_FDD) -> Command | None:
        """Komenda 'note on' danej linii, ktora powinna wlasnie grac."""
        command = self.last_command_at(lane, position)

        return command if command is not None and command.is_note_on else None

    def resume_command(self, position: float, lane: str = LANE_FDD) -> Command | None:
        """Komenda do wyslania NATYCHMIAST po seeku dla danej linii.

        Jesli w danej chwili trwa nuta (NOTE_ON byl wczesniej, NOTE_OFF
        jeszcze nie), zwracamy ja z czasem rownym pozycji - dzieki temu
        seek w srodek nuty od razu ja gra, zamiast czekac na nastepny
        NOTE_ON. Zwraca None, gdy w tym miejscu jest cisza.
        """
        playing = self.sounding_at(position, lane)

        if playing is None:
            return None

        return dataclasses.replace(playing, time=position)

    def resume_commands(self, position: float) -> list[Command]:
        """Stan WSZYSTKICH linii w danej chwili (do wznowienia po seeku)."""
        resumed = []

        for lane in LANES:
            command = self.resume_command(position, lane)

            if command is not None:
                resumed.append(command)

        return resumed

    def note_at(self, position: float, lane: str = LANE_FDD) -> tuple[int | None, float | None]:
        """(nuta zrodlowa, Hz) brzmiace w danej chwili albo (None, None)."""
        playing = self.sounding_at(position, lane)

        if playing is None:
            return (None, None)

        return (playing.note, playing.hz)


def build_drum_schedule(
    spans: list[NoteSpan],
    *,
    min_hz: float = DRUM_MIN_HZ_DEFAULT,
    max_hz: float = DRUM_MAX_HZ_DEFAULT,
    mode: str = "auto",
    drive: int = DRUM_DRIVE_DEFAULT,
) -> tuple[list[Command], ScheduleStats]:
    """Nuty (monofoniczne) -> komendy bebna VHS.

    Zasady:
      * nuta -> DRUM <drive> + DRUMF <hz> (wyslanie robi dispatcher),
      * przerwa w zapisie -> DRUM 0 na koncu poprzedniej nuty,
      * nuty stykajace sie (takze o tej samej wysokosci) NIE dostaja
        DRUM 0 - dzwiek przechodzi plynnie w nastepny, bez klika.
        Przy zmianie wysokosci dispatcher wysle sam DRUMF.
    """
    commands: list[Command] = []
    stats = ScheduleStats()

    last_end = 0.0
    last_hz: float | None = None

    for span in spans:
        start = max(0.0, span.start, last_end)
        end = start + span.duration

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

        touching = last_hz is not None and start <= last_end + TIME_EPS
        same_pitch = touching and abs((last_hz or 0.0) - folded.hz) <= SAME_HZ_EPS

        if touching and not same_pitch:
            # Nuta bez przerwy zmienia wysokosc - dispatcher wysle tylko DRUMF.
            pass
        elif last_hz is not None and not touching:
            commands.append(
                Command(last_end, "drum_off", lane=LANE_DRUM)
            )

        if not same_pitch:
            commands.append(
                Command(
                    start,
                    "drum_on",
                    hz=folded.hz,
                    note=span.note,
                    lane=LANE_DRUM,
                )
            )

        last_hz = folded.hz
        last_end = end

    if last_hz is not None:
        commands.append(Command(last_end, "drum_off", lane=LANE_DRUM))

    stats.play_commands = sum(1 for command in commands if command.kind == "drum_on")
    stats.stop_commands = len(commands) - stats.play_commands
    stats.duration = commands[-1].time if commands else 0.0

    return commands, stats


def build_hdd_schedule(
    notes: list[NoteSpan],
    *,
    min_period_s: float = HDD_MIN_PERIOD_S,
    note_filter: int | None = None,
) -> tuple[list[Command], ScheduleStats]:
    """Nuty tracku -> uderzenia perkusyjne HDD (one-shot).

    HDD jest instrumentem bez wysokosci dzwieku: nuta (NOTE_ON) to jedno
    uderzenie "hit". Akordy i szybkie powtorki (blizsze niz
    ``min_period_s``) zlewaja sie w jedno uderzenie, bo mechanika ma
    cykl ~105 ms i i tak by ich nie oddzielila.

    ``note_filter``: gdy podane, tylko nuty o tym numerze uderzaja.
    Caly track perkusyjny na jeden instrument brzmi jak terkot (hi-hat ma
    ~3,5 uderzenia/s i zagluszcza rytm), dlatego wybiera sie JEDNA nuta
    o charakterze rytmicznym - np. werbel (40) albo stopa (36).
    """
    commands: list[Command] = []
    stats = ScheduleStats()
    last_time = -1.0e9

    for span in notes:
        if note_filter is not None and span.note != note_filter:
            stats.skipped += 1
            continue

        start = max(0.0, span.start)

        if start < last_time + min_period_s - TIME_EPS:
            stats.skipped += 1
            continue

        commands.append(Command(start, "hit", note=span.note, lane=LANE_HDD))

        stats.notes += 1
        last_time = start

    stats.play_commands = len(commands)
    stats.duration = commands[-1].time if commands else 0.0

    return commands, stats


def make_timeline(
    source: MidiSource,
    track_index: int,
    *,
    strategy: str = "highest",
    min_hz: float = COMFORT_MIN_HZ,
    max_hz: float = COMFORT_MAX_HZ,
    mode: str = "auto",
    gate: float = DEFAULT_GATE,
    drum_track_index: int | None = None,
    drum_strategy: str | None = None,
    drum_min_hz: float = DRUM_MIN_HZ_DEFAULT,
    drum_max_hz: float = DRUM_MAX_HZ_DEFAULT,
    drum_mode: str = "auto",
    drum_drive: int = DRUM_DRIVE_DEFAULT,
    hdd_track_index: int | None = None,
    hdd_note: int | None = None,
    hdd_rate: float | None = None,
    hdd_min_period_s: float = HDD_MIN_PERIOD_S,
) -> Timeline:
    """Buduje WSPOLNY timeline: FDD + (opcjonalnie) VHS drum + (opcjonalnie) HDD.

    Wszystkie linie sa zmergowane w jedna, posortowana liste komend, wiec gra
    je jeden scheduler z jednym zegarem - nie ma niezaleznych odtwarzaczy,
    ktore moglyby sie rozjechac.
    """
    fdd_spans = source.selected_notes(track_index, strategy)

    fdd_commands, fdd_stats = build_schedule(
        fdd_spans,
        min_hz=min_hz,
        max_hz=max_hz,
        mode=mode,
        gate=gate,
    )

    drum_commands: list[Command] = []
    drum_stats = ScheduleStats()

    if drum_track_index is not None:
        drum_spans = source.selected_notes(
            drum_track_index,
            drum_strategy or strategy,
        )

        drum_commands, drum_stats = build_drum_schedule(
            drum_spans,
            min_hz=drum_min_hz,
            max_hz=drum_max_hz,
            mode=drum_mode,
            drive=drum_drive,
        )

    hdd_commands: list[Command] = []
    hdd_stats = ScheduleStats()

    if hdd_track_index is not None:
        # Limit gestosci: nigdy nie schodzimy ponizej limitu mechaniki
        # (pelny cykl park+strike), a hdd_rate pozwala przerzedzic uderzenia
        # jeszcze bardziej (np. "max 1 uderzenie na sekunde").
        min_period = hdd_min_period_s

        if hdd_rate:
            min_period = max(min_period, 1.0 / float(hdd_rate))

        hdd_commands, hdd_stats = build_hdd_schedule(
            source.notes(hdd_track_index),
            min_period_s=min_period,
            note_filter=hdd_note,
        )

    merged = list(fdd_commands) + list(drum_commands) + list(hdd_commands)

    stats = ScheduleStats(
        notes=fdd_stats.notes + drum_stats.notes + hdd_stats.notes,
        skipped=fdd_stats.skipped + drum_stats.skipped + hdd_stats.skipped,
        folded=fdd_stats.folded + drum_stats.folded + hdd_stats.folded,
        out_of_range=fdd_stats.out_of_range + drum_stats.out_of_range + hdd_stats.out_of_range,
        play_commands=(
            fdd_stats.play_commands + drum_stats.play_commands + hdd_stats.play_commands
        ),
        stop_commands=fdd_stats.stop_commands + drum_stats.stop_commands,
        duration=max(fdd_stats.duration, drum_stats.duration, hdd_stats.duration),
        min_hz=min(
            [value for value in (fdd_stats.min_hz, drum_stats.min_hz) if value] or [0.0]
        ),
        max_hz=max(fdd_stats.max_hz, drum_stats.max_hz),
    )

    return Timeline.from_commands(
        merged,
        stats,
        track_index=track_index,
        drum_track_index=drum_track_index,
        hdd_track_index=hdd_track_index,
    )
