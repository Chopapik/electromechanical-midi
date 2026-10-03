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
import tempfile
import wave
from pathlib import Path

from midi_source import MidiSource
from pitch import hz_to_midi, midi_to_hz
from .timeline import Command, Timeline

KINDS = ('FDD', 'DVD_SLED', 'STEPPER_FREE', 'VHS', 'HDD_VCM', 'SOLENOID_RESONATOR')
TONAL = {'FDD', 'DVD_SLED', 'STEPPER_FREE', 'VHS'}

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
        mode = str(data.get('mode') or 'virtual')
        if mode != 'virtual':
            raise ValueError('real/hybrid instances are reserved for a future hardware routing adapter')
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
        self.devices = devices or []
        self.report: dict = {}
        self.events: list[AcousticEvent] = []
        self.activity: dict[str, list[tuple[float, float]]] = {}
        self.decisions: dict[str, list[dict]] = {}

    def set_config(self, payload: dict) -> None:
        devices = [VirtualDeviceInstance.parse(item) for item in payload.get('devices', [])]
        if len(devices) > 64 or len({d.id for d in devices}) != len(devices):
            raise ValueError('maximum 64 devices; ids must be unique')
        self.name = str(payload.get('name') or 'Virtual Orchestra')[:100]
        self.devices = devices
        self.report = {}
        self.events = []
        self.activity = {}
        self.decisions = {}

    def config(self) -> dict:
        return {'name': self.name, 'devices': [dataclasses.asdict(d) for d in self.devices]}

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
            if device.track is None and routes_by_device is None:
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
                                                     event_kind, device.id, hz, duration, span.velocity))
            state.playing = state.running = False
            state.phase = 'IDLE'
            report[device.id] = {'name': device.name, 'type': device.type, **counts,
                                 'reasons': reasons, 'state': vars(state).copy(), 'phases': phases}
        self.report = report
        # Scheduler remains the PlaybackEngine worker; virtual commands are its clock markers.
        commands = [Command(e.time, 'virtual', lane='virtual') for e in self.events]
        end = max(float(getattr(source, 'duration', 0)),
                  max((e.time + (e.duration if e.kind == 'tone' else .12) for e in self.events), default=0.0),
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

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.path: Path | None = None

    def stop(self):
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

    def render(self, orchestra: VirtualOrchestra, duration: float):
        self.close()
        n = int((duration + .25) * self.RATE)
        left = array('f', [0]) * n; right = array('f', [0]) * n
        by_id = {d.id: d for d in orchestra.devices}
        for event in orchestra.events:
            d = by_id[event.device]
            profile = effective_profile(d)
            start = int(event.time * self.RATE)
            length = min(n - start, int((event.duration if event.kind == 'tone' else .12) * self.RATE))
            if length <= 0: continue
            gain = .12 * d.volume / max(1, len(orchestra.devices))
            gl, gr = gain * (1 - max(0, d.pan)), gain * (1 + min(0, d.pan))
            phase = 0.0
            for i in range(length):
                t = i / self.RATE
                if event.kind == 'reversal':
                    sample = math.exp(-t * 85) * math.sin(2 * math.pi * 1700 * t)
                elif event.kind == 'hit':
                    resonance = 230 if d.type == 'HDD_VCM' else (profile.get('resonanceHz') or 440)
                    sample = math.exp(-t * 32) * (math.sin(2 * math.pi * resonance * t) + .25 * math.sin(2 * math.pi * resonance * 3 * t))
                    exponent = profile.get('velocityExponent') or .6
                    sample *= (event.velocity / 127) ** exponent
                elif d.type == 'VHS':
                    sample = (math.sin(2 * math.pi * event.hz * t) + .2 * math.sin(2 * math.pi * event.hz * 3 * t)) * min(1, t * 40)
                else:
                    # Every audible cycle derives from a mechanical STEP impulse train.
                    rate = event.hz
                    pulse = math.exp(-((t * rate) % 1) * (14 if d.type == 'FDD' else 9))
                    resonance = 900 if d.type == 'FDD' else (1300 if d.type == 'DVD_SLED' else 600)
                    sample = pulse * (.55 + .45 * math.sin(2 * math.pi * resonance * t))
                left[start+i] += sample * gl; right[start+i] += sample * gr
        with tempfile.NamedTemporaryFile(prefix='virtual-orchestra-', suffix='.wav', delete=False) as tmp:
            path = Path(tmp.name)
        try:
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(self.RATE)
                chunk = bytearray()
                for a, b in zip(left, right):
                    chunk.extend(struct.pack('<hh', int(max(-1, min(1, a))*32767), int(max(-1, min(1, b))*32767)))
                    if len(chunk) >= 65536:
                        wav.writeframes(chunk); chunk.clear()
                if chunk: wav.writeframes(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        self.path = path

    def play(self, position: float):
        if not self.path:
            return
        self.stop()
        # afplay has no seek option. A trimmed temporary slice is made on seek.
        with wave.open(str(self.path), 'rb') as source:
            source.setpos(min(source.getnframes(), int(position * source.getframerate())))
            frames = source.readframes(source.getnframes() - source.tell())
            params = source.getparams()
        with tempfile.NamedTemporaryFile(prefix='virtual-play-', suffix='.wav', delete=False) as tmp:
            play_path = Path(tmp.name)
        with wave.open(str(play_path), 'wb') as output:
            output.setparams(params); output.writeframes(frames)
        self.process = subprocess.Popen(['afplay', str(play_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Process owns the open file; clean stale slices on next start/stop.
        if hasattr(self, '_slice'):
            self._slice.unlink(missing_ok=True)
        self._slice = play_path
