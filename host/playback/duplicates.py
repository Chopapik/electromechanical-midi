"""Detekcja zdublowanych trackow (double-tracking) i normalizacja zrodla.

Realne pliki MIDI czesto zawieraja te sama partie zagrana dwa razy: ``Guitar 1``
i ``Guitar Dub``, stereo-duble, warstwy z przesunieciem kilku-kilkudziesieciu ms.
Dla syntezatora to normalna technika produkcyjna. Dla monofonicznej orkiestry
mechanicznej to FALSZYWA POLIFONIA: dwa glosy walcza o te same FDD, choc
muzycznie to jedna partia.

Ten modul zamienia surowe tracki na **partie logiczne**: duble sa wykrywane,
grupowane i reprezentowane przez jeden track z zachowaniem pelnej metadanej
zrodlowej (skad pochodzily, jakie byly offsety, jaka confidence).

    MidiSource -> detect() -> DuplicateReport
               -> normalize() -> NormalizedSource (partie logiczne)
               -> analysis / allocator

Detekcja NIE opiera sie na nazwach ani numerach trackow - liczy sie wylacznie
struktura nut: sekwencja pitchy, timing, dlugosci i velocity. Nazwa tracku
sluzy tylko do czytelnosci raportu.

Zasada bezpieczenstwa: wolimy NIE polaczyc prawdziwego dubla niz zle skleic
dwie rozne partie muzyczne.
"""
from __future__ import annotations

import bisect
import dataclasses
import statistics

from midi_source import MidiSource, NoteSpan, TrackInfo

# --- progi detekcji -------------------------------------------------------
MIN_NOTES = 8                 # krotszych trackow nie porownujemy
COUNT_RATIO_MIN = 0.60        # stosunek liczby nut - wstepny odsiew
OFFSET_SEARCH_S = 0.250       # maksymalny przesun miedzy dublem a oryginalem
OFFSET_BIN_S = 0.001          # ziarno histogramu offsetu
MATCH_WINDOW_S = 0.040        # okno dopasowania nuty po uwzglednieniu offsetu

EXACT_RATIO = 0.99            # udzial dopasowanych nut (wzgledem wiekszego tracku)
EXACT_MAD_S = 0.008           # stabilnosc offsetu
EXACT_DURATION = 0.90
EXACT_VELOCITY = 0.90

NEAR_RATIO = 0.90
NEAR_MAD_S = 0.030
NEAR_DURATION = 0.75
NEAR_VELOCITY = 0.55

# Nazwy trackow to WYLACZNIE slaba podpowiedz - nigdy warunek detekcji.
_WEAK_NAME_HINTS = ('dub', 'dbl', 'double', 'copy', 'layer', 'stack', 'l', 'r')

EXACT = 'EXACT_DUPLICATE'
NEAR = 'NEAR_DUPLICATE'
DIFFERENT = 'DIFFERENT'


@dataclasses.dataclass(frozen=True)
class TrackSimilarity:
    """Podobienstwo dwoch trackow - jawne metryki, bez magicznych stalych."""

    track_a: int
    track_b: int
    notes_a: int
    notes_b: int
    matched: int
    matching_ratio: float          # matched / max(notes_a, notes_b)
    pitch_agreement: float         # matched / min(notes_a, notes_b)
    peak_support: int              # ile par poparlo najczestszy offset
    median_offset_s: float
    offset_mad_s: float
    duration_similarity: float
    velocity_similarity: float
    count_ratio: float
    confidence: float
    verdict: str

    @property
    def duplicate(self) -> bool:
        return self.verdict != DIFFERENT

    def as_dict(self) -> dict:
        return {
            'trackA': self.track_a, 'trackB': self.track_b,
            'notesA': self.notes_a, 'notesB': self.notes_b,
            'matched': self.matched,
            'matchingRatio': round(self.matching_ratio, 4),
            'pitchAgreement': round(self.pitch_agreement, 4),
            'peakSupport': self.peak_support,
            'medianOffsetMs': round(self.median_offset_s * 1000, 2),
            'offsetMadMs': round(self.offset_mad_s * 1000, 3),
            'durationSimilarity': round(self.duration_similarity, 4),
            'velocitySimilarity': round(self.velocity_similarity, 4),
            'countRatio': round(self.count_ratio, 4),
            'confidence': round(self.confidence, 4),
            'verdict': self.verdict,
        }


@dataclasses.dataclass(frozen=True)
class DuplicateGroup:
    """Partia logiczna: jeden primary + jego duble."""

    group_id: str
    primary: int
    tracks: tuple[int, ...]
    duplicates: tuple[int, ...]
    confidence: float
    median_offsets: dict[int, float]        # track -> offset wzgledem primary [s]
    verdicts: dict[int, str]
    names: dict[int, str]

    @property
    def events_primary(self) -> int:
        return self._counts.get(self.primary, 0)

    _counts: dict[int, int] = dataclasses.field(default_factory=dict, repr=False)

    def as_dict(self) -> dict:
        return {
            'groupId': self.group_id,
            'primary': self.primary,
            'tracks': list(self.tracks),
            'duplicates': list(self.duplicates),
            'confidence': round(self.confidence, 4),
            'names': {str(k): v for k, v in self.names.items()},
            'medianOffsetsMs': {str(k): round(v * 1000, 2)
                                for k, v in self.median_offsets.items()},
            'verdicts': {str(k): v for k, v in self.verdicts.items()},
        }


@dataclasses.dataclass
class DuplicateReport:
    """Wynik detekcji: grupy + pelne metryki par (do raportu i testow)."""

    groups: list[DuplicateGroup]
    pairs: list[TrackSimilarity]
    candidates: int
    raw_tonal_events: int
    logical_tonal_events: int

    @property
    def collapsed_tracks(self) -> int:
        return sum(len(group.duplicates) for group in self.groups)

    @property
    def events_removed(self) -> int:
        return self.raw_tonal_events - self.logical_tonal_events

    def group_of(self, track: int) -> DuplicateGroup | None:
        for group in self.groups:
            if track in group.tracks:
                return group

        return None

    def as_dict(self) -> dict:
        return {
            'groups': [group.as_dict() for group in self.groups],
            'pairs': [pair.as_dict() for pair in self.pairs],
            'candidatePairs': self.candidates,
            'summary': {
                'groupsFound': len(self.groups),
                'tracksCollapsed': self.collapsed_tracks,
                'rawTonalEvents': self.raw_tonal_events,
                'logicalTonalEvents': self.logical_tonal_events,
                'estimatedDuplicateEventsRemoved': self.events_removed,
            },
        }


def _pitch_index(notes: list[NoteSpan]) -> dict[int, list[tuple[float, int]]]:
    index: dict[int, list[tuple[float, int]]] = {}

    for position, span in enumerate(notes):
        index.setdefault(span.note, []).append((span.start, position))

    for entries in index.values():
        entries.sort()

    return index


def _estimate_offset(notes_a: list[NoteSpan], notes_b: list[NoteSpan],
                     index_b: dict[int, list[tuple[float, int]]]) -> tuple[float, int]:
    """Najczestszy staly przesun miedzy trackami + ile par go popiera.

    Histogram, nie srednia: kilka brakujacych nut albo ornament
    nie przesuwa wyniku, a prawdziwy dub tworzy waski, wysoki szczyt.
    """
    sample = notes_a if len(notes_a) <= 600 else notes_a[:600]
    histogram: dict[int, int] = {}

    for span in sample:
        for start, _ in index_b.get(span.note, ()):
            delta = start - span.start

            if abs(delta) <= OFFSET_SEARCH_S:
                bucket = round(delta / OFFSET_BIN_S)
                histogram[bucket] = histogram.get(bucket, 0) + 1

    if not histogram:
        return 0.0, 0

    # Remis rozstrzygamy na korzysc mniejszego |offsetu|, potem mniejszego offsetu.
    best = min(histogram.items(), key=lambda item: (-item[1], abs(item[0]), item[0]))
    peak_s = best[0] * OFFSET_BIN_S
    near = []

    for span in notes_a:
        for start, _ in index_b.get(span.note, ()):
            delta = start - span.start

            if abs(delta - peak_s) <= MATCH_WINDOW_S:
                near.append(delta)

    if not near:
        return peak_s, best[1]

    return statistics.median(near), best[1]


def _match(notes_a: list[NoteSpan], notes_b: list[NoteSpan],
           index_b: dict[int, list[tuple[float, int]]],
           offset: float, window: float) -> list[tuple[NoteSpan, NoteSpan]]:
    """Dopasowuje nuty A do B po pitchu i czasie (offset + okno). Zachlanne,
    deterministyczne, kazda nuta B uzyta najwyzej raz."""
    used: set[int] = set()
    pairs = []

    for span in notes_a:
        target = span.start + offset
        candidates = index_b.get(span.note)

        if not candidates:
            continue

        left = bisect.bisect_left(candidates, (target - window, -1))
        best = None

        for position in range(left, len(candidates)):
            start, index = candidates[position]

            if start > target + window:
                break

            if index in used:
                continue

            distance = abs(start - target)

            if best is None or distance < best[0]:
                best = (distance, index)

        if best is not None:
            used.add(best[1])
            pairs.append((span, notes_b[best[1]]))

    return pairs


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def compare_tracks(notes_a: list[NoteSpan], notes_b: list[NoteSpan],
                   track_a: int = -1, track_b: int = -1) -> TrackSimilarity:
    """Czysta funkcja: dwa zbiory nut -> metryki podobienstwa + werdykt."""
    notes_a = sorted(notes_a, key=lambda span: (span.start, span.note))
    notes_b = sorted(notes_b, key=lambda span: (span.start, span.note))
    count = min(len(notes_a), len(notes_b))
    longest = max(len(notes_a), len(notes_b))

    base = TrackSimilarity(
        track_a=track_a, track_b=track_b, notes_a=len(notes_a), notes_b=len(notes_b),
        matched=0, matching_ratio=0.0, pitch_agreement=0.0, peak_support=0,
        median_offset_s=0.0, offset_mad_s=0.0, duration_similarity=0.0,
        velocity_similarity=0.0, count_ratio=(count / longest if longest else 0.0),
        confidence=0.0, verdict=DIFFERENT)

    if count < MIN_NOTES or base.count_ratio < COUNT_RATIO_MIN:
        return base

    index_b = _pitch_index(notes_b)
    offset, support = _estimate_offset(notes_a, notes_b, index_b)
    pairs = _match(notes_a, notes_b, index_b, offset, MATCH_WINDOW_S)

    if not pairs:
        return dataclasses.replace(base, peak_support=support)

    offsets = [b.start - a.start for a, b in pairs]
    median_offset = statistics.median(offsets)
    mad = statistics.median([abs(value - median_offset) for value in offsets])

    def ratio(left: float, right: float) -> float:
        biggest = max(left, right)

        return left / biggest if biggest > 0 else 1.0

    duration_similarity = statistics.median([
        ratio(min(a.duration, b.duration), max(a.duration, b.duration))
        for a, b in pairs])
    velocity_similarity = _clamp(
        1.0 - statistics.median([abs(a.velocity - b.velocity) for a, b in pairs]) / 127.0)
    matching_ratio = len(pairs) / longest
    pitch_agreement = len(pairs) / count

    timing = _clamp(1.0 - mad / NEAR_MAD_S)
    confidence = _clamp(
        0.55 * matching_ratio
        + 0.20 * timing
        + 0.15 * duration_similarity
        + 0.10 * velocity_similarity)

    verdict = DIFFERENT

    if (matching_ratio >= EXACT_RATIO and mad <= EXACT_MAD_S
            and duration_similarity >= EXACT_DURATION
            and velocity_similarity >= EXACT_VELOCITY):
        verdict = EXACT
    elif (matching_ratio >= NEAR_RATIO and mad <= NEAR_MAD_S
            and duration_similarity >= NEAR_DURATION
            and velocity_similarity >= NEAR_VELOCITY):
        verdict = NEAR

    return TrackSimilarity(
        track_a=track_a, track_b=track_b, notes_a=len(notes_a), notes_b=len(notes_b),
        matched=len(pairs), matching_ratio=matching_ratio,
        pitch_agreement=pitch_agreement, peak_support=support,
        median_offset_s=median_offset, offset_mad_s=mad,
        duration_similarity=duration_similarity,
        velocity_similarity=velocity_similarity, count_ratio=base.count_ratio,
        confidence=confidence, verdict=verdict)


def _candidates(source: MidiSource) -> list[TrackInfo]:
    """Tylko tonalne tracki. Perkusji nie deduplikujemy (v1)."""
    return [track for track in source.tracks
            if not track.is_drums and track.note_count >= MIN_NOTES]


def detect(source: MidiSource) -> DuplicateReport:
    """Znajduje grupy zdublowanych trackow. Deterministyczne, bez nazw."""
    candidates = _candidates(source)
    notes = {track.index: source.notes(track.index) for track in candidates}
    pairs: dict[tuple[int, int], TrackSimilarity] = {}

    for position, track_a in enumerate(candidates):
        for track_b in candidates[position + 1:]:
            key = (min(track_a.index, track_b.index), max(track_a.index, track_b.index))
            similarity = compare_tracks(notes[track_a.index], notes[track_b.index], *key)

            if similarity.duplicate:
                pairs[key] = similarity

    # Connected components po parach duplikatow.
    parent: dict[int, int] = {track.index: track.index for track in candidates}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]

        return node

    for left, right in pairs:
        root_left, root_right = find(left), find(right)

        if root_left != root_right:
            parent[max(root_left, root_right)] = min(root_left, root_right)

    components: dict[int, list[int]] = {}

    for track in candidates:
        components.setdefault(find(track.index), []).append(track.index)

    groups: list[DuplicateGroup] = []
    by_index = {track.index: track for track in candidates}

    for members in sorted(components.values()):
        if len(members) < 2:
            continue

        # Primary: wieksze pokrycie, potem wczesniejszy indeks (deterministycznie).
        primary = min(members, key=lambda index: (-by_index[index].note_count, index))

        # Bezpieczenstwo: kazdy czlonek musi pasowac do PRIMARY, nie tylko do
        # sasiada w grafie. Inaczej lancuch A~B~C sklejalby A z C.
        confirmed = [primary]
        offsets = {primary: 0.0}
        verdicts = {primary: EXACT}
        confidences = []

        for member in sorted(members):
            if member == primary:
                continue

            key = (min(primary, member), max(primary, member))
            similarity = pairs.get(key)

            if similarity is None:
                continue

            confirmed.append(member)
            offsets[member] = similarity.median_offset_s
            verdicts[member] = similarity.verdict
            confidences.append(similarity.confidence)

        if len(confirmed) < 2:
            continue

        groups.append(DuplicateGroup(
            group_id=f'part-{primary}',
            primary=primary,
            tracks=tuple(sorted(confirmed)),
            duplicates=tuple(sorted(set(confirmed) - {primary})),
            confidence=min(confidences),
            median_offsets=offsets,
            verdicts=verdicts,
            names={index: by_index[index].name for index in confirmed},
        ))

    return DuplicateReport(groups=groups, pairs=list(pairs.values()),
                           candidates=len(candidates), raw_tonal_events=0,
                           logical_tonal_events=0)


@dataclasses.dataclass(frozen=True)
class LogicalTrack:
    """Partia logiczna widziana przez analize i allocator."""

    index: int                       # indeks tracku-primary (zgodny z surowym)
    name: str
    note_count: int
    channels: tuple[int, ...]
    is_drums: bool
    source_tracks: tuple[int, ...]
    group_id: str | None = None
    duplicate_confidence: float | None = None
    median_offsets: dict[int, float] = dataclasses.field(default_factory=dict)

    @property
    def label(self) -> str:
        if not self.source_tracks or len(self.source_tracks) == 1:
            return f'{self.name} - {self.note_count} nut'

        sources = ', '.join(str(index) for index in self.source_tracks)

        return f'{self.name} - {self.note_count} nut (partia z trackow {sources})'


class NormalizedSource:
    """Zrodlo po normalizacji: partie logiczne zamiast surowych trackow.

    Udostepnia te sama minimalna powierzchnie co ``MidiSource``
    (``tracks`` / ``notes(index)`` / ``path``), wiec analysis i allocator
    nie musza wiedziec, ze cokolwiek zostalo sklejone.
    """

    def __init__(self, source: MidiSource, report: DuplicateReport,
                 tracks: list[LogicalTrack], notes: dict[int, list[NoteSpan]]):
        self.source = source
        self.path = source.path
        self.duration = source.duration
        self.duplicate_report = report
        self.tracks = tracks
        self._notes = notes
        self.raw_tonal_events = report.raw_tonal_events
        self.logical_tonal_events = report.logical_tonal_events

    def notes(self, track_index: int) -> list[NoteSpan]:
        return self._notes[track_index]

    def tonal_demand(self) -> tuple[float, float]:
        """(surowy, logiczny) czas brzmienia trackow tonalnych w sekundach."""
        raw = 0.0

        for track in self.source.tracks:
            if track.is_drums:
                continue

            raw += sum(span.duration for span in self.source.notes(track.index))

        logical = sum(span.duration for track in self.tracks
                      if not track.is_drums for span in self._notes[track.index])

        return raw, logical

    def as_dict(self) -> dict:
        return {
            'tracks': [{'index': track.index, 'name': track.name,
                        'sourceTracks': list(track.source_tracks),
                        'groupId': track.group_id,
                        'duplicateConfidence': track.duplicate_confidence}
                       for track in self.tracks],
            'duplicates': self.duplicate_report.as_dict(),
        }


def normalize(source: MidiSource, report: DuplicateReport | None = None) -> NormalizedSource:
    """Surowe tracki -> partie logiczne. Duble znikaja, metadane zostaja."""
    report = report or detect(source)
    grouped: dict[int, DuplicateGroup] = {}

    for group in report.groups:
        for track in group.tracks:
            grouped[track] = group

    tracks: list[LogicalTrack] = []
    notes: dict[int, list[NoteSpan]] = {}
    raw_tonal = 0

    for track in source.tracks:
        if not track.is_drums:
            raw_tonal += len(source.notes(track.index))

        group = grouped.get(track.index)

        if group is not None and track.index != group.primary:
            continue                       # dub nie jest osobnym glosem

        if group is None:
            tracks.append(LogicalTrack(
                index=track.index, name=track.name, note_count=track.note_count,
                channels=track.channels, is_drums=track.is_drums,
                source_tracks=(track.index,)))
        else:
            tracks.append(LogicalTrack(
                index=track.index, name=track.name, note_count=track.note_count,
                channels=track.channels, is_drums=track.is_drums,
                source_tracks=group.tracks, group_id=group.group_id,
                duplicate_confidence=group.confidence,
                median_offsets=dict(group.median_offsets)))

        notes[track.index] = source.notes(track.index)

    logical_tonal = sum(len(notes[track.index]) for track in tracks if not track.is_drums)

    report.raw_tonal_events = raw_tonal
    report.logical_tonal_events = logical_tonal

    return NormalizedSource(source, report, tracks, notes)
