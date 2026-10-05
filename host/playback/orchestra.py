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

_POLICY_KEYS = frozenset(BALANCED)


IDLE_DEFAULTS = {
    'enabled': False, 'maxCopiesPerEvent': 1, 'lookAheadMs': 80.0,
    'deviceTypes': ['FDD', 'DVD_SLED', 'HDD_VCM', 'DVD_TRAY'],
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
            or any(kind not in ('FDD', 'DVD_SLED', 'HDD_VCM', 'DVD_TRAY', 'VHS') for kind in config['deviceTypes'])):
        raise ValueError('invalid idleReinforcement deviceTypes')
    for key in ('enabled', 'vhsEnabled'):
        if not isinstance(config[key], bool):
            raise ValueError(f'idleReinforcement {key} must be boolean')
    return config


@dataclasses.dataclass
class OrchestraConfig:
    """Dostepne urzadzenia + polityka wykonania."""

    name: str = 'Balanced 4FDD + 4DVD + VHS + 4HDD + 2Tray'
    devices: list[dict] = dataclasses.field(default_factory=list)
    policy: dict = dataclasses.field(default_factory=lambda: dict(BALANCED))
    dvd_mode: str = 'independent'
    tray_enabled: bool = True
    idle_reinforcement: dict = dataclasses.field(default_factory=parse_idle)

    def instances(self) -> list[VirtualDeviceInstance]:
        return [VirtualDeviceInstance.parse(device) for device in self.devices]

    def as_dict(self) -> dict:
        return {'name': self.name, 'devices': self.devices, 'policy': self.policy,
                'dvdMode': self.dvd_mode, 'trayEnabled': self.tray_enabled, 'idleReinforcement': self.idle_reinforcement}

    def allocation_devices(self) -> tuple[list[VirtualDeviceInstance], dict[str, list[dict]]]:
        """Reinforcement never changes the configured normal voice inventory."""
        if self.dvd_mode not in ('independent', 'reinforcement'):
            raise ValueError(f'unknown DVD mode: {self.dvd_mode}')
        devices = self.instances()
        return devices, {}


def _device(ident: str, kind: str, profile: str, name: str, mode: str = 'virtual') -> dict:
    return {'id': ident, 'type': kind, 'name': name, 'track': None, 'role': '',
            'volume': 0.2 if kind == 'DVD_SLED' else (0.35 if kind == 'DVD_TRAY' else 0.6),
            'pan': 0.0, 'mute': False, 'solo': False,
            'transpose': 0, 'gate': 1.0, 'profile': profile, 'mode': mode,
            'overrides': {}}


def default_orchestra(*, dvd_count: int = 4, dvd_mode: str = 'independent',
                      fdd_count: int = 4, hdd_count: int = 4, tray_count: int = 2,
                      tray_enabled: bool = True) -> OrchestraConfig:
    """Configurable software inventory; saved explicit device lists stay intact."""
    counts = (fdd_count, dvd_count, hdd_count, tray_count)
    if any(not isinstance(count, int) or count < 0 for count in counts) or sum(counts) + 1 > 64:
        raise ValueError('device counts must be nonnegative integers; maximum 64 devices')
    if dvd_mode not in ('independent', 'reinforcement'):
        raise ValueError(f'unknown DVD mode: {dvd_mode}')
    devices: list[dict] = []
    counters: dict[str, int] = {}

    inventory = (('FDD', fdd_count, 'FDD_CURRENT'), ('DVD_SLED', dvd_count, 'DVD_REFERENCE'),
                 ('VHS', 1, 'VHS_CURRENT'), ('HDD_VCM', hdd_count, 'WD_CAVIAR_CURRENT'),
                 ('DVD_TRAY', tray_count, 'DVD_TRAY_REFERENCE'))
    for kind, count, profile in inventory:
        if profile not in PROFILES:
            raise ValueError(f'brak profilu {profile} dla {kind}')

        for _ in range(count):
            counters[kind] = counters.get(kind, 0) + 1
            number = counters[kind]
            ident = (f'DVD_STEPPER_{number}' if kind == 'DVD_SLED' else
                     f'DVD_TRAY_{number}' if kind == 'DVD_TRAY' else f'{kind.lower()}-{number}')
            label = 'DVD Stepper' if kind == 'DVD_SLED' else 'DVD Tray' if kind == 'DVD_TRAY' else kind
            devices.append(_device(ident, kind, profile, f'{label} {number}' if kind.startswith('DVD') else f'{label} #{number}'))

    return OrchestraConfig(
        name=f'Balanced {fdd_count}FDD + {dvd_count}DVD + VHS + {hdd_count}HDD + {tray_count}Tray',
        devices=devices, policy=dict(BALANCED), dvd_mode=dvd_mode, tray_enabled=tray_enabled)


def parse_policy(payload: dict | None) -> dict:
    """Uzupelnia polityke o domyslne BALANCED, odrzuca nieznane klucze."""
    policy = dict(BALANCED)

    for key, value in (payload or {}).items():
        if key not in _POLICY_KEYS:
            raise ValueError(f'nieznany klucz polityki: {key}')

        policy[key] = value

    for key in ('maxMicroDelayMs', 'maxArpeggioMs', 'stealMargin', 'maxNoteSeconds', 'leadMaxNoteSeconds',
                   'leadMaxMicroDelayMs', 'capacitySafety',
                   'minMechanicalSustainMs', 'preferredMechanicalSustainMs',
                   'releaseGapMs', 'maxSustainExtensionMs', 'sourceContinuityAmount'):
        policy[key] = float(policy[key])

        if policy[key] < 0:
            raise ValueError(f'{key} nie moze byc ujemny')

    for key in ('preserveLead', 'preserveBass', 'allowVoiceSteal', 'softenRepeats',
                'mechanicalSustain', 'sourceContinuity'):
        policy[key] = bool(policy[key])

    if not 0 <= policy['sourceContinuityAmount'] <= 1:
        raise ValueError('sourceContinuityAmount must be between 0 and 1')

    if policy['mode'] not in ('balanced', 'melody', 'rhythm', 'strict'):
        raise ValueError(f'nieznany tryb polityki: {policy["mode"]}')

    return policy


def parse_orchestra(payload: dict | None) -> OrchestraConfig:
    """Buduje konfiguracje z JSON-a; brak pola devices = domyslna orkiestra."""
    payload = payload or {}
    dvd_mode = str(payload.get('dvdMode') or 'independent')
    if dvd_mode not in ('independent', 'reinforcement'):
        raise ValueError(f'unknown DVD mode: {dvd_mode}')

    if 'devices' not in payload or payload['devices'] is None:
        config = default_orchestra()
        config.policy = parse_policy(payload.get('policy'))
        config.name = str(payload.get('name') or config.name)
        config.dvd_mode = dvd_mode
        config.tray_enabled = bool(payload.get('trayEnabled', True))
        config.idle_reinforcement = parse_idle(payload.get('idleReinforcement'))
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
        tray_enabled=bool(payload.get('trayEnabled', True)),
        idle_reinforcement=parse_idle(payload.get('idleReinforcement')),
    )
    config.allocation_devices()
    return config


def web_startup_config() -> dict:
    """User-selected web player defaults; explicit presets/overrides stay editable."""
    orchestra = default_orchestra(dvd_mode='reinforcement')
    return {'name': orchestra.name, 'devices': orchestra.devices, 'enabled': True,
            'masterVolume': 19.5, 'tonalMode': 'extreme_v15', 'hddMode': 'articulated',
            'sourceContinuity': True, 'sourceContinuityAmount': 1.,
            'dvdMode': 'reinforcement', 'trayEnabled': True,
            'idleReinforcement': parse_idle({'enabled': False})}
