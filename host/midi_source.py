"""Wczytywanie plikow MIDI: tracki, tempo, nuty i redukcja do monofonii.

Ten modul NIE zna Serial ani Arduino - zwraca tylko dane muzyczne
w sekundach, liczone wzgledem poczatku utworu.

Timing opiera sie na mapie tempo z pliku MIDI (set_tempo), wiec zmiany
BPM w trakcie utworu sa obslugiwane. Nie zakladamy stalego tempa.
"""

from __future__ import annotations

import bisect
import dataclasses
from pathlib import Path

import mido

DEFAULT_TEMPO = 500_000  # 120 BPM, gdyby plik nie mial zadnego set_tempo

# Dlugosc przyjmowana dla nuty bez NOTE_OFF, gdy track nie ma juz
# zadnego zdarzenia okreslajacego koniec (inaczej nuta mialaby 0 s).
DANGLING_NOTE_S = 1.0

# Nazwy nut perkusyjnych wg General MIDI (kanal 10). Uzywane m.in. przez
# perkusje HDD: to JEDEN instrument uderzeniowy, wiec z calego zestawu
# wybiera sie jedna-nute, ktora ma charakter rytmiczny (werbel, stopa).
DRUM_NAMES = {
    35: "Stopa",
    36: "Stopa",
    37: "Side stick",
    38: "Werbel",
    39: "Klaśnięcie",
    40: "Werbel",
    41: "Tom niski",
    42: "Hi-hat zamk.",
    43: "Tom niski",
    44: "Hi-hat pedal",
    45: "Tom średni",
    46: "Hi-hat otw.",
    47: "Tom średni",
    48: "Tom wysoki",
    49: "Crash",
    50: "Tom wysoki",
    51: "Ride",
    52: "China",
    53: "Ride bell",
    54: "Tamburyn",
    55: "Splash",
    56: "Cowbell",
    57: "Crash 2",
    59: "Ride 2",
}


def drum_name(note: int) -> str | None:
    """GM-owa nazwa nuty perkusyjnej (None, jesli to nie nuta perkusyjna)."""
    return DRUM_NAMES.get(note)


class MidiSourceError(Exception):
    """Plik MIDI nie nadaje sie do odtworzenia."""


# ============================================================
# TEMPO
# ============================================================


@dataclasses.dataclass(frozen=True)
class _TempoSegment:
    tick: int       # tick, od ktorego obowiazuje
    seconds: float  # czas w sekundach na poczatku tego ticku
    tempo: int      # mikrosekundy na cwiercnute


class TempoMap:
    """Zamienia ticki na sekundy, z uwzglednieniem wszystkich set_tempo."""

    def __init__(self, midi_file: mido.MidiFile):
        self.ticks_per_beat = midi_file.ticks_per_beat

        # Zbieramy set_tempo ze WSZYSTKICH trackow (konduktor bywa w 0,
        # ale nie zawsze). Przy tym samym ticku wygrywa ostatni odczytany.
        tempos: dict[int, int] = {}

        for track in midi_file.tracks:
            tick = 0

            for msg in track:
                tick += msg.time

                if msg.type == "set_tempo":
                    tempos[tick] = msg.tempo

        tempos.setdefault(0, DEFAULT_TEMPO)

        self._segments: list[_TempoSegment] = []
        previous_tick = 0
        previous_tempo = tempos[0]
        seconds = 0.0

        for tick, tempo in sorted(tempos.items()):
            seconds += mido.tick2second(
                tick - previous_tick, self.ticks_per_beat, previous_tempo
            )
            self._segments.append(_TempoSegment(tick, seconds, tempo))
            previous_tick = tick
            previous_tempo = tempo

        self._ticks = [segment.tick for segment in self._segments]

    @property
    def change_count(self) -> int:
        """Liczba zmian tempa w utworze (bez domyslnego wpisu)."""
        return max(0, len(self._segments) - 1)

    def seconds_at(self, tick: int) -> float:
        """Tick (bezwzgledny) -> sekundy od poczatku utworu."""
        index = bisect.bisect_right(self._ticks, tick) - 1
        segment = self._segments[max(index, 0)]

        return segment.seconds + mido.tick2second(
            tick - segment.tick, self.ticks_per_beat, segment.tempo
        )


# ============================================================
# DANE
# ============================================================


@dataclasses.dataclass(frozen=True)
class NoteSpan:
    """Pojedyncze brzmienie nuty w czasie (sekundy od poczatku utworu)."""

    start: float
    end: float
    note: int
    velocity: int
    channel: int
    order: int = 0  # kolejnosc zdarzenia w pliku (dla strategii "last")

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclasses.dataclass(frozen=True)
class TrackInfo:
    index: int
    name: str
    note_count: int
    channels: tuple[int, ...]

    @property
    def is_drums(self) -> bool:
        return 9 in self.channels  # kanal 10 wg. nazewnictwa 1-based

    @property
    def label(self) -> str:
        parts = [self.name, f"{self.note_count} nut"]

        if self.channels:
            channels = ", ".join(str(channel + 1) for channel in self.channels)
            parts.append(f"kanal {channels}")

        if self.is_drums:
            parts.append("perkusja")

        return " - ".join(parts)


@dataclasses.dataclass(frozen=True)
class TimedText:
    time: float
    text: str
    kind: str
    track: int


# ============================================================
# REDUKCJA DO MONOFONII
#
# Jedna stacja dyskietek gra tylko jedna nuta naraz. Ponizsze strategie
# zamieniaja dowolna polifonie na sekwencje rozlacznych odcinkow.
# Dodanie nowej strategii = jedna funkcja + wpis w STRATEGIES.
# ============================================================


def _pick_highest(active: list[int], notes: list[NoteSpan]) -> int:
    return max(active, key=lambda index: notes[index].note)


def _pick_lowest(active: list[int], notes: list[NoteSpan]) -> int:
    return min(active, key=lambda index: notes[index].note)


def _pick_last(active: list[int], notes: list[NoteSpan]) -> int:
    """Ostatni NOTE_ON wedlug kolejnosci zdarzen z pliku MIDI.

    Nie wedlug kolejnosci w liscie (ta jest posortowana po wysokosci),
    tylko po numerze zdarzenia. Przy rownych numerach (recznie zbudowane
    nuty) wygrywa zrodlo wlaczone jako ostatnie.
    """
    return max(
        enumerate(active),
        key=lambda item: (notes[item[1]].order, item[0]),
    )[1]


STRATEGIES = {
    "highest": _pick_highest,
    "lowest": _pick_lowest,
    "last": _pick_last,
}

# Ponizej tego uznajemy, ze nuty tylko sie stykaja, a nie nachodza.
_OVERLAP_EPS = 1e-6


def merge_unisons(notes: list[NoteSpan]) -> list[NoteSpan]:
    """Scala nachodzace na siebie brzmienia tej samej wysokosci.

    Stacja dyskietek jest monofoniczna, wiec dwie jednoczesne nuty o tej
    samej wysokosci (np. piano + smyczki) to fizycznie jeden ciagly
    dzwiek. Bez scalenia powstalaby w srodku sztuczna artykulacja
    (STOP + PLAY), choc wysokosc sie nie zmienia.

    Nuty tylko STYKajACE sie (koniec == poczatek) zostaja osobno -
    inaczej zniknelaby powtorka tej samej nuty.
    """
    if not notes:
        return []

    ordered = sorted(notes, key=lambda span: (span.note, span.start, span.end))
    merged: list[NoteSpan] = [ordered[0]]

    for span in ordered[1:]:
        current = merged[-1]

        if span.note == current.note and span.start < current.end - _OVERLAP_EPS:
            if span.end > current.end:
                merged[-1] = dataclasses.replace(current, end=span.end)

            continue

        merged.append(span)

    merged.sort(key=lambda span: (span.start, span.note, span.end))

    return merged


def monophonic(notes: list[NoteSpan], strategy: str = "highest") -> list[NoteSpan]:
    """Zamienia (byc moze polifoniczne) nuty na ciag nut rozlacznych w czasie.

    Odcinek zamyka sie tylko wtedy, gdy zmienia sie wybrana wysokosc albo
    gdy zrodlo tego dzwieku przestalo brzmiec. Dzieki temu dluga nuta
    trzymana nad ruchomym basem zostaje JEDNA nuta, a nie seria
    ponownych atakow (co daloby sztuczne przerwy w harmonogramie).
    """
    if strategy not in STRATEGIES:
        raise MidiSourceError(
            f"nieznana strategia {strategy!r}, dostepne: {', '.join(sorted(STRATEGIES))}"
        )

    notes = merge_unisons(notes)

    if not notes:
        return []

    pick = STRATEGIES[strategy]

    # kind 0 = NOTE_ON (przed NOTE_OFF w tym samym czasie)
    events: list[tuple[float, int, int]] = []

    for index, span in enumerate(notes):
        events.append((span.start, 0, index))
        events.append((span.end, 1, index))

    events.sort(key=lambda event: (event[0], event[1]))

    result: list[NoteSpan] = []
    active: list[int] = []
    active_set: set[int] = set()
    segment_start: float | None = None
    segment_source: int | None = None

    position = 0

    while position < len(events):
        moment = events[position][0]

        # 1. Zastosuj wszystkie zdarzenia w tej samej chwili.
        while position < len(events) and events[position][0] == moment:
            _, kind, index = events[position]

            if kind == 0:
                if index not in active_set:
                    active.append(index)
                    active_set.add(index)
            elif index in active_set:
                active.remove(index)
                active_set.discard(index)

            position += 1

        # 2. Co brzmi od tej chwili?
        source = pick(active, notes) if active else None

        # 3. Czy trzeba zamknac biezacy odcinek?
        if segment_source is not None:
            close = (
                source is None
                or notes[source].note != notes[segment_source].note
                or segment_source not in active_set
            )

            if close:
                if moment > segment_start:
                    previous = notes[segment_source]
                    result.append(
                        NoteSpan(
                            start=segment_start,
                            end=moment,
                            note=previous.note,
                            velocity=previous.velocity,
                            channel=previous.channel,
                            order=previous.order,
                        )
                    )

                segment_start = None
                segment_source = None

        # 4. Ten sam dzwiek gra dalej (ew. inne zrodlo) albo zaczyna sie nowy.
        if source is not None:
            if segment_source is None:
                segment_start = moment

            segment_source = source

    return result


# ============================================================
# PLIK MIDI
# ============================================================


def _channel_tracks(tracks: list[mido.MidiTrack]) -> list[mido.MidiTrack]:
    """Expose mixed tracks as channel tracks without changing absolute ticks.

    Applies to Type 0 and mixed Type 1 tracks. Single-channel tracks stay
    intact. Shared text/meta events occur once, on the first channel track;
    tempo is always read from the original file. Each view retains the
    original end tick, including for dangling notes.
    """
    result = []
    for track in tracks:
        note_channels = {m.channel for m in track
                         if m.type == 'note_on' and m.velocity > 0}
        if len(note_channels) <= 1:
            result.append(track)
            continue
        channels = sorted({m.channel for m in track if hasattr(m, 'channel')})
        for index, channel in enumerate(channels):
            view = mido.MidiTrack()
            name = track.name.strip() or 'MIDI'
            view.append(mido.MetaMessage('track_name', name=f'{name} · ch {channel + 1}'))
            tick = previous_tick = 0
            for message in track:
                tick += message.time
                if message.type in ('track_name', 'end_of_track'):
                    continue
                keep = (message.channel == channel if hasattr(message, 'channel')
                        else index == 0)
                if keep:
                    view.append(message.copy(time=tick - previous_tick))
                    previous_tick = tick
            view.append(mido.MetaMessage('end_of_track', time=tick - previous_tick))
            result.append(view)
    return result


class MidiSource:
    """Plik MIDI + wygodny dostep do trackow i nut."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

        try:
            self._midi = mido.MidiFile(self.path)
        except FileNotFoundError as exc:
            raise MidiSourceError(f"nie ma pliku {self.path}") from exc
        except Exception as exc:  # mido rzuca rozne typy przy uszkodzonym pliku
            raise MidiSourceError(
                f"nie moge wczytac {self.path}: {exc}"
            ) from exc

        if self._midi.ticks_per_beat <= 0:
            raise MidiSourceError(
                f"{self.path}: niepoprawne ticks_per_beat ({self._midi.ticks_per_beat})"
            )

        self.tempo = TempoMap(self._midi)
        self._tracks = _channel_tracks(self._midi.tracks)

        self._notes_cache: dict[int, list[NoteSpan]] = {}
        self._text_cache: tuple[TimedText, ...] | None = None
        self.tracks: list[TrackInfo] = [
            self._describe(index) for index in range(len(self._tracks))
        ]

        if not any(track.note_count for track in self.tracks):
            raise MidiSourceError(f"{self.path}: plik nie zawiera zadnych nut")

    # ---------- informacje ----------

    @property
    def ticks_per_beat(self) -> int:
        return self._midi.ticks_per_beat

    @property
    def file_type(self) -> int:
        return self._midi.type

    @property
    def duration(self) -> float:
        """Dlugosc pliku w sekundach (najdluzszy track, wraz z meta)."""
        return float(self._midi.length)

    def _describe(self, index: int) -> TrackInfo:
        track = self._tracks[index]

        note_count = 0
        channels: list[int] = []
        tick_name = ""

        for msg in track:
            if msg.type == "track_name" and not tick_name:
                tick_name = msg.name.strip()

            if msg.type == "note_on" and msg.velocity > 0:
                note_count += 1

                if msg.channel not in channels:
                    channels.append(msg.channel)

        name = tick_name or ("(bez nazwy)" if index else "Konduktor")

        return TrackInfo(
            index=index,
            name=name,
            note_count=note_count,
            channels=tuple(sorted(channels)),
        )

    def programs(self, track_index: int) -> tuple[int, ...]:
        """GM program changes on the track's note channels (zero based)."""
        channels = set(self.tracks[track_index].channels)
        return tuple(message.program for message in self._tracks[track_index]
                     if message.type == 'program_change' and message.channel in channels)

    def expression_events(self) -> tuple[dict, ...]:
        """Timed expression in seconds; channel scope crosses track boundaries."""
        events = []
        for track, messages in enumerate(self._tracks):
            tick = 0
            for order, message in enumerate(messages):
                tick += message.time
                if message.type not in ('control_change', 'pitchwheel', 'aftertouch', 'polytouch', 'program_change'):
                    continue
                item = {'time': self.tempo.seconds_at(tick), 'track': track,
                        'order': order, 'channel': message.channel, 'kind': message.type}
                if message.type == 'control_change':
                    item.update(control=message.control, value=message.value)
                elif message.type == 'pitchwheel': item['value'] = message.pitch
                elif message.type == 'program_change': item['value'] = message.program
                else:
                    item['value'] = message.value
                    if message.type == 'polytouch': item['note'] = message.note
                events.append(item)
        return tuple(sorted(events, key=lambda e: (e['time'], e['track'], e['order'])))

    def text_events(self) -> tuple[TimedText, ...]:
        """Timed text and karaoke events, including text-only tracks."""
        if self._text_cache is None:
            events = []
            for index, track in enumerate(self._tracks):
                tick = 0
                for message in track:
                    tick += message.time
                    if message.type in ('text', 'lyrics', 'lyric'):
                        events.append(TimedText(self.tempo.seconds_at(tick),
                                                str(message.text), message.type, index))
            self._text_cache = tuple(sorted(events, key=lambda item: (item.time, item.track)))
        return self._text_cache

    # ---------- nuty ----------

    def notes(self, track_index: int) -> list[NoteSpan]:
        """Wszystkie nuty danego tracku, posortowane po czasie startu."""
        if track_index not in self._notes_cache:
            self._notes_cache[track_index] = self._extract(track_index)

        return self._notes_cache[track_index]

    def _extract(self, track_index: int) -> list[NoteSpan]:
        if not 0 <= track_index < len(self._tracks):
            raise MidiSourceError(
                f"track {track_index} nie istnieje "
                f"(plik ma {len(self._tracks)} trackow)"
            )

        tempo = self.tempo
        track = self._tracks[track_index]

        notes: list[NoteSpan] = []
        active: dict[tuple[int, int], tuple[float, int, int]] = {}

        tick = 0
        order = 0

        for msg in track:
            tick += msg.time

            if msg.type == "note_on" and msg.velocity > 0:
                moment = tempo.seconds_at(tick)
                key = (msg.channel, msg.note)

                # Ta sama nuta juz brzmi - zamykamy poprzednia.
                if key in active:
                    start, velocity, start_order = active.pop(key)
                    notes.append(
                        NoteSpan(
                            start, moment, msg.note, velocity, msg.channel, start_order
                        )
                    )

                active[key] = (moment, msg.velocity, order)
                order += 1

            elif msg.type in ("note_off", "note_on"):
                moment = tempo.seconds_at(tick)
                key = (msg.channel, msg.note)

                if key in active:
                    start, velocity, start_order = active.pop(key)
                    notes.append(
                        NoteSpan(
                            start, moment, msg.note, velocity, msg.channel, start_order
                        )
                    )

        # Nuty bez NOTE_OFF konczymy na koncu tracku (nie na ostatnim
        # zdarzeniu nutowym) - inaczej taka nuta mialaby dlugosc 0.
        # Gdy track konczy sie dokladnie na NOTE_ON (zero informacji
        # o dlugosci), przyjmujemy bezpieczne minimum.
        track_end = tempo.seconds_at(tick)

        for (channel, note), (start, velocity, start_order) in active.items():
            end = track_end if track_end > start else start + DANGLING_NOTE_S

            notes.append(
                NoteSpan(start, end, note, velocity, channel, start_order)
            )

        notes.sort(key=lambda span: (span.start, span.note, span.end))

        return notes

    def selected_notes(self, track_index: int, strategy: str = "highest") -> list[NoteSpan]:
        """Nuty tracku zredukowane do jednej nuty naraz."""
        return monophonic(self.notes(track_index), strategy)
