"""Explainable, deterministic classification of MIDI track functions.

Scores are independent evidence weights, not probabilities. A name is a strong
hint; GM, timed lyrics and musical behaviour support or challenge it. Only a
high-confidence VOCAL can override the existing heuristic lead selection.
"""
from __future__ import annotations

import bisect
import dataclasses
import re
from collections import Counter

ROLES = ('VOCAL', 'BACKING_VOCAL', 'BASS', 'GUITAR', 'KEYS', 'STRINGS',
         'PAD_SYNTH', 'PERCUSSION', 'OTHER')
ROLE_THRESHOLD = .55
VOCAL_LEAD_THRESHOLD = .75
VOCAL_MARGIN = .12

GM_FAMILIES = ('Piano', 'Chromatic Percussion', 'Organ', 'Guitar', 'Bass',
               'Strings', 'Ensemble', 'Brass', 'Reed', 'Pipe', 'Synth Lead',
               'Synth Pad', 'Synth Effects', 'Ethnic', 'Percussive',
               'Sound Effects')
FAMILY_ROLE = {
    'Piano': 'KEYS', 'Chromatic Percussion': 'KEYS', 'Organ': 'KEYS',
    'Guitar': 'GUITAR', 'Bass': 'BASS', 'Strings': 'STRINGS',
    'Ensemble': 'STRINGS', 'Synth Lead': 'PAD_SYNTH',
    'Synth Pad': 'PAD_SYNTH', 'Synth Effects': 'PAD_SYNTH',
    'Percussive': 'PERCUSSION',
}

NAME_PATTERNS = {
    'VOCAL': r'\b(vocals?|vox|voice|voc|voz|singer|wokal|spiew|śpiew)\b',
    'BASS': r'\b(bass|bas|kontrabas|subbass)\b',
    'GUITAR': r'\b(guitars?|guit|gtr|gitara)\b',
    'KEYS': r'\b(piano|organ|keyboard|keys|rhodes|clav)\b',
    'STRINGS': r'\b(strings?|violin|viola|cello|orchestra|skrzypce)\b',
    'PAD_SYNTH': r'\b(pad|synth|atmosphere|fx)\b',
    'PERCUSSION': r'\b(drums?|percussion|drum\s+kit|toms?|bębny)\b',
}
BACKING_PATTERN = re.compile(
    r'\b(backing|background|bg|add|harmony|choir|synth)\s+'
    r'(vocals?|vox|voice|voc|voz)\b|\bchoir\b', re.I)


def gm_family(program: int) -> str:
    return GM_FAMILIES[program // 8] if 0 <= program < 128 else 'Unknown'


def _lyric_text(value: str) -> bool:
    value = value.strip()
    return (bool(value) and not value.startswith(('@', '['))
            and any(character.isalpha() for character in value)
            and len(value) <= 48)


def _lyric_alignment(notes, times: list[float]) -> float:
    if len(times) < 8 or len(notes) < 8:
        return 0.0
    aligned = 0
    for note in notes:
        index = bisect.bisect_left(times, note.start)
        if any(abs(times[position] - note.start) <= .12
               for position in (index - 1, index) if 0 <= position < len(times)):
            aligned += 1
    return round(aligned / len(notes), 3)


@dataclasses.dataclass(frozen=True)
class TrackClassification:
    index: int
    name: str
    note_count: int
    final_role: str
    confidence: float
    role_scores: dict[str, float]
    evidence: tuple[str, ...]
    gm_family: str | None
    monophonic: bool
    lyric_alignment: float

    def as_dict(self) -> dict:
        return {
            'index': self.index, 'name': self.name, 'noteCount': self.note_count,
            'finalRole': self.final_role, 'confidence': self.confidence,
            'roleScores': self.role_scores, 'evidence': list(self.evidence),
            'gmFamily': self.gm_family, 'monophonic': self.monophonic,
            'lyricAlignment': self.lyric_alignment,
        }


def classify(source, profiles) -> tuple[TrackClassification, ...]:
    """Classify logical tracks; metadata is read from their original MIDI tracks."""
    raw = getattr(source, 'source', source)
    lyric_times = sorted(event.time for event in raw.text_events()
                         if _lyric_text(event.text))
    by_index = {track.index: track for track in source.tracks}
    results = []

    for profile in profiles:
        track = by_index[profile.index]
        original_indices = getattr(track, 'source_tracks', (track.index,))
        programs = [program for index in original_indices for program in raw.programs(index)]
        family = gm_family(Counter(programs).most_common(1)[0][0]) if programs else None
        notes = source.notes(profile.index)
        alignment = _lyric_alignment(notes, lyric_times)
        scores = {role: 0.0 for role in ROLES}
        scores['OTHER'] = .25
        reasons: dict[str, list[str]] = {role: [] for role in ROLES}

        def add(role: str, amount: float, reason: str) -> None:
            scores[role] += amount
            reasons[role].append(reason)

        name = profile.name.casefold()
        backing = BACKING_PATTERN.search(name)
        if backing:
            add('BACKING_VOCAL', .78, f'name: {backing.group(0)}')
        else:
            for role, pattern in NAME_PATTERNS.items():
                match = re.search(pattern, name, re.I)
                if match:
                    add(role, .72 if role in ('VOCAL', 'BASS') else .68,
                        f'name: {match.group(0)}')
        if re.search(r'\b(melody|melodia|solo)\b', name) and not backing:
            add('VOCAL', .08, 'name: melody/solo')

        if family:
            mapped = FAMILY_ROLE.get(family)
            if mapped:
                add(mapped, .45 if mapped == 'BASS' else .18, f'GM family: {family}')
            if family == 'Bass' and profile.mean_pitch <= 55:
                scores['VOCAL'] = max(0.0, scores['VOCAL'] - .35)
                reasons['VOCAL'].append('GM Bass and low register contradict vocal')

        if profile.is_drums:
            add('PERCUSSION', 1.0, 'MIDI drum channel')
        elif notes:
            if profile.monophony >= .8:
                add('VOCAL', .07, 'mostly monophonic')
                add('BACKING_VOCAL', .04, 'mostly monophonic')
                if profile.mean_pitch <= 55:
                    add('BASS', .04, 'monophonic low line')
            if 48 <= profile.mean_pitch <= 84:
                add('VOCAL', .06, 'vocal-range register')
            if profile.mean_pitch <= 55:
                add('BASS', .12, 'low register')
            if profile.step_ratio >= .3:
                add('VOCAL', .04, 'stepwise melodic motion')
            if .1 <= profile.mean_duration <= .8:
                add('VOCAL', .02, 'phrase-like note duration')
            if profile.polyphony >= 1.5:
                for role in ('GUITAR', 'KEYS', 'STRINGS'):
                    add(role, .04, 'polyphonic texture')
            if alignment >= .25:
                add('VOCAL', .50 * min(1.0, alignment / .75),
                    f'lyrics alignment: {alignment:.0%}')
                add('BACKING_VOCAL', .10 * min(1.0, alignment / .75),
                    f'lyrics alignment: {alignment:.0%}')

        ranked = sorted(ROLES, key=lambda role: (-scores[role], ROLES.index(role)))
        winner = ranked[0]
        if scores[winner] < ROLE_THRESHOLD:
            winner = 'OTHER'
        confidence = round(min(1.0, scores[winner]), 3)
        evidence = tuple(sorted(reasons[winner], key=lambda reason: (
            0 if reason.startswith('name:') else
            1 if reason.startswith('lyrics alignment:') else
            2 if reason.startswith('GM family:') else 3))) or ('insufficient specific evidence',)
        results.append(TrackClassification(
            index=profile.index, name=profile.name, note_count=profile.note_count,
            final_role=winner, confidence=confidence,
            role_scores={role: round(min(1.0, scores[role]), 3) for role in ROLES},
            evidence=evidence, gm_family=family,
            monophonic=profile.monophony >= .8 and bool(notes),
            lyric_alignment=alignment,
        ))

    return tuple(results)
