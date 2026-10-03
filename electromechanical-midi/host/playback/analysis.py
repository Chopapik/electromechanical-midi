"""Analiza muzyczna pliku MIDI pod katem auto-aranzacji.

Ten modul nie decyduje o zadnym urzadzeniu. Odpowiada tylko na pytania:
  * ktory track najbardziej przypomina linie lead / wokal,
  * ktory niesie bas,
  * jaka role ma kazda nuta.

Nazwy trackow sa WYLACZNIE slaba podpowiedzia - nigdy wymogiem.
"""
from __future__ import annotations

import dataclasses
import statistics

from midi_source import MidiSource, NoteSpan

# Role muzyczne nut. Allocator tlumaczy je na priorytety i preferencje sprzetu.
LEAD = 'lead'
BASS = 'bass'
HARMONY = 'harmony'
PERCUSSION = 'percussion'

# Slabe wskazowki z nazw trackow (waga ponizej).
_NAME_HINTS = {
    'vocal': 1.0, 'vox': 1.0, 'voice': 1.0, 'wokal': 1.0, 'spiew': 1.0,
    'lead': 1.0, 'melod': 0.8, 'solo': 0.8, 'sing': 0.8, 'top': 0.5,
    'gitara': 0.3, 'guitar': 0.3, 'sax': 0.4, 'violin': 0.4, 'skrzyp': 0.4,
}
_BASS_HINTS = {'bass': 1.0, 'bas': 1.0, 'kontrabas': 1.0, 'sub': 0.6,
               'kick': 0.5, 'stopa': 0.5}


@dataclasses.dataclass(frozen=True)
class TrackProfile:
    """Cechy jednego tracku - wejscie dla detekcji lead/bas."""

    index: int
    name: str
    note_count: int
    is_drums: bool
    channels: tuple[int, ...]
    mean_pitch: float
    min_pitch: int
    max_pitch: int
    mean_duration: float
    mean_velocity: float
    polyphony: float          # srednia liczba jednoczesnych nut
    overlap_ratio: float      # jaka czesc nut nachodzi na inna nute tracku
    step_ratio: float         # jaka czesc interwalow to <= 2 semitony
    density: float            # nuty na sekunde
    name_hint: float

    @property
    def monophony(self) -> float:
        return max(0.0, 1.0 - self.overlap_ratio)

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class MidiAnalysis:
    tracks: list[TrackProfile]
    lead_track: int | None
    lead_confidence: float
    bass_track: int | None
    bass_confidence: float
    roles: dict[str, str]                 # note id "track:order" -> rola
    lead_notes: tuple[str, ...] = ()      # nuty wybrane jako linia lead

    def as_dict(self) -> dict:
        return {
            'tracks': [track.as_dict() for track in self.tracks],
            'leadTrack': self.lead_track,
            'leadConfidence': round(self.lead_confidence, 3),
            'bassTrack': self.bass_track,
            'bassConfidence': round(self.bass_confidence, 3),
            'leadNotes': len(self.lead_notes),
        }


def _hint(name: str, table: dict[str, float]) -> float:
    lowered = name.lower()

    return max((weight for key, weight in table.items() if key in lowered), default=0.0)


def _overlap_ratio(notes: list[NoteSpan]) -> float:
    """Jaka czesc nut startuje, gdy poprzednia jeszcze brzmi (monofonia)."""
    if len(notes) < 2:
        return 0.0

    ordered = sorted(notes, key=lambda span: (span.start, span.note))
    overlapping = 0
    previous_end = ordered[0].end

    for span in ordered[1:]:
        if span.start < previous_end - 1e-6:
            overlapping += 1

        previous_end = max(previous_end, span.end)

    return overlapping / len(ordered)


def _polyphony(notes: list[NoteSpan]) -> float:
    """Srednia liczba jednoczesnych nut (bez podzialu na wysciaglenie)."""
    if not notes:
        return 0.0

    moments = sorted({round(span.start, 6) for span in notes})
    total = 0

    for moment in moments:
        active = sum(1 for span in notes if span.start <= moment < span.end - 1e-9)
        total += max(active, 1)

    return total / len(moments)


def _step_ratio(notes: list[NoteSpan]) -> float:
    """Udzial malych interwalow - melodia chodzi po stopniach, akord skacze."""
    ordered = sorted(notes, key=lambda span: (span.start, span.note))

    if len(ordered) < 2:
        return 0.0

    steps = 0

    for previous, current in zip(ordered, ordered[1:]):
        if abs(current.note - previous.note) <= 2:
            steps += 1

    return steps / (len(ordered) - 1)


def _profile(source: MidiSource, index: int) -> TrackProfile:
    track = source.tracks[index]
    notes = source.notes(index)

    if not notes:
        return TrackProfile(index, track.name, 0, track.is_drums, track.channels,
                            0.0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                            _hint(track.name, _NAME_HINTS))

    pitches = [span.note for span in notes]
    span_seconds = max(1e-6, max(span.end for span in notes) - min(span.start for span in notes))

    return TrackProfile(
        index=index,
        name=track.name,
        note_count=len(notes),
        is_drums=track.is_drums,
        channels=track.channels,
        mean_pitch=statistics.fmean(pitches),
        min_pitch=min(pitches),
        max_pitch=max(pitches),
        mean_duration=statistics.fmean([span.duration for span in notes]),
        mean_velocity=statistics.fmean([span.velocity for span in notes]),
        polyphony=_polyphony(notes),
        overlap_ratio=_overlap_ratio(notes),
        step_ratio=_step_ratio(notes),
        density=len(notes) / span_seconds,
        name_hint=_hint(track.name, _NAME_HINTS),
    )


def _normalise(values: list[float]) -> list[float]:
    if not values:
        return []

    low, high = min(values), max(values)

    if high - low < 1e-9:
        return [0.5] * len(values)

    return [(value - low) / (high - low) for value in values]


def _lead_scores(profiles: list[TrackProfile]) -> list[float]:
    """Heurystyka leada: monofonia, wysokie rejestry, dlugie i głośne nuty,
    ciaglosc melodii. Nazwa tracku to tylko maly dodatek."""
    candidates = [p for p in profiles if not p.is_drums and p.note_count >= 4]

    if not candidates:
        return []

    pitch_rank = _normalise([p.mean_pitch for p in candidates])
    duration_rank = _normalise([p.mean_duration for p in candidates])
    velocity_rank = _normalise([p.mean_velocity for p in candidates])
    density_rank = _normalise([p.density for p in candidates])

    scores = []

    for profile, pitch, duration, velocity, density in zip(
            candidates, pitch_rank, duration_rank, velocity_rank, density_rank):
        score = (
            0.30 * profile.monophony
            + 0.18 * pitch
            + 0.14 * duration
            + 0.08 * velocity
            + 0.15 * profile.step_ratio
            + 0.05 * density
            + 0.10 * profile.name_hint
        )
        scores.append(score)

    return scores


def _pick_lead(profiles: list[TrackProfile]) -> tuple[int | None, float]:
    candidates = [p for p in profiles if not p.is_drums and p.note_count >= 20]

    if not candidates:
        return None, 0.0

    scores = _lead_scores(profiles)
    scored = [p for p in profiles if not p.is_drums and p.note_count >= 4]
    ranked = sorted(zip(scored, scores), key=lambda item: (-item[1], item[0].index))

    if not ranked:
        return None, 0.0

    winner, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = best - second

    # Zbyt plasko = brak wyraznego leada. Lepiej nie chronic na sile.
    if best < 0.42 or margin < 0.03:
        return winner.index, round(min(best, 0.5), 3)

    confidence = min(1.0, best * (0.6 + 0.8 * min(margin, 0.5) / 0.5))

    return winner.index, round(confidence, 3)


def _pick_bass(profiles: list[TrackProfile]) -> tuple[int | None, float]:
    candidates = [p for p in profiles if not p.is_drums and p.note_count >= 8]

    if not candidates:
        return None, 0.0

    pitch_rank = _normalise([-p.mean_pitch for p in candidates])
    scored = []

    for profile, low in zip(candidates, pitch_rank):
        score = (
            0.50 * low
            + 0.25 * profile.monophony
            + 0.15 * _hint(profile.name, _BASS_HINTS)
            + 0.10 * min(profile.mean_duration / 0.5, 1.0)
        )
        scored.append((score, profile))

    scored.sort(key=lambda item: (-item[0], item[1].index))
    best, winner = scored[0]

    if best < 0.45:
        return None, 0.0

    return winner.index, round(min(best, 1.0), 3)


def _lead_line(source: MidiSource, profile: TrackProfile) -> set[str]:
    """Ktore nuty leadowego tracku naprawde niosa melodie.

    Przy monofonicznym tracku - wszystkie. Przy polifonicznym (np. pianie)
    melodia to gorny glos, wiec bierzemy najwyzsza nuta z kazdego uderzenia.
    """
    notes = source.notes(profile.index)

    if profile.overlap_ratio <= 0.15:
        return {f'{profile.index}:{span.order}' for span in notes}

    groups: dict[float, NoteSpan] = {}

    for span in notes:
        key = round(span.start, 4)

        if key not in groups or span.note > groups[key].note:
            groups[key] = span

    return {f'{profile.index}:{span.order}' for span in groups.values()}


def analyze(source: MidiSource, *, lead_track: int | None = None) -> MidiAnalysis:
    """Profiluje tracki i wyznacza role nut. Czysta funkcja - brak stanu."""
    profiles = [_profile(source, index) for index in range(len(source.tracks))]

    detected_lead, lead_confidence = _pick_lead(profiles)

    if lead_track is not None and 0 <= lead_track < len(source.tracks):
        detected_lead, lead_confidence = lead_track, 1.0

    bass_track, bass_confidence = _pick_bass(profiles)
    lead_notes: set[str] = set()

    if detected_lead is not None:
        lead_notes = _lead_line(source, profiles[detected_lead])

    roles: dict[str, str] = {}

    for profile in profiles:
        if profile.note_count == 0:
            continue

        for span in source.notes(profile.index):
            note_id = f'{profile.index}:{span.order}'

            if profile.is_drums:
                roles[note_id] = PERCUSSION
            elif detected_lead == profile.index and note_id in lead_notes:
                roles[note_id] = LEAD
            elif bass_track == profile.index:
                roles[note_id] = BASS
            else:
                roles[note_id] = HARMONY

    return MidiAnalysis(
        tracks=profiles,
        lead_track=detected_lead,
        lead_confidence=lead_confidence,
        bass_track=bass_track,
        bass_confidence=bass_confidence,
        roles=roles,
        lead_notes=tuple(sorted(lead_notes)),
    )
