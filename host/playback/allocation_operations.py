"""Shared scoring, gate budgets and event placement; no allocator dependency."""
from __future__ import annotations

import statistics
from midi_source import NoteSpan
from .analysis import BASS, HARMONY, LEAD, PERCUSSION
from .capabilities import MIN_NOTE_S
from .performance import PerformanceEvent
from .allocation_models import AllocationCandidate, AllocationSlot, ManualPin, SourceNote

_BASE_PRIORITY = {LEAD: 100.0, BASS: 80.0, PERCUSSION: 60.0, HARMONY: 40.0}


def note_priority(role: str, velocity: int, duration: float, policy: dict) -> float:
    base = _BASE_PRIORITY.get(role, _BASE_PRIORITY[HARMONY])

    if role == LEAD and not policy.get('preserveLead', True):
        base = _BASE_PRIORITY[HARMONY]
    elif role == BASS and not policy.get('preserveBass', True):
        base = _BASE_PRIORITY[HARMONY]

    if role == PERCUSSION:
        return base + velocity / 127.0 * 20.0

    return base + velocity / 127.0 * 10.0 + min(duration, 0.6) * 12.0


def clip_duration(duration: float, minimum: float, policy: dict,
          key: str = 'maxNoteSeconds') -> float:
    """Dlugosc nuty w planie: nie krotsza niz mechanika i nie dluzsza niz budzet.

    Monofoniczna orkiestra gra raczej krotkim gate'em niz sustainem: bez
    limitu dlugie nuty blokuja glosy i wypychaja z planu cala reszte.
    """
    duration = max(duration, minimum)
    cap = float(policy.get(key) or 0.0)

    return min(duration, cap) if cap > 0 else duration


def solve_cap(durations: list[float], budget: float) -> float:
    """Najwieksza dlugosc nuty, przy ktorej suma dlugosci <= budzet."""
    low, high = MIN_NOTE_S, max(durations)

    for _ in range(40):
        middle = (low + high) / 2.0

        if sum(min(duration, middle) for duration in durations) <= budget:
            low = middle
        else:
            high = middle

    return round(low, 4)


def adaptive_cap(notes: list[SourceNote], slots: list[AllocationSlot], policy: dict,
                  roles: frozenset[str]) -> float:
    """Budzet dlugosci nuty dla monofonicznej orkiestry.

    N glosow x dlugosc utworu to twarda pojemnosc. Gdy suma dlugosci nut ja
    przekracza, czesc materialu MUSI wypasc - chyba ze skrocimy nuty, tak jak
    robi to kazdy instrument monofoniczny grajacy akordy.

    Punktem odniesienia jest MEDIANA dlugosci nuty w tym utworze: nuta dluzsza
    od typowej blokuje glos bez muzycznego uzasadnienia. Solver pojemności
    dziala tylko jako bezpiecznik, gdyby mediana wciaz nie wystarczala.
    """
    # Budzet liczymy OSOBNO dla kazdej puli: akompaniament nie moze zjadac
    # pojemnosci zarezerwowanej dla leadu i odwrotnie.
    tonal = [note for note in notes if note['role'] in roles]

    if not tonal or not slots:
        return 0.0

    durations = [note['span'].duration for note in tonal]
    start = min(note['span'].start for note in tonal)
    end = max(note['span'].end for note in tonal)
    capacity = max(1e-6, end - start) * len(slots)

    if roles == frozenset({LEAD}) and sum(durations) <= capacity:
        return 0.0                       # nie skracamy rzadkiej linii leadu

    # Doswiadczalny zapas: glosy nigdy nie wypelniaja 100% czasu (artykulacja,
    # fragmentacja, nuty krotsze od limitu).
    budget = capacity * float(policy.get('capacitySafety', 1.6))
    cap = max(statistics.median(durations), MIN_NOTE_S)

    if sum(min(duration, cap) for duration in durations) > budget:
        cap = solve_cap(durations, budget)

    return round(min(cap, max(durations)), 4)


def dropped_event(note: SourceNote, outcome_reason: str, role: str,
             preferred: str | None, pin: ManualPin | None) -> PerformanceEvent:
    span: NoteSpan = note['span']

    return PerformanceEvent(
        id=note['id'], track=note['track'], track_name=note['track_name'],
        note=span.note, name=note['name'], velocity=span.velocity,
        channel=span.channel, start=span.start, duration=span.duration,
        device_id=None, device_type=None, played_note=None, played_hz=None,
        actual_start=span.start, actual_duration=0.0, outcome='DROPPED',
        role=role, preferred_device=preferred,
        rule_id=pin.rule_id if pin else None, reason=outcome_reason,
        source_tracks=note.get('source_tracks', ()),
        duplicate_group_id=note.get('group_id'),
        duplicate_confidence=note.get('duplicate_confidence'))


def commit_event(slot: AllocationSlot, events: list[PerformanceEvent], event: PerformanceEvent,
            start: float, duration: float) -> None:
    events.append(event)
    slot.event_index = len(events) - 1
    slot.busy_until = start + duration + slot.capability.retrigger_s
    slot.last_played = event.played_note


def place_event(slot: AllocationSlot, candidate: AllocationCandidate, note: SourceNote, outcome: str,
           actual_start: float, duration: float, role: str, pin: ManualPin | None,
           preferred: str, events: list[PerformanceEvent]) -> PerformanceEvent:
    span: NoteSpan = note['span']
    final = outcome

    if candidate.folded and outcome == 'ACCEPTED':
        final = 'FOLDED'

    event = PerformanceEvent(
        id=note['id'], track=note['track'], track_name=note['track_name'],
        note=span.note, name=note['name'], velocity=span.velocity,
        channel=span.channel, start=span.start, duration=span.duration,
        device_id=slot.device.id, device_type=slot.device.type,
        played_note=candidate.played, played_hz=candidate.hz,
        actual_start=actual_start, actual_duration=duration,
        outcome=final, role=role, preferred_device=preferred,
        articulation=pin.articulation if pin else None,
        rule_id=pin.rule_id if pin else None,
        source_tracks=note.get('source_tracks', ()),
        duplicate_group_id=note.get('group_id'),
        duplicate_confidence=note.get('duplicate_confidence'))
    commit_event(slot, events, event, actual_start, duration)

    return event
