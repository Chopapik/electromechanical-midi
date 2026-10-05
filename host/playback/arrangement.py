"""Song-specific routing between the existing MidiSource and device mechanics.

The document contains no MIDI bytes or playback clock. Rules select original
NoteSpans; the virtual constraint engine remains responsible for outcomes.
"""
from __future__ import annotations

import dataclasses
import hashlib
from typing import Any

from midi_source import MidiSource, NoteSpan, drum_name
from pitch import note_name
from .virtual import VirtualDeviceInstance

SCHEMA_VERSION = 1

class ArrangementError(ValueError):
    pass

class ArrangementMismatch(ArrangementError):
    def __init__(self, mismatches: list[dict]):
        super().__init__('Arrangement does not match the loaded MIDI')
        self.mismatches = mismatches

@dataclasses.dataclass(frozen=True)
class RoutedNote:
    span: NoteSpan
    note_id: str
    track: int
    rule_id: str
    articulation: str | None = None
    transpose: int = 0
    gate: float = 1.0
    octave_fold: bool = True
    strategy: str = 'first'

    @property
    def start(self): return self.span.start
    @property
    def end(self): return self.span.end
    @property
    def note(self): return self.span.note
    @property
    def velocity(self): return self.span.velocity
    @property
    def order(self): return self.span.order
    @property
    def duration(self): return self.span.duration


def midi_identity(source: MidiSource) -> dict:
    return {
        'file': source.path.name,
        'sha256': hashlib.sha256(source.path.read_bytes()).hexdigest(),
        'tracks': [{'index': t.index, 'name': t.name} for t in source.tracks],
    }


def all_notes(source: MidiSource) -> list[dict]:
    result = []
    for track in source.tracks:
        for span in source.notes(track.index):
            result.append({
                'id': f'{track.index}:{span.order}',
                'track': track.index, 'trackName': track.name,
                'channel': span.channel + 1, 'note': span.note,
                'name': drum_name(span.note) if track.is_drums else note_name(span.note),
                'start': round(span.start, 6), 'duration': round(span.duration, 6),
                'velocity': span.velocity, 'isDrum': track.is_drums,
            })
    return sorted(result, key=lambda n: (n['start'], n['track'], n['id']))


def _range(value: int, bound: dict | None) -> bool:
    if not bound:
        return True
    return (bound.get('min') is None or value >= int(bound['min'])) and (bound.get('max') is None or value <= int(bound['max']))


def matches(rule: dict, track: int, span: NoteSpan) -> bool:
    source = rule['source']
    tracks = source.get('tracks')
    if tracks is None:
        one = source.get('track')
        tracks = [one] if one is not None else None
    if tracks is not None and track not in tracks:
        return False
    channels = source.get('channels')
    if channels is None and source.get('channel') is not None:
        channels = [source['channel']]
    if channels is not None and span.channel + 1 not in channels:
        return False
    if source.get('includeNotes') is not None and span.note not in source['includeNotes']:
        return False
    if span.note in source.get('excludeNotes', []):
        return False
    return _range(span.note, source.get('noteRange')) and _range(span.velocity, source.get('velocityRange'))


class Arrangement:
    def __init__(self, data: dict):
        self.data = data
        self.devices = [VirtualDeviceInstance.parse(d) for d in data['devices']]
        self.rules = data['rules']

    @classmethod
    def default(cls, source: MidiSource, devices: list[VirtualDeviceInstance]) -> 'Arrangement':
        rules = []
        for device in devices:
            if device.track is not None:
                rules.append({'id': f'route-{device.id}', 'source': {'track': device.track},
                              'destination': {'deviceId': device.id}, 'transform': {}})
        return cls.parse({'schemaVersion': SCHEMA_VERSION, 'midi': midi_identity(source),
                          'name': source.path.stem, 'devices': [dataclasses.asdict(d) for d in devices],
                          'rules': rules}, source)

    @classmethod
    def parse(cls, payload: dict, source: MidiSource, *, allow_mismatch: bool = False) -> 'Arrangement':
        if not isinstance(payload, dict) or payload.get('schemaVersion') != SCHEMA_VERSION:
            raise ArrangementError(f'Unsupported arrangement schemaVersion (expected {SCHEMA_VERSION})')
        midi = payload.get('midi')
        if not isinstance(midi, dict) or not isinstance(payload.get('devices'), list) or not isinstance(payload.get('rules'), list):
            raise ArrangementError('Arrangement requires midi, devices and rules')
        if not isinstance(midi.get('file'), str) or not isinstance(midi.get('tracks'), list):
            raise ArrangementError('Arrangement midi requires file and track identities')
        if any(not isinstance(track, dict) or not isinstance(track.get('index'), int)
               or not isinstance(track.get('name'), str) for track in midi['tracks']):
            raise ArrangementError('Invalid MIDI track identity')
        current = midi_identity(source)
        mismatches = []
        if midi.get('file') != current['file'] or (midi.get('sha256') and midi['sha256'] != current['sha256']):
            mismatches.append({'kind': 'midi', 'expected': {'file': midi.get('file'), 'sha256': midi.get('sha256')},
                               'actual': {'file': current['file'], 'sha256': current['sha256']}})
        expected_tracks = {t['index']: t['name'] for t in midi['tracks']}
        if len(expected_tracks) != len(midi['tracks']) or len(expected_tracks) != len(current['tracks']):
            mismatches.append({'kind': 'trackCount', 'expected': len(midi['tracks']),
                               'actual': len(current['tracks'])})
        for index, name in expected_tracks.items():
            actual = current['tracks'][index]['name'] if isinstance(index, int) and 0 <= index < len(current['tracks']) else None
            if actual != name:
                mismatches.append({'kind': 'track', 'index': index, 'expected': name, 'actual': actual})
        if mismatches and not allow_mismatch:
            raise ArrangementMismatch(mismatches)
        devices = [VirtualDeviceInstance.parse(d) for d in payload['devices']]
        ids = {d.id for d in devices}
        if len(ids) != len(devices) or len(devices) > 64:
            raise ArrangementError('Device IDs must be unique (maximum 64)')
        rules = []
        rule_ids = set()
        for raw in payload['rules']:
            if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not raw['id'] or raw['id'] in rule_ids:
                raise ArrangementError('Rule IDs must be unique and nonempty')
            rule_ids.add(raw['id'])
            source_filter = raw.get('source') or {}
            if not isinstance(source_filter, dict):
                raise ArrangementError('Rule source must be an object')
            for key in ('track',):
                if source_filter.get(key) is not None and not (0 <= int(source_filter[key]) < len(source.tracks)):
                    raise ArrangementError(f'Rule {raw["id"]}: invalid track')
            for index in source_filter.get('tracks', []):
                if not 0 <= int(index) < len(source.tracks):
                    raise ArrangementError(f'Rule {raw["id"]}: invalid track')
            for key in ('includeNotes', 'excludeNotes'):
                values = source_filter.get(key)
                if values is not None and (not isinstance(values, list) or any(not 0 <= int(n) <= 127 for n in values)):
                    raise ArrangementError(f'Rule {raw["id"]}: invalid {key}')
            for key in ('noteRange', 'velocityRange'):
                bounds = source_filter.get(key)
                if bounds is not None and (not isinstance(bounds, dict) or any(
                    value is not None and not 0 <= int(value) <= 127 for value in bounds.values())):
                    raise ArrangementError(f'Rule {raw["id"]}: invalid {key}')
            destination = raw.get('destination') or {}
            target = destination.get('deviceId')
            if target is not None and target not in ids:
                raise ArrangementError(f'Rule {raw["id"]}: missing device {target}')
            transform = raw.get('transform') or {}
            gate = float(transform.get('gate', 1))
            transpose = int(transform.get('transpose', 0))
            if not 0 < gate <= 2 or not -48 <= transpose <= 48:
                raise ArrangementError(f'Rule {raw["id"]}: invalid transform')
            strategy = transform.get('strategy', 'first')
            if strategy not in ('first', 'highest', 'lowest', 'last'):
                raise ArrangementError(f'Rule {raw["id"]}: invalid strategy')
            rules.append({'id': str(raw['id'])[:80], 'source': source_filter,
                          'destination': {'deviceId': target},
                          'transform': {'gate': gate, 'transpose': transpose,
                                        'octaveFold': bool(transform.get('octaveFold', True)),
                                        'strategy': strategy},
                          'articulation': raw.get('articulation')})
        return cls({'schemaVersion': SCHEMA_VERSION, 'midi': current if allow_mismatch else midi,
                    'name': str(payload.get('name') or source.path.stem)[:100],
                    'devices': [dataclasses.asdict(d) for d in devices], 'rules': rules})

    def route(self, source: MidiSource) -> tuple[dict[str, list[RoutedNote]], list[dict]]:
        by_device: dict[str, list[RoutedNote]] = {d.id: [] for d in self.devices}
        enabled_ids = {d.id for d in self.devices if d.enabled}
        notes = all_notes(source)
        spans = {(track.index, span.order): span for track in source.tracks for span in source.notes(track.index)}
        for note in notes:
            span = spans[(note['track'], int(note['id'].split(':')[1]))]
            routed_to = set()
            routes = []
            matched = [rule for rule in self.rules if matches(rule, note['track'], span)]
            precise = [rule for rule in matched if rule['source'].get('track') == note['track']
                       and rule['source'].get('includeNotes') == [span.note]]
            for rule in precise or matched:
                target = rule['destination']['deviceId']
                if target is None:
                    routes.append({'ruleId': rule['id'], 'deviceId': None, 'status': 'UNASSIGNED'})
                    continue
                if target not in enabled_ids:
                    continue
                if target in routed_to:
                    continue
                routed_to.add(target)
                transform = rule['transform']
                by_device[target].append(RoutedNote(span, note['id'], note['track'], rule['id'],
                    rule.get('articulation'), transform['transpose'], transform['gate'],
                    transform['octaveFold'], transform['strategy']))
                routes.append({'ruleId': rule['id'], 'deviceId': target, 'status': 'PENDING',
                               'articulation': rule.get('articulation')})
            note['routes'] = routes
            note['status'] = 'UNASSIGNED' if not routed_to else 'PENDING'
        return by_device, notes

    def as_dict(self) -> dict:
        return self.data
