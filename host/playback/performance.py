"""Performance Plan: jedyne zrodlo prawdy o tym, co ma zagrac ktore urzadzenie.

Plan jest pomiedzy allokatorem a rendererami:

    MIDI -> analiza -> allocator -> PERFORMANCE PLAN -> VirtualOrchestra
                                                    -> hardware scheduler (v2)

Virtual Orchestra renderuje decyzje zawarte w planie. NIE podejmuje ich
ponownie i nie dropuje niczego "po swojemu" - inaczej dwie sciezki
(wirtualna i sprzetowa) gralyby co innego.
"""
from __future__ import annotations

import dataclasses

# Mozliwe wyniki dla pojedynczego zdarzenia. Kolejnosc = precedencja przy
# raportowaniu: gdy nuta byla i przesunieta, i przypisana do innego
# urzadzenia, raportujemy ten wczesniejszy (bardziej "ratunkowy") stan.
# Przerwa dluzsza niz to slychac jako dziure, nie artykulacje.
LONG_GAP_S = 0.150

OUTCOMES = (
    'DROPPED',       # nie bylo gdzie zagrac - ostatecznosc
    'STOLEN',        # wziela glos urzadzeniu o nizszym priorytecie
    'SHORTENED',     # zagrala, ale krotsza niz w zapisie
    'ARPEGGIATED',   # dolozona poza oknem micro-delay (rozlozenie akordu)
    'DELAYED',       # start opozniony w oknie micro-delay
    'REASSIGNED',    # preferowane urzadzenie zajete - zagralo inne wolne
    'FOLDED',        # octave folding, zeby zmiescic sie w zakresie
    'ACCEPTED',      # zagrala dokladnie tam, gdzie chciala
)

# Statusy zrozumiale dla istniejacego UI/piano rolla.
_STATUS = {
    'DROPPED': 'DROPPED',
    'STOLEN': 'ACCEPTED',
    'SHORTENED': 'ACCEPTED',
    'ARPEGGIATED': 'DELAYED',
    'DELAYED': 'DELAYED',
    'REASSIGNED': 'ACCEPTED',
    'FOLDED': 'FOLDED',
    'ACCEPTED': 'ACCEPTED',
}


@dataclasses.dataclass(frozen=True)
class PerformanceEvent:
    """Jedno zdarzenie planu: zrodlo, decyzja, faktyczny czas."""

    id: str
    track: int
    track_name: str
    note: int                      # nuta zapisana w MIDI
    name: str | None               # nazwa nuty / brzmienia perkusyjnego
    velocity: int
    channel: int
    start: float                   # oryginalny start z MIDI
    duration: float                # oryginalna dlugosc
    device_id: str | None
    device_type: str | None
    played_note: int | None        # po transpozycji i zlozeniu oktawowym
    played_hz: float | None
    actual_start: float
    actual_duration: float
    outcome: str
    role: str = 'harmony'
    preferred_device: str | None = None
    articulation: str | None = None
    stolen_from: str | None = None
    reason: str | None = None
    rule_id: str | None = None     # ustawione, gdy decyzja pochodzi z recznej reguly
    # --- pochodzenie: partia logiczna po sklejeniu double-trackingu ---
    source_tracks: tuple[int, ...] = ()
    duplicate_group_id: str | None = None
    duplicate_confidence: float | None = None
    # Ile sekund dodala mechaniczna artykulacja (0 = nuta grala tyle, ile w MIDI).
    sustain_added: float = 0.0

    @property
    def delay(self) -> float:
        return max(0.0, self.actual_start - self.start)

    @property
    def end(self) -> float:
        return self.actual_start + self.actual_duration

    @property
    def played(self) -> bool:
        return self.outcome != 'DROPPED' and self.device_id is not None

    @property
    def reassigned(self) -> bool:
        return self.preferred_device is not None and self.device_id != self.preferred_device

    @property
    def folded(self) -> bool:
        return self.played_note is not None and self.played_note != self.note

    @property
    def status(self) -> str:
        return _STATUS.get(self.outcome, 'DROPPED')

    def as_dict(self) -> dict:
        return {
            'id': self.id, 'track': self.track, 'trackName': self.track_name,
            'note': self.note, 'name': self.name, 'velocity': self.velocity,
            'channel': self.channel, 'start': round(self.start, 6),
            'duration': round(self.duration, 6),
            'deviceId': self.device_id, 'deviceType': self.device_type,
            'playedNote': self.played_note,
            'playedHz': round(self.played_hz, 3) if self.played_hz else None,
            'actualStart': round(self.actual_start, 6),
            'actualDuration': round(self.actual_duration, 6),
            # Jawny podzial: co bylo w MIDI vs co zagra mechanika.
            'sourceDuration': round(self.duration, 6),
            'performedDuration': round(self.actual_duration, 6),
            'sustainExtendedMs': round(self.sustain_added * 1000, 2),
            # UWAGA: 'articulation' to artykulacja z recznej reguly (np. LEFT_HARD).
            # Mechaniczny sustain to osobne pole, zeby sie nie nadpisywaly.
            'mechanicalArticulation': ('mechanical-sustain'
                                       if self.sustain_added > 1e-6 else None),
            'outcome': self.outcome, 'status': self.status, 'role': self.role,
            'preferredDevice': self.preferred_device,
            'delay': round(self.delay, 6),
            'delayMs': round(self.delay * 1000, 2),
            'reassigned': self.reassigned, 'folded': self.folded,
            'articulation': self.articulation, 'stolenFrom': self.stolen_from,
            'reason': self.reason, 'ruleId': self.rule_id,
            'sourceTracks': list(self.source_tracks),
            'duplicateGroupId': self.duplicate_group_id,
            'duplicateConfidence': self.duplicate_confidence,
        }


@dataclasses.dataclass(frozen=True)
class ReinforcementEvent:
    source_id: str
    device_id: str
    start: float
    duration: float
    hz: float
    velocity: int

    def as_dict(self) -> dict:
        return {'sourceId': self.source_id, 'deviceId': self.device_id,
                'start': round(self.start, 6), 'duration': round(self.duration, 6),
                'hz': round(self.hz, 3), 'velocity': self.velocity}


@dataclasses.dataclass
class PerformancePlan:
    """Caly plan wykonania: zdarzenia + orkiestra + polityka + raport."""

    name: str
    events: list[PerformanceEvent]
    devices: list[dict]
    policy: dict
    analysis: dict = dataclasses.field(default_factory=dict)
    source_ref: dict = dataclasses.field(default_factory=dict)
    origin: str = 'auto'          # 'auto' | 'manual' | 'hybrid'
    lead_devices: tuple[str, ...] = ()   # urzadzenia DEDICATED_LEAD_ONLY
    duplicates: dict = dataclasses.field(default_factory=dict)
    articulation: dict = dataclasses.field(default_factory=dict)
    dvd_mode: str = 'independent'
    reinforcements: list[ReinforcementEvent] = dataclasses.field(default_factory=list)

    @property
    def duration(self) -> float:
        return max((event.end for event in self.events), default=0.0)

    def by_device(self) -> dict[str, list[PerformanceEvent]]:
        result: dict[str, list[PerformanceEvent]] = {device['id']: [] for device in self.devices}

        for event in self.events:
            if event.device_id is not None:
                result.setdefault(event.device_id, []).append(event)

        return result

    def report(self) -> dict:
        return build_report(self)

    def as_dict(self) -> dict:
        return {
            'name': self.name,
            'origin': self.origin,
            'policy': self.policy,
            'analysis': self.analysis,
            'midi': self.source_ref,
            'devices': self.devices,
            'dvdMode': self.dvd_mode,
            'reinforcements': [event.as_dict() for event in self.reinforcements],
            'events': [event.as_dict() for event in self.events],
            'report': self.report(),
        }


def _blank(kind: str) -> dict:
    return {'kind': kind, 'requested': 0, 'played': 0, 'dropped': 0,
            'onTime': 0, 'reassigned': 0, 'delayed': 0, 'arpeggiated': 0,
            'stolen': 0, 'shortened': 0, 'folded': 0,
            'delaySumMs': 0.0, 'delayMaxMs': 0.0}


def _summary(bucket: dict, total_duration: float, device_count: int,
             activity: dict[str, float]) -> dict:
    requested = bucket['requested']
    played = bucket['played']
    delayed = bucket['delayed']
    used = [value for value in activity.values()]
    active_time = sum(used)

    return {
        **{key: value for key, value in bucket.items() if key != 'delaySumMs'},
        'dropRate': round(bucket['dropped'] / requested, 4) if requested else 0.0,
        'meanDelayMs': round(bucket['delaySumMs'] / delayed, 2) if delayed else 0.0,
        'maxDelayMs': round(bucket['delayMaxMs'], 2),
        'retention': round(played / requested, 4) if requested else 1.0,
        'activeTime': round(active_time, 3),
        'utilization': (round(active_time / (total_duration * device_count), 4)
                        if total_duration > 0 and device_count else 0.0),
    }


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Scala nachodzace na siebie przedzialy czasu."""
    merged: list[list[float]] = []

    for start, stop in sorted(intervals):
        if merged and start <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], stop)
        else:
            merged.append([start, stop])

    return [(start, stop) for start, stop in merged]


def _intersection(left: list[tuple[float, float]],
                  right: list[tuple[float, float]]) -> float:
    total = 0.0
    index = 0

    for start, stop in left:
        while index < len(right) and right[index][1] <= start:
            index += 1

        position = index

        while position < len(right) and right[position][0] < stop:
            total += min(stop, right[position][1]) - max(start, right[position][0])
            position += 1

    return max(0.0, total)


def continuity(plan: PerformancePlan, *, tonal_only: bool = False) -> dict:
    """Kiedy orkiestra MILCZY - miara ciaglosci odtwarzania.

    Plan moze wygladac dobrze w metrykach dropow, a mimo to miec dziury:
    krotsze nuty i przesuniecia zostawiaja okna bez dzwieku. Liczymy je
    wprost na sumie przedzialow wszystkich zagranych zdarzen.
    """
    events = [event for event in plan.events
              if event.played and (not tonal_only or event.role != 'percussion')]
    end_of_song = max((event.actual_start for event in plan.events), default=0.0)

    if not events:
        return {'orchestraSilentTime': round(end_of_song, 3), 'silentGapCount': 1 if end_of_song else 0,
                'meanSilentGapMs': round(end_of_song * 1000, 1), 'maxSilentGapMs': round(end_of_song * 1000, 1),
                'plannedCoverage': 0.0}

    intervals = sorted((event.actual_start, event.end) for event in events)
    merged: list[list[float]] = []

    for start, stop in intervals:
        if merged and start <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], stop)
        else:
            merged.append([start, stop])

    gaps = []
    cursor = 0.0

    for start, stop in merged:
        if start - cursor > 1e-3:
            gaps.append(start - cursor)

        cursor = max(cursor, stop)

    if end_of_song - cursor > 1e-3:
        gaps.append(end_of_song - cursor)

    sounding = sum(stop - start for start, stop in merged)
    source_tonal = sum(event.duration for event in plan.events
                       if event.role != 'percussion' and event.played)

    fdd = [event for event in plan.events
           if event.played and event.device_type == 'FDD']
    accompaniment = [event for event in plan.events
                     if event.role not in ('lead', 'percussion')]
    intended_accompaniment = _merge([(event.start, event.start + event.duration)
                                     for event in accompaniment])
    played_fdd = _merge([(event.actual_start, event.end) for event in fdd])
    played_accompaniment = _merge([
        (event.actual_start, event.end) for event in plan.events
        if event.played and event.role in ('bass', 'harmony')
    ])
    active_accompaniment = sum(stop - start for start, stop in intended_accompaniment)
    covered_accompaniment = _intersection(intended_accompaniment, played_accompaniment)

    ordered = sorted(gaps)
    long_gaps = [value for value in ordered if value > LONG_GAP_S]

    def percentile(fraction: float) -> float:
        if not ordered:
            return 0.0

        return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))] * 1000

    return {
        'orchestraSilentTime': round(sum(gaps), 3),
        'silentGapCount': len(gaps),
        'meanSilentGapMs': round(sum(gaps) / len(gaps) * 1000, 1) if gaps else 0.0,
        'medianSilentGapMs': round(percentile(0.5), 1),
        'p90SilentGapMs': round(percentile(0.9), 1),
        'maxSilentGapMs': round(max(gaps) * 1000, 1) if gaps else 0.0,
        # Dziury, ktore slychac jako "gra - cisza - gra". Krotkie przerwy to
        # artykulacja, nie blad planu.
        'longGapCount': len(long_gaps),
        'longGapSeconds': round(sum(long_gaps), 3),
        'plannedCoverage': round(sounding / end_of_song, 4) if end_of_song > 0 else 0.0,
        'soundingSeconds': round(sounding, 3),
        'sourceSoundingSeconds': round(source_tonal, 3),
        # Czy akompaniament sie "niesie": ile czasu, w ktorym zrodlo ma
        # material akompaniamentu, rzeczywiscie gra FDD lub dodatkowy DVD.
        'accompanimentActiveSeconds': round(active_accompaniment, 3),
        'accompanimentCoveredSeconds': round(covered_accompaniment, 3),
        'accompanimentContinuity': (round(covered_accompaniment / active_accompaniment, 4)
                                    if active_accompaniment > 0 else 0.0),
        'fddCoverage': (round(sum(stop - start for start, stop in played_fdd) / end_of_song, 4)
                        if end_of_song > 0 else 0.0),
    }


def build_report(plan: PerformancePlan) -> dict:
    """Metryki, ktore mowia czy plan jest dobry - bez zgadywania."""
    duration = plan.duration
    kinds = {'tonal': _blank('tonal'), 'percussion': _blank('percussion')}
    per_device: dict[str, dict] = {}
    activity: dict[str, float] = {}
    device_kind: dict[str, str] = {}

    types = {device['id']: device.get('type', '') for device in plan.devices}

    for event in plan.events:
        kind = 'percussion' if event.role == 'percussion' else 'tonal'
        bucket = kinds[kind]
        bucket['requested'] += 1

        if event.outcome == 'DROPPED':
            bucket['dropped'] += 1
        else:
            bucket['played'] += 1

        # onTime = zagralo dokladnie w swoim czasie (niezaleznie od tego,
        # ktore urzadzenie je uratowalo). To metryka "czy sa dziury".
        if event.outcome != 'DROPPED' and event.delay <= 1e-3:
            bucket['onTime'] += 1

        if event.outcome == 'REASSIGNED':
            bucket['reassigned'] += 1
        elif event.outcome == 'DELAYED':
            bucket['delayed'] += 1
        elif event.outcome == 'ARPEGGIATED':
            bucket['arpeggiated'] += 1
        elif event.outcome == 'STOLEN':
            bucket['stolen'] += 1
        elif event.outcome == 'SHORTENED':
            bucket['shortened'] += 1
        elif event.outcome == 'FOLDED':
            bucket['folded'] += 1

        # Flagi sa niezalezne od wyniku glownego - inaczej gubimy informacje.
        if event.reassigned and event.outcome != 'REASSIGNED':
            bucket['reassigned'] += 1

        if event.folded and event.outcome != 'FOLDED':
            bucket['folded'] += 1

        if event.delay > 0:
            bucket['delaySumMs'] += event.delay * 1000.0
            bucket['delayMaxMs'] = max(bucket['delayMaxMs'], event.delay * 1000.0)

        if event.device_id is None:
            continue

        entry = per_device.setdefault(event.device_id, {
            'deviceId': event.device_id, 'type': types.get(event.device_id, ''),
            'notes': 0, 'dropped': 0, 'activeTime': 0.0, 'utilization': 0.0,
        })
        entry['notes'] += 1
        entry['activeTime'] += event.actual_duration
        activity[event.device_id] = activity.get(event.device_id, 0.0) + event.actual_duration
        device_kind[event.device_id] = 'percussion' if event.role == 'percussion' else 'tonal'

    for device in plan.devices:
        device_id = device['id']
        activity.setdefault(device_id, 0.0)
        entry = per_device.setdefault(device_id, {
            'deviceId': device_id, 'type': device.get('type', ''),
            'notes': 0, 'dropped': 0, 'activeTime': 0.0, 'utilization': 0.0,
        })
        entry['activeTime'] = round(activity.get(device_id, 0.0), 3)
        entry['utilization'] = (round(activity.get(device_id, 0.0) / duration, 4)
                                if duration > 0 else 0.0)

    # Dropy dopisujemy do urzadzen tylko wtedy, gdy wiemy, gdzie trafily.
    for event in plan.events:
        if event.outcome == 'DROPPED' and event.preferred_device in per_device:
            per_device[event.preferred_device]['dropped'] += 1

    tonal_devices = [d for d in plan.devices if device_kind.get(d['id'], 'tonal') == 'tonal']
    perc_devices = [d for d in plan.devices if device_kind.get(d['id']) == 'percussion']
    tonal_activity = {k: v for k, v in activity.items() if device_kind.get(k, 'tonal') == 'tonal'}
    perc_activity = {k: v for k, v in activity.items() if device_kind.get(k) == 'percussion'}

    total_requested = sum(bucket['requested'] for bucket in kinds.values())
    total_played = sum(bucket['played'] for bucket in kinds.values())
    total_dropped = sum(bucket['dropped'] for bucket in kinds.values())
    delayed = sum(bucket['delayed'] + bucket['arpeggiated'] for bucket in kinds.values())
    delay_sum = sum(bucket['delaySumMs'] for bucket in kinds.values())

    lead_events = [event for event in plan.events if event.role == 'lead']
    lead_played = [event for event in lead_events if event.played]
    lead_devices = set(plan.lead_devices)
    on_lead_device = [event for event in plan.events if event.device_id in lead_devices]
    violations = [event for event in on_lead_device if event.role != 'lead']

    return {
        'sourceEvents': total_requested,
        'dvdMode': plan.dvd_mode,
        'reinforcement': {
            'events': len(plan.reinforcements),
            'totalSeconds': round(sum(event.duration for event in plan.reinforcements), 3),
        },
        'trackClassification': plan.analysis.get('trackClassification', []),
        'lead': {
            'requested': len(lead_events),
            'played': len(lead_played),
            'dropped': len(lead_events) - len(lead_played),
            'delayed': len([e for e in lead_events
                            if e.outcome in ('DELAYED', 'ARPEGGIATED', 'STOLEN')]),
            'preservation': (round(len(lead_played) / len(lead_events), 4)
                             if lead_events else 1.0),
        },
        'leadDevices': {
            'devices': sorted(lead_devices),
            'notes': len(on_lead_device),
            'nonLeadEvents': len(violations),
            'clean': not violations,
        },
        'tonal': _summary(kinds['tonal'], duration, len(tonal_devices), tonal_activity),
        'percussion': _summary(kinds['percussion'], duration, len(perc_devices), perc_activity),
        'devices': sorted(per_device.values(), key=lambda item: item['deviceId']),
        'totals': {
            'requested': total_requested,
            'played': total_played,
            'dropped': total_dropped,
            'dropRate': round(total_dropped / total_requested, 4) if total_requested else 0.0,
            'retention': round(total_played / total_requested, 4) if total_requested else 1.0,
            'delayed': sum(bucket['delayed'] for bucket in kinds.values()),
            'arpeggiated': sum(bucket['arpeggiated'] for bucket in kinds.values()),
            'reassigned': sum(bucket['reassigned'] for bucket in kinds.values()),
            'voiceSteals': sum(bucket['stolen'] for bucket in kinds.values()),
            'shortened': sum(bucket['shortened'] for bucket in kinds.values()),
            'folded': sum(bucket['folded'] for bucket in kinds.values()),
            'meanDelayMs': round(delay_sum / delayed, 2) if delayed else 0.0,
            'maxDelayMs': round(max((bucket['delayMaxMs'] for bucket in kinds.values()), default=0.0), 2),
        },
        'duration': round(duration, 3),
        'continuity': continuity(plan),
        'continuityTonal': continuity(plan, tonal_only=True),
        'duplicates': plan.duplicates,
        'articulation': plan.articulation,
    }
