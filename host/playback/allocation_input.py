"""Deterministic source preparation and duplicate reporting for both allocators."""
from __future__ import annotations

from midi_source import MidiSource, drum_name
from pitch import note_name
from .analysis import BASS, HARMONY, LEAD, PERCUSSION, MidiAnalysis
from .sound_roles import UNPITCHED_EFFECT, UNSUPPORTED_EFFECT, source_effects
from .allocation_models import AllocationSlot, SourceNote
from .allocation_operations import dropped_event, note_priority

# Stable tie order: preserve source attacks and shortest-first within a role.
_BAND = {LEAD: 0, BASS: 1, PERCUSSION: 1, HARMONY: 2, UNPITCHED_EFFECT: 3}


def source_notes(source: MidiSource, midi_analysis: MidiAnalysis, policy: dict) -> list[SourceNote]:
    """Wszystkie nuty pliku z rola, w deterministycznej kolejnosci.

    W obrebie jednego uderzenia (ten sam start) najpierw dostaja urzadzenia
    nuty WAZNIEJSZE. Inaczej o tym, ktora z 8 rownoczesnych nut przezyje
    na 4 glosach, decydowalaby przypadkowa kolejnosc trackow.
    """
    result = []
    effects = source_effects(source)

    for track in source.tracks:
        for span in source.notes(track.index):
            note_id = f'{track.index}:{span.order}'
            role = UNPITCHED_EFFECT if note_id in effects else midi_analysis.roles.get(note_id, HARMONY)
            result.append({
                'id': note_id, 'span': span, 'track': track.index,
                'track_name': track.name, 'role': role, 'order': span.order,
                'priority': note_priority(role, span.velocity, span.duration, policy),
                'name': effects.get(note_id) or (drum_name(span.note) if track.is_drums else note_name(span.note)),
                'source_tracks': tuple(getattr(track, 'source_tracks', (track.index,))),
                'group_id': getattr(track, 'group_id', None),
                'duplicate_confidence': getattr(track, 'duplicate_confidence', None),
            })

    # W obrebie jednego uderzenia: najpierw wazniejsze role (lead, bas, perkusja),
    # a w tej samej roli NAJKROTSZE nuty pierwsze. To klasyczne SPT - maksymalizuje
    # liczbe zagranych nut, nie wypychajac przy tym melodii ani basu.
    result.sort(key=lambda item: (item['span'].start, _BAND[item['role']],
                                  item['span'].duration, item['track'], item['order']))

    return result


def partition_effects(notes, pins):
    """Keep unsupported triggers out of allocation, density and phrase budgets."""
    return ([note for note in notes if note['role'] != UNPITCHED_EFFECT],
            [dropped_event(note, UNSUPPORTED_EFFECT, UNPITCHED_EFFECT, None, pins.get(note['id']))
             for note in notes if note['role'] == UNPITCHED_EFFECT])


def duplicate_kpis(source, notes: list[SourceNote], accompaniment_slots: list[AllocationSlot],
                    report) -> dict:
    """Ile falszywej polifonii zniknelo i jak bardzo odciazylo to FDD."""
    tonal = [note for note in notes if note['role'] != PERCUSSION]

    if not tonal:
        return {}

    start = min(note['span'].start for note in tonal)
    end = max(note['span'].end for note in tonal)
    span = max(1e-6, end - start)
    capacity = span * max(1, len(accompaniment_slots))
    lead_tracks = {note['track'] for note in tonal if note['role'] == LEAD}
    logical_accompaniment = sum(note['span'].duration for note in tonal
                                if note['role'] != LEAD)
    lead_group: set[int] = set()

    for track in lead_tracks:
        group = report.group_of(track)
        lead_group |= set(group.tracks) if group is not None else {track}

    raw = getattr(source, 'source', None)
    raw_accompaniment = logical_accompaniment

    if raw is not None:
        raw_accompaniment = sum(
            span_.duration
            for track in raw.tracks
            if not track.is_drums and track.index not in lead_group
            for span_ in raw.notes(track.index))

    def clamp_demand(value: float) -> float:
        return value / capacity if capacity > 0 else 0.0

    return {
        'groupsFound': len(report.groups),
        'tracksCollapsed': report.collapsed_tracks,
        'rawTonalEvents': report.raw_tonal_events,
        'logicalTonalEvents': report.logical_tonal_events,
        'duplicateEventsCollapsed': report.events_removed,
        'accompanimentDemandSecondsBefore': round(raw_accompaniment, 1),
        'accompanimentDemandSecondsAfter': round(logical_accompaniment, 1),
        'demandCapacityBefore': round(clamp_demand(raw_accompaniment), 3),
        'demandCapacityAfter': round(clamp_demand(logical_accompaniment), 3),
        'capacitySeconds': round(capacity, 1),
        'groups': [group.as_dict() for group in report.groups],
        'pairs': [pair.as_dict() for pair in report.pairs],
    }
