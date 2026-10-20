"""Konfiguracja orkiestry - CO mamy, niezaleznie od tego, CO gramy.

Rozdzielone sa dwie rzeczy, ktore wczesniej byly sklejone w song-specific
JSON-ie:

  * ``OrchestraConfig`` - dostepny sprzet i polityka (stale dla uzytkownika),
  * ``PerformancePlan`` - co ten sprzet faktycznie zagra w danym utworze.

Dzieki temu uzytkownik wrzuca MIDI i naciska Play; plan powstaje sam.
"""
from __future__ import annotations

import dataclasses

from .virtual import PROFILES, VirtualDeviceInstance

# Preset BALANCED: chroni lead i bas, korzysta z kazdego wolnego urzadzenia,
# dopuszcza krotkie przesuniecie, dropuje dopiero w ostatecznosci.
BALANCED = {
    'mode': 'balanced',
    'mechanicalAware': True,
    'dvdSustainThresholdMs': 500.,
    'dvdContinuousSustain': False,
    'dvdDynamicAware': True,
    'dvdMaxBridgeMs': 200.,
    'dvdBackgroundMaxBridgeMs': 350.,
    'mechanicalPhraseWindowMs': 1500.,
    'mechanicalPreferenceWeight': .8,
    'partContinuityWeight': .12,
    'sustainCompetitionTolerance': 8.,
    'fddUnisonEnabled': True,
    'fddUnisonMaxVoices': 2,
    'fddUnisonMinVelocity': 90.,
    'fddUnisonMaxDurationMs': 800.,
    'fddMinAttackIntervalMs': 120.,
    'fddFixedToneMs': 0.,
    'preserveLead': True,
    'preserveBass': True,
    'maxMicroDelayMs': 30.0,
    'maxArpeggioMs': 90.0,
    # Lead na VHS: tylko minimalna korekta czasu, zero arpeggio.
    'leadMaxMicroDelayMs': 12.0,
    'allowVoiceSteal': True,
    'stealMargin': 12.0,
    'tonalOverflow': 'adaptive',
    'percussionOverflow': 'nearest-free',
    'foldMode': 'auto',
    'softenRepeats': True,
    # FDD mechanical sustain: MIDI gitary to krotkie szarpniecia, a stacja
    # nie ma naturalnego wybrzmienia. Krotkie nuty dostaja dluzszy NOTE_OFF
    # (bez ruszania NOTE_ON) wypelniajacy przerwe do nastepnej nuty.
    'mechanicalSustain': True,
    'sourceContinuity': False,
    'sourceContinuityAmount': 1.0,
    'minMechanicalSustainMs': 120.0,
    'preferredMechanicalSustainMs': 190.0,
    'releaseGapMs': 3.0,
    'maxSustainExtensionMs': 200.0,
    'maxNoteSeconds': 0.0,      # 0 = arranger wylicza sam (akompaniament)
    'leadMaxNoteSeconds': 0.0,  # 0 = arranger wylicza sam (lead na VHS)
    # Budzet dlugosci nut: ile pojemnosci orkiestry moze zajac suma nut.
    # Nizej = mniej dropow, ale rzadsza faktura; wyzej = odwrotnie.
    'capacitySafety': 1.15,
}

from .fdd_quality import DEFAULTS as FDD_QUALITY_DEFAULTS
BALANCED.update(FDD_QUALITY_DEFAULTS)
_POLICY_KEYS = frozenset(BALANCED)


IDLE_DEFAULTS = {
    'enabled': False, 'maxCopiesPerEvent': 1, 'lookAheadMs': 80.0,
    'deviceTypes': ['FDD', 'DVD_SLED', 'HDD_VCM'],
    'minScore': 75.0, 'minDurationMs': 40.0, 'percussionCooldownMs': 250.0, 'vhsEnabled': False,
}


def parse_idle(payload=None):
    if payload is not None and not isinstance(payload, dict):
        raise ValueError('idleReinforcement must be an object')
    config = {**IDLE_DEFAULTS, **(payload or {})}
    if set(config) - set(IDLE_DEFAULTS):
        raise ValueError('unknown idleReinforcement setting')
    count = config['maxCopiesPerEvent']
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 2:
        raise ValueError('maxCopiesPerEvent must be 0, 1 or 2')
    for key in ('lookAheadMs', 'minScore', 'minDurationMs', 'percussionCooldownMs'):
        config[key] = float(config[key])
        if not 0 <= config[key] <= 10000:
            raise ValueError(f'invalid idleReinforcement {key}')
    if (not isinstance(config['deviceTypes'], list)
            or any(kind not in ('FDD', 'DVD_SLED', 'HDD_VCM', 'VHS') for kind in config['deviceTypes'])):
        raise ValueError('invalid idleReinforcement deviceTypes')
    for key in ('enabled', 'vhsEnabled'):
        if not isinstance(config[key], bool):
            raise ValueError(f'idleReinforcement {key} must be boolean')
    return config


@dataclasses.dataclass
class OrchestraConfig:
    """Dostepne urzadzenia + polityka wykonania."""

    name: str = 'Balanced 4FDD + 4DVD + VHS + 4HDD'
    devices: list[dict] = dataclasses.field(default_factory=list)
    policy: dict = dataclasses.field(default_factory=lambda: dict(BALANCED))
    dvd_mode: str = 'independent'
    idle_reinforcement: dict = dataclasses.field(default_factory=parse_idle)

    hardware: dict = dataclasses.field(default_factory=dict)

    def instances(self) -> list[VirtualDeviceInstance]:
        return [VirtualDeviceInstance.parse(device) for device in self.devices]

    def as_dict(self) -> dict:
        return {'name': self.name, 'devices': self.devices, 'policy': self.policy,
                'hardware': self.hardware, 'dvdMode': self.dvd_mode, 'idleReinforcement': self.idle_reinforcement}

    def allocation_devices(self) -> tuple[list[VirtualDeviceInstance], dict[str, list[dict]]]:
        """Reinforcement never changes the configured normal voice inventory."""
        if self.dvd_mode not in ('independent', 'reinforcement'):
            raise ValueError(f'unknown DVD mode: {self.dvd_mode}')
        devices = [device for device in self.instances() if device.enabled]
        return devices, {}


def _device(ident: str, kind: str, profile: str, name: str, mode: str = 'virtual') -> dict:
    return {'id': ident, 'type': kind, 'name': name, 'track': None, 'role': '',
            'volume': 0.2 if kind == 'DVD_SLED' else 0.6,
            'pan': 0.0, 'mute': False, 'solo': False,
            'transpose': 0, 'gate': 1.0, 'profile': profile, 'mode': mode,
            'overrides': {}, 'enabled': True, 'hardware_role': '', 'hardware_overrides': {}}


def default_orchestra(*, dvd_count: int = 4, dvd_mode: str = 'independent',
                      fdd_count: int = 4, hdd_count: int = 4) -> OrchestraConfig:
    """Configurable software inventory; saved explicit device lists stay intact."""
    counts = (fdd_count, dvd_count, hdd_count)
    if any(not isinstance(count, int) or count < 0 for count in counts) or sum(counts) + 1 > 64:
        raise ValueError('device counts must be nonnegative integers; maximum 64 devices')
    if dvd_mode not in ('independent', 'reinforcement'):
        raise ValueError(f'unknown DVD mode: {dvd_mode}')
    devices: list[dict] = []
    counters: dict[str, int] = {}

    inventory = (('FDD', fdd_count, 'FDD_CURRENT'), ('DVD_SLED', dvd_count, 'DVD_REFERENCE'),
                 ('VHS', 1, 'VHS_CURRENT'), ('HDD_VCM', hdd_count, 'WD_CAVIAR_CURRENT'))
    for kind, count, profile in inventory:
        if profile not in PROFILES:
            raise ValueError(f'brak profilu {profile} dla {kind}')

        for _ in range(count):
            counters[kind] = counters.get(kind, 0) + 1
            number = counters[kind]
            ident = f'DVD_STEPPER_{number}' if kind == 'DVD_SLED' else f'{kind.lower()}-{number}'
            label = 'DVD Stepper' if kind == 'DVD_SLED' else kind
            devices.append(_device(ident, kind, profile, f'{label} {number}' if kind.startswith('DVD') else f'{label} #{number}'))

    return OrchestraConfig(
        name=f'Balanced {fdd_count}FDD + {dvd_count}DVD + VHS + {hdd_count}HDD',
        devices=devices, policy=dict(BALANCED), dvd_mode=dvd_mode)


def parse_policy(payload: dict | None) -> dict:
    """Uzupelnia polityke o domyslne BALANCED, odrzuca nieznane klucze."""
    policy = dict(BALANCED)

    for key, value in (payload or {}).items():
        if key not in _POLICY_KEYS:
            raise ValueError(f'nieznany klucz polityki: {key}')

        policy[key] = value

    if policy['arrangementPreset'] not in ('balanced','fdd_quality','dvd_lead_low_fdd','fdd_quality_adaptive','instrument_roles','instrument_roles_unison','instrument_roles_duet','instrument_roles_unison4','universal'):
        raise ValueError('Unknown arrangement preset')
    for key in FDD_QUALITY_DEFAULTS:
        if key=='arrangementPreset': continue
        policy[key]=float(policy[key])
        if not 0 < policy[key] < float('inf'): raise ValueError('Invalid '+key)
    for key in ('fddQualityDensity','fddQualityOptionalPriority','fddQualityUnisonPriority','fddQualityUnisonDuty'):
        if policy[key]>1: raise ValueError('Invalid '+key)
    for key in ('maxMicroDelayMs', 'maxArpeggioMs', 'stealMargin', 'maxNoteSeconds', 'leadMaxNoteSeconds',
                   'leadMaxMicroDelayMs', 'capacitySafety',
                   'dvdMaxBridgeMs', 'dvdBackgroundMaxBridgeMs', 'dvdSustainThresholdMs', 'mechanicalPhraseWindowMs', 'mechanicalPreferenceWeight',
                   'partContinuityWeight', 'sustainCompetitionTolerance', 'fddUnisonMinVelocity', 'fddUnisonMaxDurationMs',
                   'fddMinAttackIntervalMs', 'fddFixedToneMs',
                   'minMechanicalSustainMs', 'preferredMechanicalSustainMs',
                   'releaseGapMs', 'maxSustainExtensionMs', 'sourceContinuityAmount'):
        policy[key] = float(policy[key])

        if policy[key] < 0:
            raise ValueError(f'{key} nie moze byc ujemny')

    for key in ('preserveLead', 'preserveBass', 'allowVoiceSteal', 'softenRepeats',
                'dvdContinuousSustain', 'dvdDynamicAware', 'mechanicalSustain', 'sourceContinuity', 'mechanicalAware', 'fddUnisonEnabled'):
        policy[key] = bool(policy[key])

    import math
    if any(isinstance(v, float) and not math.isfinite(v) for v in policy.values()):
        raise ValueError('policy numbers must be finite')
    if policy['dvdSustainThresholdMs'] <= 0 or policy['mechanicalPhraseWindowMs'] <= 0:
        raise ValueError('mechanical thresholds must be positive')
    if not 120 <= policy['fddMinAttackIntervalMs'] <= 1000:
        raise ValueError('fddMinAttackIntervalMs must be between 120 and 1000')
    if not 0 <= policy['fddFixedToneMs'] <= 5000:
        raise ValueError('fddFixedToneMs must be between 0 and 5000')
    if isinstance(policy['fddUnisonMaxVoices'], bool) or not isinstance(policy['fddUnisonMaxVoices'], int) or policy['fddUnisonMaxVoices'] not in (1, 2):
        raise ValueError('fddUnisonMaxVoices must be 1 or 2')
    if not 0 <= policy['fddUnisonMinVelocity'] <= 127:
        raise ValueError('fddUnisonMinVelocity must be between 0 and 127')
    if not 0 <= policy['sourceContinuityAmount'] <= 1:
        raise ValueError('sourceContinuityAmount must be between 0 and 1')

    if policy['mode'] not in ('balanced', 'melody', 'rhythm', 'strict'):
        raise ValueError(f'nieznany tryb polityki: {policy["mode"]}')

    return policy


def parse_orchestra(payload: dict | None) -> OrchestraConfig:
    """Buduje konfiguracje z JSON-a; brak pola devices = domyslna orkiestra."""
    payload = payload or {}
    hardware = payload.get('hardware', {})
    if not isinstance(hardware, dict) or set(hardware)-{'inventory'}:
        raise ValueError('invalid hardware configuration')
    inventory = hardware.get('inventory')
    if inventory is not None and (not isinstance(inventory, dict) or any(not isinstance(v, bool) or k.split(':')[0] not in ('fdd','sled','hdd','drum') or len(k.split(':'))!=2 or not k.split(':')[1].isdigit() for k,v in inventory.items())):
        raise ValueError('hardware inventory requires physical lane booleans')
    dvd_mode = str(payload.get('dvdMode') or 'independent')
    if dvd_mode not in ('independent', 'reinforcement'):
        raise ValueError(f'unknown DVD mode: {dvd_mode}')

    if 'devices' not in payload or payload['devices'] is None:
        config = default_orchestra()
        config.policy = parse_policy(payload.get('policy'))
        config.name = str(payload.get('name') or config.name)
        config.dvd_mode = dvd_mode
        config.idle_reinforcement = parse_idle(payload.get('idleReinforcement'))
        config.hardware = hardware
        config.allocation_devices()

        return config

    devices = [VirtualDeviceInstance.parse(device) for device in payload['devices']]

    if len(devices) > 64 or len({device.id for device in devices}) != len(devices):
        raise ValueError('maximum 64 devices; ids must be unique')

    config = OrchestraConfig(
        name=str(payload.get('name') or 'Orchestra')[:100],
        devices=[dataclasses.asdict(device) for device in devices],
        policy=parse_policy(payload.get('policy')),
        dvd_mode=dvd_mode,
        idle_reinforcement=parse_idle(payload.get('idleReinforcement')),
        hardware=hardware,
    )
    config.allocation_devices()
    return config


def web_startup_config() -> dict:
    """User-selected web player defaults; explicit presets/overrides stay editable."""
    orchestra = default_orchestra(dvd_mode='reinforcement')
    return {'name': orchestra.name, 'devices': orchestra.devices, 'enabled': True,
            'masterVolume': 19.5, 'tonalMode': 'extreme_v15', 'hddMode': 'articulated',
            'sourceContinuity': True, 'sourceContinuityAmount': 1.,
            'dvdMode': 'reinforcement',
            'idleReinforcement': parse_idle({'enabled': False})}


def esp32_startup_config() -> dict:
    """Explicit target preset. Uncalibrated sleds start disabled."""
    config = web_startup_config()
    config.update(name='ESP32 bring-up', dvdMode='independent')
    for device in config['devices']:
        device['mode'] = 'real'
        device['enabled'] = device['type'] != 'DVD_SLED'
        if device['type'] == 'HDD_VCM': device['profile'] = 'DRV8833_HDD_START'
    return config
