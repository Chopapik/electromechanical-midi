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
from pitch import COMFORT_MAX_HZ, COMFORT_MIN_HZ, hz_to_midi, midi_to_hz
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

    def playback_range(self):
        """Shared musical range; firmware limits remain separate hard bounds."""
        low, high = self.get('minHz'), self.get('maxHz')
        if self.kind == 'FDD':
            preferred_low = self.get('preferredMinHz')
            preferred_high = self.get('preferredMaxHz')
            if preferred_low is not None:
                low = max(low, preferred_low) if low is not None else preferred_low
            if preferred_high is not None:
                high = min(high, preferred_high) if high is not None else preferred_high
        return low, high

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
        'minPosition': _p(4, 'RESEARCHED', 'firmware/controller/src/main.cpp MIN_TRACK'),
        'maxPosition': _p(72, 'RESEARCHED', 'firmware/controller/src/main.cpp MAX_TRACK'),
        'minHz': _p(40, 'RESEARCHED', 'firmware MIN_PLAY_HZ'),
        'maxHz': _p(500, 'RESEARCHED', 'firmware MAX_PLAY_HZ'),
        'preferredMinHz': _p(COMFORT_MIN_HZ, 'RESEARCHED', 'host/pitch.py'),
        'preferredMaxHz': _p(COMFORT_MAX_HZ, 'MEASURED', 'README.md: Fizyczna kalibracja FDD; 410 Hz = 38/40, normal orientation'),
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
        'parkMs': _p(40, 'RESEARCHED', 'firmware/controller/src/main.cpp'),
        'settleMs': _p(40, 'RESEARCHED', 'firmware/controller/src/main.cpp'),
        'strikeMs': _p(2, 'RESEARCHED', 'firmware/controller/src/main.cpp; shorter impulse for quieter hardware hits'),
        'cooldownMs': _p(0, 'ESTIMATED', 'preview; calibrate separately'),
    }),
    'SOLENOID_REFERENCE': DeviceProfile('SOLENOID_REFERENCE', 'SOLENOID_RESONATOR', {
        'polyphony': _p(1, 'ESTIMATED', 'single actuator per instance'),
        'fixedMidiNote': _p(None), 'minRetriggerMs': _p(None),
        'resonanceHz': _p(None), 'velocityExponent': _p(.6, 'ESTIMATED', 'preview curve, not measured force'),
    }),
}
DEFAULT_PROFILE = {p.kind: p.id for p in PROFILES.values()}
# Separate controller profile: Uno calibration must not silently migrate to DRV8833.
PROFILES['DRV8833_HDD_START'] = DeviceProfile('DRV8833_HDD_START', 'HDD_VCM', {
    'polyphony': _p(1, 'ESTIMATED', 'one VCM per DRV8833 bridge'),
    'parkMs': _p(40, 'ESTIMATED', 'ESP32 bring-up; requires physical calibration'),
    'settleMs': _p(40, 'ESTIMATED', 'ESP32 bring-up; requires physical calibration'),
    'strikeMs': _p(4, 'ESTIMATED', 'ESP32 bring-up; requires physical calibration'),
    'cooldownMs': _p(0, 'ESTIMATED', 'requires physical calibration'),
})

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

    enabled: bool = True
    hardware_role: str = ''
    hardware_overrides: dict = dataclasses.field(default_factory=dict)

    @property
    def drives_hardware(self) -> bool:
        """Czy instancja ma wysylac komendy na fizyczna linie (Serial)."""
        return self.enabled and self.mode in ('real', 'hybrid')

    @property
    def in_preview(self) -> bool:
        """Czy instancja ma byc slyszalna w podgladzie audio (WAV)."""
        return self.enabled and self.mode in ('virtual', 'hybrid')

    @classmethod
    def parse(cls, data: dict) -> 'VirtualDeviceInstance':
        if not isinstance(data.get('enabled', True), bool):
            raise ValueError('device enabled must be boolean')
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
        hardware_role = data.get('hardwareRole', data.get('hardware_role', ''))
        if hardware_role and (kind != 'HDD_VCM' or hardware_role not in ('HDD_PERCUSSION', 'HDD_TONAL')):
            raise ValueError('invalid hardwareRole')
        hardware_overrides = data.get('hardwareOverrides', data.get('hardware_overrides', {}))
        if hardware_overrides or hardware_role:
            from .hardware_profiles import HardwareRegistry
            profile_name = hardware_role or {'FDD':'FDD','DVD_SLED':'DVD_SLED','HDD_VCM':'HDD_PERCUSSION','VHS':'VHS'}.get(kind)
            if not profile_name: raise ValueError('no physical profile for device')
            HardwareRegistry().effective(profile_name, overrides=hardware_overrides)
        return cls(ident, kind, str(data.get('name') or kind)[:80], track,
                   str(data.get('role') or '')[:80], volume, pan,
                   bool(data.get('mute', False)), bool(data.get('solo', False)),
                   transpose, gate, profile, mode, overrides, data.get('enabled', True), hardware_role, hardware_overrides)

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
        self.tray_movements = [e for e in plan.tray_events if any(d['id'] == e.device_id and d.get('enabled', True) for d in plan.devices)]
        self.devices = [VirtualDeviceInstance.parse(device) for device in plan.devices if device.get('enabled', True)]
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

        audible_solo = any(d.enabled and d.solo and not d.mute for d in self.devices)
        durations = [event.actual_duration for event in plan.events if event.played]

        for device in self.devices:
            if not device.enabled:
                continue
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
            device = by_id.get(extra.device_id)
            if device is None or not device.enabled:
                continue
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
            if extra.device_id not in by_id:
                continue
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
        audible_solo = any(d.enabled and d.solo and not d.mute for d in self.devices)
        for device in self.devices:
            if not device.enabled:
                continue
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
                lo, hi = profile.playback_range()
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
            result[device.id] = device.enabled and index >= 0 and position < intervals[index][1] + visual_hold
        return result
