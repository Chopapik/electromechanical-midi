"""Device configuration and reference profiles shared by planning and preview."""
from __future__ import annotations
import dataclasses
import math
from pitch import COMFORT_MIN_HZ, COMFORT_MAX_HZ

KINDS = ('FDD', 'DVD_SLED', 'STEPPER_FREE', 'VHS', 'HDD_VCM', 'SOLENOID_RESONATOR')
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
class DeviceInstance:
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
    def parse(cls, data: dict) -> 'DeviceInstance':
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
        if not (0 <= volume <= (2.5 if kind=='VHS' else 1) and -1 <= pan <= 1 and 0 < gate <= 2):
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

def effective_profile(device: DeviceInstance) -> DeviceProfile:
    base = PROFILES[device.profile or DEFAULT_PROFILE[device.type]]
    return dataclasses.replace(base, parameters={**base.parameters, **device.overrides})


# Compatibility name for older CLI and third-party arrangement consumers.
VirtualDeviceInstance = DeviceInstance
