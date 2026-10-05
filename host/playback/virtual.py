"""Virtual orchestra: deterministic mechanics first, disposable acoustic preview second.

All times come from MidiSource's TempoMap. No MIDI parser or browser scheduler lives here.
Unknown reference profiles deliberately omit unverified mechanical limits.
"""
from __future__ import annotations

import dataclasses
import bisect
from array import array
import math
import struct
import subprocess
import shutil
import threading
import time
import re
import tempfile
import wave
from pathlib import Path

from midi_source import MidiSource
from pitch import hz_to_midi, midi_to_hz
from .timeline import Command, Timeline

from .tonal_articulation import Curve, TonalArticulation, resolve as resolve_tonal, render as render_tonal, retarget as retarget_tonal, apply_mode as apply_tonal_mode
from .hdd_articulation import HDDArticulation, classify as classify_hdd, adapt as adapt_hdd, sample as sample_hdd

KINDS = ('FDD', 'DVD_SLED', 'DVD_TRAY', 'STEPPER_FREE', 'VHS', 'HDD_VCM', 'SOLENOID_RESONATOR')
TONAL = {'FDD', 'DVD_SLED', 'STEPPER_FREE', 'VHS'}

# Tryb instancji decyduje, dokad trafiaja jej zaakceptowane nuty:
#   'virtual' - tylko symulacja i podglad audio (bez Seriala),
#   'real'    - tylko fizyczny sprzet na swojej linii (bez podgladu audio),
#   'hybrid'  - jedno i drugie.
# Dzieki temu ten sam dokument aranzacji obsluguje sprzet i wirtualizacje.
MODES = ('virtual', 'real', 'hybrid')
MODE_ALIASES = {'hardware': 'real', 'physical': 'real', 'both': 'hybrid'}

@dataclasses.dataclass(frozen=True)
class Parameter:
    value: float | int | None
    provenance: str
    source: str = ''

@dataclasses.dataclass(frozen=True)
class DeviceProfile:
    id: str
    kind: str
    parameters: dict[str, Parameter]
    overflow: str = 'drop'
    busy_policy: str = 'drop'

    def get(self, name: str) -> float | int | None:
        return self.parameters.get(name, Parameter(None, 'UNKNOWN')).value

    def as_dict(self) -> dict:
        return {'id': self.id, 'kind': self.kind, 'overflow': self.overflow,
                'busyPolicy': self.busy_policy,
                'parameters': {k: dataclasses.asdict(v) for k, v in self.parameters.items()}}

def _p(value, provenance='UNKNOWN', source=''):
    return Parameter(value, provenance, source)

PROFILES = {
    'DVD_TRAY_REFERENCE': DeviceProfile('DVD_TRAY_REFERENCE', 'DVD_TRAY', {
        'polyphony': _p(1, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'shortMinMs': _p(80, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'shortMaxMs': _p(120, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'mediumMinMs': _p(140, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'mediumMaxMs': _p(200, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'strongMinMs': _p(200, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'strongMaxMs': _p(300, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'cooldownMs': _p(150, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'rideGapMs': _p(800, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'openHatGapMs': _p(1200, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'openHatMinVelocity': _p(100, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'rideMinVelocity': _p(75, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'motorHz': _p(120, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'resonanceHz': _p(1050, 'ESTIMATED', 'software experiment; needs physical calibration'),
        'gearHz': _p(57, 'ESTIMATED', 'software experiment; needs physical calibration'),
    }),
    'FDD_CURRENT': DeviceProfile('FDD_CURRENT', 'FDD', {
        'polyphony': _p(1, 'RESEARCHED', 'single FDD head and firmware PLAY state'),
        'minPosition': _p(4, 'RESEARCHED', 'firmware/floppy/src/main.cpp MIN_TRACK'),
        'maxPosition': _p(72, 'RESEARCHED', 'firmware/floppy/src/main.cpp MAX_TRACK'),
        'minHz': _p(40, 'RESEARCHED', 'firmware MIN_PLAY_HZ'),
        'maxHz': _p(500, 'RESEARCHED', 'firmware MAX_PLAY_HZ'),
        'preferredMinHz': _p(130, 'RESEARCHED', 'host/pitch.py'),
        'preferredMaxHz': _p(330, 'RESEARCHED', 'host/pitch.py'),
        'maxStepRate': _p(1000, 'RESEARCHED', 'firmware MIN_STEP_INTERVAL_US'),
    }, overflow='fold'),
    'DVD_REFERENCE': DeviceProfile('DVD_REFERENCE', 'DVD_SLED', {
        'polyphony': _p(1, 'ESTIMATED', 'one sled motor per instance'),
        'minPosition': _p(None), 'maxPosition': _p(None),
        'minHz': _p(None), 'maxHz': _p(None), 'maxStepRate': _p(None),
    }),
    'STEPPER_REFERENCE': DeviceProfile('STEPPER_REFERENCE', 'STEPPER_FREE', {
        'polyphony': _p(1, 'ESTIMATED', 'one motor per instance'),
        'minHz': _p(None), 'maxHz': _p(None), 'maxStepRate': _p(None),
    }),
    'VHS_CURRENT': DeviceProfile('VHS_CURRENT', 'VHS', {
        'polyphony': _p(1, 'RESEARCHED', 'single current motor'),
        'minHz': _p(20, 'RESEARCHED', 'host/playback/engine.py DRUM_MIN_HZ'),
        'maxHz': _p(2000, 'RESEARCHED', 'host/playback/engine.py DRUM_MAX_HZ'),
        'drive': _p(38, 'RESEARCHED', 'host/playback/timeline.py DRUM_DRIVE_DEFAULT'),
        'acceleration': _p(None),
    }),
    'WD_CAVIAR_CURRENT': DeviceProfile('WD_CAVIAR_CURRENT', 'HDD_VCM', {
        'polyphony': _p(1, 'RESEARCHED', 'single current VCM'),
        'parkMs': _p(40, 'RESEARCHED', 'firmware/floppy/src/main.cpp'),
        'settleMs': _p(40, 'RESEARCHED', 'firmware/floppy/src/main.cpp'),
        'strikeMs': _p(25, 'RESEARCHED', 'firmware/floppy/src/main.cpp'),
        'cooldownMs': _p(0, 'ESTIMATED', 'preview; calibrate separately'),
    }),
    'SOLENOID_REFERENCE': DeviceProfile('SOLENOID_REFERENCE', 'SOLENOID_RESONATOR', {
        'polyphony': _p(1, 'ESTIMATED', 'single actuator per instance'),
        'fixedMidiNote': _p(None), 'minRetriggerMs': _p(None),
        'resonanceHz': _p(None), 'velocityExponent': _p(.6, 'ESTIMATED', 'preview curve, not measured force'),
    }),
}
DEFAULT_PROFILE = {p.kind: p.id for p in PROFILES.values()}

@dataclasses.dataclass
class VirtualDeviceInstance:
    id: str
    type: str
    name: str
    track: int | None = None
    role: str = ''
    volume: float = 0.6
    pan: float = 0.0
    mute: bool = False
    solo: bool = False
    transpose: int = 0
    gate: float = 1.0
    profile: str = ''
    mode: str = 'virtual'
    overrides: dict[str, Parameter] = dataclasses.field(default_factory=dict)

    @property
    def drives_hardware(self) -> bool:
        """Czy instancja ma wysylac komendy na fizyczna linie (Serial)."""
        return self.mode in ('real', 'hybrid')

    @property
    def in_preview(self) -> bool:
        """Czy instancja ma byc slyszalna w podgladzie audio (WAV)."""
        return self.mode in ('virtual', 'hybrid')

    @classmethod
    def parse(cls, data: dict) -> 'VirtualDeviceInstance':
        kind = str(data.get('type', ''))
        if kind not in KINDS:
            raise ValueError(f'unknown device type: {kind}')
        ident = str(data.get('id', ''))
        if not ident or len(ident) > 80:
            raise ValueError('device id required (max 80 chars)')
        profile = str(data.get('profile') or DEFAULT_PROFILE[kind])
        if profile not in PROFILES or PROFILES[profile].kind != kind:
            raise ValueError(f'invalid profile for {kind}')
        track = data.get('track')
        track = None if track is None else int(track)
        if track is not None and track < 0:
            raise ValueError('track must be nonnegative')
        volume, pan, gate = float(data.get('volume', .6)), float(data.get('pan', 0)), float(data.get('gate', 1))
        if not (0 <= volume <= 1 and -1 <= pan <= 1 and 0 < gate <= 2):
            raise ValueError('volume, pan or gate outside supported range')
        transpose = int(data.get('transpose', 0))
        if not -48 <= transpose <= 48:
            raise ValueError('transpose outside supported range')
        mode = str(data.get('mode') or 'virtual').strip().lower()
        mode = MODE_ALIASES.get(mode, mode)
        if mode not in MODES:
            raise ValueError(f'invalid mode: {mode} (expected one of {", ".join(MODES)})')
        if kind == 'DVD_TRAY' and mode != 'virtual':
            raise ValueError('DVD_TRAY supports virtual mode only')
        overrides = {}
        for key, item in (data.get('overrides') or {}).items():
            if key not in PROFILES[profile].parameters or key == 'polyphony':
                raise ValueError(f'invalid profile parameter: {key}')
            provenance = str(item.get('provenance', 'ESTIMATED'))
            if provenance not in ('CALIBRATED', 'MEASURED', 'RESEARCHED', 'ESTIMATED', 'UNKNOWN'):
                raise ValueError(f'invalid provenance: {provenance}')
            raw = item.get('value')
            value = None if raw is None or raw == '' else float(raw)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f'invalid value for {key}')
            overrides[key] = Parameter(value, provenance, str(item.get('source') or '')[:200])
        return cls(ident, kind, str(data.get('name') or kind)[:80], track,
                   str(data.get('role') or '')[:80], volume, pan,
                   bool(data.get('mute', False)), bool(data.get('solo', False)),
                   transpose, gate, profile, mode, overrides)

def effective_profile(device: VirtualDeviceInstance) -> DeviceProfile:
    base = PROFILES[device.profile or DEFAULT_PROFILE[device.type]]
    return dataclasses.replace(base, parameters={**base.parameters, **device.overrides})

@dataclasses.dataclass(frozen=True)
class AcousticEvent:
    time: float
    kind: str
    device: str
    hz: float = 0.0
    duration: float = 0.0
    velocity: int = 100
    direction: int = 1
    hdd_articulation: HDDArticulation | None = None
    source_id: str | None = None
    reinforcement: bool = False
    source_note: int | None = None
    source_channel: int | None = None
    source_track: str = ''
    tonal_articulation: TonalArticulation | None = None

class MechanicalState:
    def __init__(self, profile: DeviceProfile):
        self.position = float(profile.get('minPosition') or 0)
        self.direction = 1
        self.playing = False
        self.current_frequency = 0.0
        self.target_frequency = 0.0
        self.drive = float(profile.get('drive') or 0)
        self.running = False
        self.busy_until = 0.0
        self.phase = 'IDLE'

class VirtualOrchestra:
    def __init__(self, devices: list[VirtualDeviceInstance] | None = None, name: str = 'Virtual Orchestra'):
        self.name = name
        self.dvd_mode = 'independent'
        self.master_volume = 1.0
        self.hdd_mode = 'articulated'
        self.tonal_mode = 'articulated'
        self.source_continuity = False
        self.source_continuity_amount = 1.
        self.tray_enabled = True
        self.idle_reinforcement = {}
        self.tray_movements = []
        self.devices = devices or []
        self.report: dict = {}
        self.events: list[AcousticEvent] = []
        self.activity: dict[str, list[tuple[float, float]]] = {}
        self.decisions: dict[str, list[dict]] = {}

    def set_config(self, payload: dict) -> None:
        tonal_mode = str(payload.get('tonalMode', 'articulated'))
        if tonal_mode not in ('raw', 'articulated', 'extreme', 'extreme_v15', 'extreme_v2'):
            raise ValueError('tonalMode must be raw, articulated, extreme, extreme_v15 or extreme_v2')
        hdd_mode = str(payload.get('hddMode', 'articulated'))
        if hdd_mode not in ('raw', 'articulated'):
            raise ValueError('hddMode must be raw or articulated')
        master = float(payload.get('masterVolume', 1.0))
        if not math.isfinite(master) or not 0 <= master <= 20:
            raise ValueError('masterVolume outside supported range 0..20')
        amount = float(payload.get('sourceContinuityAmount', 1.))
        if not math.isfinite(amount) or not 0 <= amount <= 1:
            raise ValueError('sourceContinuityAmount must be between 0 and 1')
        devices = [VirtualDeviceInstance.parse(item) for item in payload.get('devices', [])]
        dvd_mode = str(payload.get('dvdMode') or 'independent')
        if dvd_mode not in ('independent', 'reinforcement'):
            raise ValueError(f'unknown DVD mode: {dvd_mode}')
        if len(devices) > 64 or len({d.id for d in devices}) != len(devices):
            raise ValueError('maximum 64 devices; ids must be unique')
        self.name = str(payload.get('name') or 'Virtual Orchestra')[:100]
        self.dvd_mode = dvd_mode
        self.master_volume = master
        self.hdd_mode = hdd_mode
        self.tonal_mode = tonal_mode
        self.source_continuity = bool(payload.get('sourceContinuity', False))
        self.source_continuity_amount = amount
        self.tray_enabled = bool(payload.get("trayEnabled", True))
        from .orchestra import parse_idle
        self.idle_reinforcement = parse_idle(payload.get('idleReinforcement'))
        self.tray_movements = []
        self.devices = devices
        self.report = {}
        self.events = []
        self.activity = {}
        self.decisions = {}

    def config(self) -> dict:
        return {'name': self.name, 'dvdMode': self.dvd_mode, 'masterVolume': self.master_volume, 'hddMode': self.hdd_mode, 'tonalMode': self.tonal_mode, 'sourceContinuity': self.source_continuity, 'sourceContinuityAmount': self.source_continuity_amount,
                'trayEnabled': self.tray_enabled, 'idleReinforcement': self.idle_reinforcement,
                'devices': [dataclasses.asdict(d) for d in self.devices]}

    def load_plan(self, plan) -> 'VirtualOrchestra':
        """Podmienia sklad orkiestry na ten z planu wykonania."""
        self.source_continuity = bool(plan.policy.get('sourceContinuity', False))
        self.source_continuity_amount = float(plan.policy.get('sourceContinuityAmount', 1.))
        self.name = plan.name
        self.dvd_mode = plan.dvd_mode
        self.tray_enabled = plan.tray_enabled
        self.idle_reinforcement = plan.idle_reinforcement
        self.tray_movements = plan.tray_events
        self.devices = [VirtualDeviceInstance.parse(device) for device in plan.devices]
        self.report = {}
        self.events = []
        self.activity = {device.id: [] for device in self.devices}
        self.decisions = {}

        return self

    def render_plan(self, plan) -> Timeline:
        """Wykonuje GOTOWY plan: symuluje mechanike, nie podejmuje decyzji.

        To jest granica miedzy aranzerem a sprzetem. Plan juz wie, ktore
        urzadzenie gra jaka nute i od kiedy; tutaj sprawdzamy tylko, jak
        zachowa sie mechanika (kroki, travel, zawracanie, cykl uderzenia)
        i produkujemy zdarzenia dla audio oraz dla schedulera sprzetowego.

        Nie ma tu ani jednego "dropu z powodu polifonii" - jesli plan jest
        poprawny, kazde jego zdarzenie jest zagrane.
        """
        self.load_plan(plan)
        self.tonal_decisions, self.strum_groups = resolve_tonal(plan)
        by_device: dict[str, list] = {device.id: [] for device in self.devices}

        for event in plan.events:
            if event.device_id is not None and event.outcome != 'DROPPED':
                by_device.setdefault(event.device_id, []).append(event)

        for device in self.devices:
            by_device[device.id].sort(key=lambda item: (item.actual_start, item.id))

        audible_solo = any(d.solo and not d.mute for d in self.devices)
        durations = [event.actual_duration for event in plan.events if event.played]

        for device in self.devices:
            profile = effective_profile(device)
            state = MechanicalState(profile)
            counts = dict(accepted=0, played=0, dropped=0, folded=0, delayed=0,
                          busyConflicts=0, polyphonyConflicts=0, retriggerConflicts=0,
                          steps=0, reversals=0, travel=0, activeTime=0.0,
                          requestedHits=0, acceptedHits=0, droppedWhileBusy=0,
                          busyTime=0.0, maxDensity=0.0)
            reasons: dict[str, int] = {}
            phases: list[dict] = []
            audible = not device.mute and (not audible_solo or device.solo)
            last_hit: float | None = None

            for event in by_device.get(device.id, []):
                counts['accepted'] += 1
                counts['played'] += 1
                reasons[event.outcome] = reasons.get(event.outcome, 0) + 1

                if event.folded:
                    counts['folded'] += 1

                if event.outcome == 'DELAYED':
                    counts['delayed'] += 1
                elif event.outcome == 'ARPEGGIATED':
                    counts['delayed'] += 1
                    counts['retriggerConflicts'] += 1

                start = event.actual_start
                duration = event.actual_duration
                self.decisions.setdefault(event.id, []).append({
                    'deviceId': device.id, 'ruleId': event.rule_id,
                    'articulation': event.articulation, 'status': event.status,
                    'reason': event.outcome, 'outcome': event.outcome,
                    'originalNote': event.note, 'playedNote': event.played_note,
                    'deviceAvailableAt': None,
                    'tonalArticulation': (self.tonal_decisions[event.id].debug()
                                          if event.id in self.tonal_decisions else None),
                })

                if device.type in ('HDD_VCM', 'SOLENOID_RESONATOR'):
                    counts['requestedHits'] += 1
                    counts['acceptedHits'] += 1
                    cycle = max(duration, 0.0)
                    counts['busyTime'] += cycle

                    if last_hit is not None and start > last_hit:
                        counts['maxDensity'] = max(counts['maxDensity'], 1 / (start - last_hit))

                    last_hit = start

                    if device.type == 'HDD_VCM':
                        park = float(profile.get('parkMs') or 0) / 1000
                        settle = float(profile.get('settleMs') or 0) / 1000
                        strike = float(profile.get('strikeMs') or 0) / 1000
                        phases.extend([
                            {'time': start, 'phase': 'PARK'},
                            {'time': start + park, 'phase': 'SETTLE'},
                            {'time': start + park + settle, 'phase': 'STRIKE'},
                            {'time': start + park + settle + strike, 'phase': 'COOLDOWN'},
                        ])

                    if audible:
                        self.activity[device.id].append((start, max(start + cycle, start + .22)))
                        self.events.append(AcousticEvent(
                            start + float(profile.get('parkMs') or 0) / 1000
                            + float(profile.get('settleMs') or 0) / 1000,
                            'hit', device.id, 0.0, duration, event.velocity,
                            hdd_articulation=(classify_hdd(event.note, event.channel, event.velocity, event.articulation)
                                              if device.type == 'HDD_VCM' else None), source_id=event.id,
                            source_note=event.note, source_channel=event.channel, source_track=event.track_name))

                    continue

                hz = event.played_hz or 0.0
                counts['activeTime'] += duration
                state.playing = state.running = True
                state.current_frequency = state.target_frequency = hz

                if device.type in ('FDD', 'DVD_SLED', 'STEPPER_FREE') and hz > 0:
                    steps = int(duration * hz)
                    counts['steps'] += steps
                    counts['travel'] += steps
                    low, high = profile.get('minPosition'), profile.get('maxPosition')

                    if low is not None and high is not None and high > low:
                        for step in range(steps):
                            if ((state.direction > 0 and state.position >= high)
                                    or (state.direction < 0 and state.position <= low)):
                                state.direction *= -1
                                counts['reversals'] += 1
                                reasons['DIRECTION_REVERSAL'] = reasons.get('DIRECTION_REVERSAL', 0) + 1

                                if audible:
                                    self.events.append(AcousticEvent(
                                        start + step / hz, 'reversal', device.id))

                            state.position += state.direction

                if audible:
                    self.activity[device.id].append((start, start + duration))
                    self.events.append(AcousticEvent(start, 'tone', device.id, hz,
                                                     duration, event.velocity, source_id=event.id,
                        source_note=event.note, source_channel=event.channel, source_track=event.track_name,
                        tonal_articulation=self.tonal_decisions.get(event.id)))

            state.playing = state.running = False
            state.phase = 'IDLE'
            self.report[device.id] = {'name': device.name, 'type': device.type, **counts,
                                      'reasons': reasons, 'state': vars(state).copy(),
                                      'phases': phases, 'reinforcementEvents': 0,
                                      'reinforcementTime': 0.0}

        # Acoustic-only extras: normal commands and their statistics are already
        # fixed. The pass guarantees these intervals never overlap normal DVD notes.
        by_id = {device.id: device for device in self.devices}
        sources = {e.id: e for e in plan.events}
        audible_solo = any(device.solo and not device.mute for device in self.devices)
        for extra in plan.reinforcements:
            device = by_id[extra.device_id]
            report = self.report[device.id]
            report['reinforcementEvents'] += 1
            report['reinforcementTime'] += extra.duration
            if not device.mute and (not audible_solo or device.solo):
                self.activity[device.id].append((extra.start, extra.start + extra.duration))
                self.events.append(AcousticEvent(extra.start, extra.kind, device.id,
                                                 extra.hz, extra.duration, extra.velocity,
                    hdd_articulation=(classify_hdd(sources[extra.source_id].note, sources[extra.source_id].channel,
                        sources[extra.source_id].velocity, sources[extra.source_id].articulation)
                        if device.type == 'HDD_VCM' else None),
                    source_id=extra.source_id, reinforcement=True, source_note=sources[extra.source_id].note,
                    source_channel=sources[extra.source_id].channel, source_track=sources[extra.source_id].track_name,
                    tonal_articulation=(retarget_tonal(self.tonal_decisions[extra.source_id],
                        device.type, extra.duration, extra.velocity,
                        extra.start-sources[extra.source_id].actual_start)
                        if extra.kind == "tone" and extra.source_id in self.tonal_decisions else None)))
        for extra in plan.tray_events:
            report = self.report[extra.device_id]
            report['reinforcementEvents'] += 1
            report['reinforcementTime'] += extra.duration
            self.activity[extra.device_id].append((extra.start, extra.start + extra.duration))
            self.events.append(AcousticEvent(extra.start, 'tray', extra.device_id,
                                             duration=extra.duration, velocity=extra.velocity,
                                             direction=extra.direction))
        for intervals in self.activity.values():
            intervals.sort()

        end = max(float(getattr(plan, 'duration', 0.0)),
                  max((e.time + e.tonal_articulation.gate + e.tonal_articulation.release
                       for e in self.events if e.tonal_articulation is not None and not e.reinforcement), default=0.0),
                  max((e.time + (e.duration if e.kind in ('tone', 'tray') else .12)
                       for e in self.events), default=0.0),
                  max((interval[1] for intervals in self.activity.values()
                       for interval in intervals), default=0.0))
        commands = [Command(e.time, 'virtual', lane='virtual') for e in self.events]

        if end:
            if not commands:
                commands.append(Command(0, 'virtual', lane='virtual'))

            commands.append(Command(end, 'virtual', lane='virtual'))

        return Timeline.from_commands(commands)

    def tray_state_at(self, position: float) -> dict:
        result = {device.id: {'phase': 'idle'} for device in self.devices if device.type == 'DVD_TRAY'}
        for event in self.tray_movements:
            if event.start <= position < event.start + event.duration + event.cooldown:
                result[event.device_id] = {**event.as_dict(), 'phase':
                    'moving' if position < event.start + event.duration else 'recovery'}
        return result

    def simulate(self, source: MidiSource, routes_by_device: dict | None = None) -> Timeline:
        self.events = []
        self.activity = {device.id: [] for device in self.devices}
        self.decisions = {}
        report = {}
        audible_solo = any(d.solo and not d.mute for d in self.devices)
        for device in self.devices:
            profile = effective_profile(device)
            state = MechanicalState(profile)
            counts = dict(accepted=0, played=0, dropped=0, folded=0, delayed=0,
                          busyConflicts=0, polyphonyConflicts=0, retriggerConflicts=0,
                          steps=0, reversals=0, travel=0, activeTime=0.0,
                          requestedHits=0, acceptedHits=0, droppedWhileBusy=0, busyTime=0.0,
                          maxDensity=0.0)
            reasons: dict[str, int] = {}
            phases: list[dict] = []
            def reason(code):
                reasons[code] = reasons.get(code, 0) + 1
            if device.type == 'DVD_TRAY' or (device.track is None and routes_by_device is None):
                report[device.id] = {'name': device.name, 'type': device.type, **counts,
                                     'reasons': reasons, 'state': vars(state).copy(), 'phases': phases}
                continue
            if routes_by_device is None and device.track >= len(source.tracks):
                reason('TRACK_UNAVAILABLE')
                report[device.id] = {'name': device.name, 'type': device.type, **counts,
                                     'reasons': reasons, 'state': vars(state).copy(), 'phases': phases}
                continue
            incoming = (routes_by_device.get(device.id, []) if routes_by_device is not None
                        else source.notes(device.track))
            def priority(item):
                strategy = getattr(item, 'strategy', 'first')
                if strategy == 'highest': return -item.note
                if strategy == 'lowest': return item.note
                if strategy == 'last': return -item.order
                return item.order
            notes = sorted(incoming, key=lambda n: (n.start, priority(n), n.order))
            active_until = 0.0
            last_hit: float | None = None
            for incoming_note in notes:
                span = getattr(incoming_note, 'span', incoming_note)
                note_id = getattr(incoming_note, 'note_id', None)
                folded_flag = False
                delayed_flag = False
                def decision(status, code=None, hz_played=None, available_at=None):
                    if note_id is not None:
                        self.decisions.setdefault(note_id, []).append({
                            'deviceId': device.id, 'ruleId': incoming_note.rule_id,
                            'articulation': incoming_note.articulation,
                            'status': status, 'reason': code,
                            'originalNote': span.note,
                            'playedNote': round(hz_to_midi(hz_played)) if hz_played else None,
                            'deviceAvailableAt': available_at,
                        })
                start = span.start
                duration = span.duration * device.gate * getattr(incoming_note, 'gate', 1.0)
                if duration <= 0:
                    decision('DROPPED', 'ZERO_DURATION')
                    continue
                if device.type in TONAL and start < active_until - 1e-6:
                    counts['dropped'] += 1; counts['polyphonyConflicts'] += 1; reason('NOTE_DROPPED_POLYPHONY')
                    decision('DROPPED', 'NOTE_DROPPED_POLYPHONY', available_at=active_until)
                    continue
                note = span.note + device.transpose + getattr(incoming_note, 'transpose', 0)
                hz = midi_to_hz(note)
                lo, hi = profile.get('minHz'), profile.get('maxHz')
                if lo is not None and hi is not None and (hz < lo or hz > hi):
                    if profile.overflow == 'fold' and getattr(incoming_note, 'octave_fold', True):
                        candidates = [(abs(shift), midi_to_hz(note + shift)) for shift in range(-120, 121, 12)
                                      if lo <= midi_to_hz(note + shift) <= hi]
                        if candidates:
                            hz = min(candidates)[1]
                            folded_flag = True
                            counts['folded'] += 1; reason('NOTE_FOLDED')
                        else:
                            counts['dropped'] += 1; reason('NOTE_OUT_OF_RANGE'); decision('DROPPED', 'NOTE_OUT_OF_RANGE'); continue
                    else:
                        counts['dropped'] += 1; reason('NOTE_OUT_OF_RANGE'); decision('DROPPED', 'NOTE_OUT_OF_RANGE'); continue
                fixed = profile.get('fixedMidiNote')
                if fixed is not None and note != fixed:
                    counts['dropped'] += 1; reason('NOTE_OUT_OF_RANGE'); decision('DROPPED', 'NOTE_OUT_OF_RANGE'); continue
                if device.type in ('HDD_VCM', 'SOLENOID_RESONATOR'):
                    counts['requestedHits'] += 1
                    cycle = 0.0
                    sound_time = start
                    if device.type == 'HDD_VCM':
                        cycle = sum(float(profile.get(k) or 0) for k in ('parkMs', 'settleMs', 'strikeMs', 'cooldownMs')) / 1000
                    else:
                        cycle = float(profile.get('minRetriggerMs') or 0) / 1000
                    if start < state.busy_until - 1e-6:
                        counts['busyConflicts'] += 1; reason('DEVICE_BUSY')
                        if profile.busy_policy in ('delay', 'queue'):
                            start = state.busy_until
                            delayed_flag = True
                            counts['delayed'] += 1; reason('NOTE_DELAYED')
                        else:
                            counts['droppedWhileBusy'] += 1; counts['dropped'] += 1
                            reason('NOTE_DROPPED_RETRIGGER' if device.type == 'SOLENOID_RESONATOR' else 'DEVICE_BUSY_DROP')
                            decision('DROPPED', 'DEVICE_BUSY', available_at=state.busy_until)
                            continue
                    state.busy_until = start + cycle
                    if last_hit is not None and start > last_hit:
                        counts['maxDensity'] = max(counts['maxDensity'], 1 / (start - last_hit))
                    last_hit = start
                    if device.type == 'HDD_VCM':
                        park = float(profile.get('parkMs') or 0) / 1000
                        settle = float(profile.get('settleMs') or 0) / 1000
                        strike = float(profile.get('strikeMs') or 0) / 1000
                        sound_time = start + park + settle
                        phases.extend([
                            {'time': start, 'phase': 'PARK'},
                            {'time': start + park, 'phase': 'SETTLE'},
                            {'time': start + park + settle, 'phase': 'STRIKE'},
                            {'time': start + park + settle + strike, 'phase': 'COOLDOWN'},
                            {'time': state.busy_until, 'phase': 'IDLE'},
                        ])
                    counts['busyTime'] += cycle; counts['acceptedHits'] += 1
                    event_kind = 'hit'
                else:
                    event_kind = 'tone'
                    if device.type in ('FDD', 'DVD_SLED', 'STEPPER_FREE'):
                        rate = hz  # firmware: stepIntervalUs = 1e6 / hz; one STEP is one click
                        max_rate = profile.get('maxStepRate')
                        if max_rate is not None and rate > max_rate:
                            counts['dropped'] += 1; reason('NOTE_OUT_OF_RANGE'); decision('DROPPED', 'NOTE_OUT_OF_RANGE'); continue
                        steps = int(duration * rate)
                        counts['steps'] += steps; counts['travel'] += steps
                        low, high = profile.get('minPosition'), profile.get('maxPosition')
                        if low is not None and high is not None and high > low:
                            for step in range(steps):
                                if (state.direction > 0 and state.position >= high) or (state.direction < 0 and state.position <= low):
                                    state.direction *= -1
                                    counts['reversals'] += 1; reason('DIRECTION_REVERSAL')
                                    if not device.mute and (not audible_solo or device.solo):
                                        self.events.append(AcousticEvent(start + step / rate, 'reversal', device.id))
                                state.position += state.direction
                    active_until = start + duration
                    state.playing = state.running = True
                    state.current_frequency = state.target_frequency = hz
                    counts['activeTime'] += duration
                counts['accepted'] += 1; counts['played'] += 1; reason('NOTE_ACCEPTED')
                decision('DELAYED' if delayed_flag else 'FOLDED' if folded_flag else 'ACCEPTED',
                         'NOTE_DELAYED' if delayed_flag else 'NOTE_FOLDED' if folded_flag else 'NOTE_ACCEPTED', hz)
                if not device.mute and (not audible_solo or device.solo):
                    activity_end = (start + duration if event_kind == 'tone'
                                    else max(start + cycle, start + .22))
                    self.activity[device.id].append((start, activity_end))
                    self.events.append(AcousticEvent(sound_time if event_kind == 'hit' else start,
                                                     event_kind, device.id, hz, duration, span.velocity,
                        hdd_articulation=(classify_hdd(span.note, span.channel, span.velocity,
                            getattr(incoming_note, 'articulation', None)) if device.type == 'HDD_VCM' else None),
                        source_id=note_id, source_note=span.note, source_channel=span.channel))
            state.playing = state.running = False
            state.phase = 'IDLE'
            report[device.id] = {'name': device.name, 'type': device.type, **counts,
                                 'reasons': reasons, 'state': vars(state).copy(), 'phases': phases}
        self.report = report
        # Scheduler remains the PlaybackEngine worker; virtual commands are its clock markers.
        commands = [Command(e.time, 'virtual', lane='virtual') for e in self.events]
        end = max(float(getattr(source, 'duration', 0)),
                  max((e.time + (e.duration if e.kind in ('tone', 'tray') else .12) for e in self.events), default=0.0),
                  max((interval[1] for intervals in self.activity.values() for interval in intervals), default=0.0))
        if end:
            if not commands:
                commands.append(Command(0, 'virtual', lane='virtual'))
            commands.append(Command(end, 'virtual', lane='virtual'))
        return Timeline.from_commands(commands)

    def active_at(self, position: float, *, visual_hold: float = 0.0) -> dict[str, bool]:
        """LED states from accepted work; a short hold makes brief hits visible in the UI."""
        result = {}
        for device in self.devices:
            intervals = self.activity.get(device.id, [])
            index = bisect.bisect_right(intervals, (position, float('inf'))) - 1
            result[device.id] = index >= 0 and position < intervals[index][1] + visual_hold
        return result

class WavePreview:
    """Disposable host-side PCM preview. Renderer consumes only accepted mechanical events."""
    RATE = 22050

    def __init__(self, *, clocked: bool = False):
        self.clocked = clocked
        self._audio_anchor = None
        self._audio_start = None
        self._audio_end = 0.0
        self.audio_events = []
        self.master_volume = 1.0
        self.process: subprocess.Popen | None = None
        self.path: Path | None = None

    def stop(self):
        self._audio_start = None
        self._audio_anchor = None
        if self.process is not None:
            self.process.terminate()
            try: self.process.wait(timeout=.5)
            except subprocess.TimeoutExpired: self.process.kill()
            self.process = None

    def close(self):
        self.stop()
        if hasattr(self, '_slice'):
            self._slice.unlink(missing_ok=True)
            del self._slice
        if self.path:
            self.path.unlink(missing_ok=True)
            self.path = None

    def _plan(self, orchestra: VirtualOrchestra, n: int) -> list[tuple]:
        """Zdarzenia do policzenia: (urzadzenie, profil, event, start, dlugosc).

        Instancje 'real' graja na prawdziwym sprzecie - podglad audio ich nie
        dubluje. Dzieki temu 'hybrid' nie brzmi podwojnie.
        """
        by_id = {d.id: d for d in orchestra.devices}
        ordinary = []
        hdd = {}
        tonal = {}
        self.tonal_stats = {'events': [], 'retriggers': 0, 'suppressedReinforcement': 0}
        self.hdd_stats = {'events': [], 'chokes': 0, 'suppressedReinforcement': 0}
        for event in orchestra.events:
            d = by_id[event.device]
            if not d.in_preview:
                continue
            # Reversals describe actuator travel, not an additional MIDI sound.
            # The former synthetic 1700 Hz knock dominated sustained FDD notes.
            # Keep mechanical events/statistics, but omit that uncalibrated audio.
            if event.kind == 'reversal':
                continue
            if event.kind == 'tone':
                tonal.setdefault(d.id, []).append(event)
            elif d.type == 'HDD_VCM' and event.kind == 'hit':
                if event.hdd_articulation is None:
                    raise ValueError('HDD hit is missing its domain articulation')
                hdd.setdefault(d.id, []).append(event)
            else:
                start = int(event.time * self.RATE)
                length = min(n - start, int((event.duration if event.kind in ('tone', 'tray') else .12) * self.RATE))
                if length > 0:
                    ordinary.append((d, effective_profile(d), event, start, length))
        for ident, tones in tonal.items():
            d = by_id[ident]
            tones.sort(key=lambda e: (e.time, e.reinforcement))
            next_primary = None
            upcoming = [None]*len(tones)
            for i in range(len(tones)-1, -1, -1):
                upcoming[i] = next_primary
                if not tones[i].reinforcement: next_primary = tones[i]
            lane = []
            for i, event in enumerate(tones):
                start = int(event.time*self.RATE)
                art = event.tonal_articulation
                if art is None:
                    # Manual legacy simulation has no semantic PerformancePlan.
                    art = TonalArticulation('CONTINUOUS', d.type, .006, .1, .7, .035,
                        event.duration, .5, .15, (event.velocity/127)**.65,
                        source_duration=event.duration, velocity=event.velocity,
                        frequency=Curve((0.,),(event.hz,)))
                art = apply_tonal_mode(art, orchestra.tonal_mode)
                duration = art.gate+art.release
                if event.reinforcement:
                    if lane and not lane[-1][2].reinforcement and lane[-1][3]+lane[-1][4]>start:
                        self.tonal_stats['suppressedReinforcement'] += 1
                        continue
                    if upcoming[i]: duration=min(duration, max(0.,upcoming[i].time-event.time))
                    duration=min(duration,event.duration) # never extend extra beyond its reservation
                length=min(n-start,int(duration*self.RATE))
                if length<=0: continue
                if lane and lane[-1][3]+lane[-1][4]>start:
                    previous=lane[-1]
                    lane[-1]=(*previous[:4], max(0,start-previous[3]))
                    self.tonal_stats['retriggers']+=1
                event=dataclasses.replace(event,tonal_articulation=art)
                lane.append((d,effective_profile(d),event,start,length))
            for row in lane:
                event,start,length=row[2:]
                self.tonal_stats['events'].append(dict(event.tonal_articulation.debug(),
                    sourceId=event.source_id, track=event.source_track, start=event.time,
                    deviceId=ident, reinforcement=event.reinforcement, audioDuration=length/self.RATE,
                    truncated=length<int((event.tonal_articulation.gate+event.tonal_articulation.release)*self.RATE)))
            ordinary.extend(row for row in lane if row[4]>0)
        for ident, hits in hdd.items():
            d = by_id[ident]
            hits.sort(key=lambda e: (e.time, e.reinforcement))
            primary_indices = [i for i, event in enumerate(hits) if not event.reinforcement]
            primary_gaps = {}
            for position, i in enumerate(primary_indices):
                neighbors = [primary_indices[j] for j in (position-1, position+1)
                             if 0 <= j < len(primary_indices)]
                primary_gaps[i] = min((abs(hits[i].time-hits[j].time) for j in neighbors), default=math.inf)
            adapted = []
            for i, event in enumerate(hits):
                gaps = [abs(event.time - hits[j].time) for j in (i-1, i+1) if 0 <= j < len(hits)]
                # An optional extra must not change a normal hit's timbre/decay.
                gap = min(gaps, default=math.inf) if event.reinforcement else primary_gaps[i]
                art = adapt_hdd(event.hdd_articulation, gap, orchestra.hdd_mode == 'raw')
                adapted.append(dataclasses.replace(event, hdd_articulation=art))
            next_primaries = [None] * len(adapted)
            next_primary = None
            for i in range(len(adapted) - 1, -1, -1):
                next_primaries[i] = next_primary
                if not adapted[i].reinforcement:
                    next_primary = adapted[i]
            lane = []
            for i, event in enumerate(adapted):
                start = int(event.time * self.RATE)
                length = min(n - start, int(event.hdd_articulation.duration * self.RATE))
                if length <= 0:
                    continue
                # Acoustic extras cannot interrupt a normal actuator gesture/tail.
                if event.reinforcement and lane and not lane[-1][2].reinforcement and lane[-1][3] + lane[-1][4] > start:
                    self.hdd_stats['suppressedReinforcement'] += 1
                    continue
                if event.reinforcement:
                    next_primary = next_primaries[i]
                    if next_primary is not None:
                        length = min(length, max(0, int(next_primary.time * self.RATE) - start))
                if lane and lane[-1][3] + lane[-1][4] > start:
                    previous = lane[-1]
                    lane[-1] = (*previous[:4], max(0, start - previous[3]))
                    self.hdd_stats['chokes'] += 1
                lane.append((d, effective_profile(d), event, start, length))
            for item in lane:
                event, start, length = item[2:]
                art = event.hdd_articulation
                self.hdd_stats['events'].append({
                    'deviceId': ident, 'sourceId': event.source_id, 'reinforcement': event.reinforcement,
                    'note': event.source_note, 'channel': event.source_channel, 'track': event.source_track,
                    'start': event.time, 'duration': length / self.RATE, 'articulation': art.kind,
                    'pitchBand': art.pitch_band, 'resonanceHz': art.resonance, 'decay': art.decay,
                    'raw': art.raw, 'choked': length < int(art.duration * self.RATE),
                })
            ordinary.extend(item for item in lane if item[4] > 0)
        return ordinary

    def _render_python(self, plan: list[tuple], n: int, mix_count: int) -> tuple:
        """Wersja bez zaleznosci: ~2-4 mln probek/s, wiec dlugi utwor trwa."""
        from .tray import tray_sound
        left = array('f', [0]) * n
        right = array('f', [0]) * n
        for d, profile, event, start, length in plan:
            gain = .12 * d.volume / max(1, mix_count)
            gl, gr = gain * (1 - max(0, d.pan)), gain * (1 + min(0, d.pan))
            for i in range(length):
                t = i / self.RATE
                if event.kind == 'tray':
                    sample = tray_sound(t, event.duration, event.velocity, profile, d.id, event.direction)
                elif event.kind == 'reversal':
                    sample = math.exp(-t * 85) * math.sin(2 * math.pi * 1700 * t)
                elif d.type == 'HDD_VCM' and event.kind == 'hit':
                    sample = sample_hdd(t, event.hdd_articulation, d.id)
                    sample *= min(1., (length - 1 - i) / max(1, int(.006 * self.RATE)))
                elif event.kind == 'hit':
                    resonance = 230 if d.type == 'HDD_VCM' else (profile.get('resonanceHz') or 440)
                    sample = math.exp(-t * 32) * (math.sin(2 * math.pi * resonance * t) + .25 * math.sin(2 * math.pi * resonance * 3 * t))
                    exponent = profile.get('velocityExponent') or .6
                    sample *= (event.velocity / 127) ** exponent
                elif event.kind == 'tone' and event.tonal_articulation is not None:
                    sample = render_tonal(t, event.tonal_articulation, event.hz, (length-1)/self.RATE)
                elif d.type == 'VHS':
                    sample = (math.sin(2 * math.pi * event.hz * t) + .2 * math.sin(2 * math.pi * event.hz * 3 * t)) * min(1, t * 40)
                else:
                    # Every audible cycle derives from a mechanical STEP impulse train.
                    rate = event.hz
                    pulse = math.exp(-((t * rate) % 1) * (14 if d.type == 'FDD' else 9))
                    resonance = 900 if d.type == 'FDD' else (1300 if d.type == 'DVD_SLED' else 600)
                    sample = pulse * (.55 + .45 * math.sin(2 * math.pi * resonance * t))
                left[start+i] += sample * gl; right[start+i] += sample * gr

        return left, right

    def _render_numpy(self, np, plan: list[tuple], n: int, mix_count: int) -> tuple:
        """Ta sama matematyka, wektorowo.

        Zmierzone (aranzacja 6 urzadzen): 5.7 s -> 0.20 s, a przy 40
        urzadzeniach 23.8 s -> 0.85 s. Zysk jest WYLACZNIE na pierwszym
        renderze po wczytaniu/edycji - kolejne `Play` korzysta z gotowego WAV.
        """
        left = np.zeros(n, dtype=np.float32)
        right = np.zeros(n, dtype=np.float32)
        for d, profile, event, start, length in plan:
            t = np.arange(length, dtype=np.float32) / self.RATE
            if event.kind == 'tray':
                from .tray import tray_sound
                sample = tray_sound(t, event.duration, event.velocity, profile, d.id, event.direction, np)
            elif event.kind == 'reversal':
                sample = np.exp(-t * 85) * np.sin(2 * np.pi * 1700 * t)
            elif d.type == 'HDD_VCM' and event.kind == 'hit':
                sample = sample_hdd(t, event.hdd_articulation, d.id, np)
                sample *= np.minimum(1., np.maximum(0., (length - 1 - np.arange(length)) / max(1, int(.006 * self.RATE))))
            elif event.kind == 'hit':
                resonance = 230 if d.type == 'HDD_VCM' else (profile.get('resonanceHz') or 440)
                sample = np.exp(-t * 32) * (np.sin(2 * np.pi * resonance * t) + .25 * np.sin(2 * np.pi * resonance * 3 * t))
                sample = sample * (event.velocity / 127) ** (profile.get('velocityExponent') or .6)
            elif event.kind == 'tone' and event.tonal_articulation is not None:
                sample = render_tonal(t, event.tonal_articulation, event.hz, (length-1)/self.RATE, np)
            elif d.type == 'VHS':
                sample = (np.sin(2 * np.pi * event.hz * t) + .2 * np.sin(2 * np.pi * event.hz * 3 * t)) * np.minimum(1, t * 40)
            else:
                rate = event.hz
                pulse = np.exp(-((t * rate) % 1) * (14 if d.type == 'FDD' else 9))
                resonance = 900 if d.type == 'FDD' else (1300 if d.type == 'DVD_SLED' else 600)
                sample = pulse * (.55 + .45 * np.sin(2 * np.pi * resonance * t))
            gain = .12 * d.volume / max(1, mix_count)
            gl, gr = gain * (1 - max(0, d.pan)), gain * (1 + min(0, d.pan))
            left[start:start+length] += sample * gl
            right[start:start+length] += sample * gr

        return left, right

    @staticmethod
    def _write(path: Path, left, right, n: int, np=None) -> None:
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(WavePreview.RATE)
            if np is not None:
                frames = np.empty(n * 2, dtype='<i2')
                frames[0::2] = (np.clip(left, -1, 1) * 32767).astype('<i2')
                frames[1::2] = (np.clip(right, -1, 1) * 32767).astype('<i2')
                wav.writeframes(frames.tobytes())
                return
            chunk = bytearray()
            for a, b in zip(left, right):
                chunk.extend(struct.pack('<hh', int(max(-1, min(1, a))*32767), int(max(-1, min(1, b))*32767)))
                if len(chunk) >= 65536:
                    wav.writeframes(chunk); chunk.clear()
            if chunk: wav.writeframes(chunk)

    def render(self, orchestra: VirtualOrchestra, duration: float):
        self.close()
        self.master_volume = orchestra.master_volume
        n = int((duration + .25) * self.RATE)
        # Dodatkowe ciche DVD nie obnizaja poziomu dotychczasowych FDD/VHS/HDD.
        mix_count = max(1, len([d for d in orchestra.devices
                                if d.in_preview and d.type not in ('DVD_SLED', 'DVD_TRAY')]))
        plan = self._plan(orchestra, n)
        # Exact audible intervals, including tails, chokes and suppressed extras.
        self.audio_events = [dataclasses.replace(row[2], duration=row[4] / self.RATE) for row in plan]

        try:
            import numpy as np
        except ImportError:
            np = None

        left, right = (self._render_numpy(np, plan, n, mix_count) if np is not None
                       else self._render_python(plan, n, mix_count))

        with tempfile.NamedTemporaryFile(prefix='virtual-orchestra-', suffix='.wav', delete=False) as tmp:
            path = Path(tmp.name)
        try:
            self._write(path, left, right, n, np)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        self.path = path

    def play(self, position: float):
        if not self.path:
            return
        self.stop()
        player = shutil.which('ffplay') if self.clocked else None
        if player:
            with wave.open(str(self.path), 'rb') as source:
                self._audio_end = source.getnframes() / source.getframerate()
            self._audio_start = position
            process = subprocess.Popen([player, '-nodisp', '-autoexit', '-hide_banner', '-stats',
                '-ss', str(position), '-af', f'volume={self.master_volume}', str(self.path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.process = process
            threading.Thread(target=self._read_audio_clock, args=(process,), daemon=True,
                             name='virtual-audio-clock').start()
            return
        # afplay has no seek option. A trimmed temporary slice is made on seek.
        with wave.open(str(self.path), 'rb') as source:
            source.setpos(min(source.getnframes(), int(position * source.getframerate())))
            frames = source.readframes(source.getnframes() - source.tell())
            params = source.getparams()
        with tempfile.NamedTemporaryFile(prefix='virtual-play-', suffix='.wav', delete=False) as tmp:
            play_path = Path(tmp.name)
        with wave.open(str(play_path), 'wb') as output:
            output.setparams(params); output.writeframes(frames)
        self.process = subprocess.Popen(['afplay', '-v', str(self.master_volume), str(play_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Process owns the open file; clean stale slices on next start/stop.
        if hasattr(self, '_slice'):
            self._slice.unlink(missing_ok=True)
        self._slice = play_path

    def _read_audio_clock(self, process):
        """ffplay reports the SDL output clock, corrected for queued audio samples."""
        line = bytearray()
        try:
            while process.stderr:
                byte = process.stderr.read(1)
                if not byte:
                    break
                if byte in (b'\r', b'\n'):
                    match = re.match(rb'\s*(\d+\.\d+)\s+M-A:', line)
                    if match and self.process is process and self._audio_start is not None:
                        self._audio_anchor = (float(match[1]), time.monotonic())
                    line.clear()
                elif len(line) < 4096:
                    line.extend(byte)
        finally:
            if process.stderr:
                process.stderr.close()

    def clock_position(self):
        """None for legacy afplay; freeze at seek target until audio actually starts."""
        if self._audio_start is None:
            return None
        anchor = self._audio_anchor
        if self.process and self.process.poll() == 0:
            return self._audio_end
        if anchor is None:
            return self._audio_start
        return max(self._audio_start, min(self._audio_end, anchor[0] + min(.12, max(0., time.monotonic() - anchor[1]))))

    @property
    def clock_running(self):
        return self._audio_start is None or (self._audio_anchor is not None and self._audio_anchor[0] >= self._audio_start)
