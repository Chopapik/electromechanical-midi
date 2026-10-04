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

# Domyslna orkiestra v1. Kolejnosc = kolejnosc w puli (deterministyczna).
DEFAULT_INVENTORY = (
    ('FDD', 3, 'FDD_CURRENT'),
    ('VHS', 1, 'VHS_CURRENT'),
    ('HDD_VCM', 3, 'WD_CAVIAR_CURRENT'),
)

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


@dataclasses.dataclass
class OrchestraConfig:
    """Dostepne urzadzenia + polityka wykonania."""

    name: str = 'Balanced 3FDD + 4DVD + VHS + 3HDD'
    devices: list[dict] = dataclasses.field(default_factory=list)
    policy: dict = dataclasses.field(default_factory=lambda: dict(BALANCED))
    dvd_mode: str = 'independent'

    def instances(self) -> list[VirtualDeviceInstance]:
        return [VirtualDeviceInstance.parse(device) for device in self.devices]

    def as_dict(self) -> dict:
        return {'name': self.name, 'devices': self.devices, 'policy': self.policy,
                'dvdMode': self.dvd_mode}

    def allocation_devices(self) -> tuple[list[VirtualDeviceInstance], dict[str, list[dict]]]:
        """Both modes allocate the same four independent DVD voices."""
        if self.dvd_mode not in ('independent', 'reinforcement'):
            raise ValueError(f'unknown DVD mode: {self.dvd_mode}')
        devices = self.instances()
        if self.dvd_mode == 'reinforcement' and len([d for d in devices if d.type == 'DVD_SLED']) != 4:
            raise ValueError('reinforcement requires exactly four DVD_SLED devices')
        return devices, {}


def _device(ident: str, kind: str, profile: str, name: str, mode: str = 'virtual') -> dict:
    return {'id': ident, 'type': kind, 'name': name, 'track': None, 'role': '',
            'volume': 0.2 if kind == 'DVD_SLED' else 0.6,
            'pan': 0.0, 'mute': False, 'solo': False,
            'transpose': 0, 'gate': 1.0, 'profile': profile, 'mode': mode,
            'overrides': {}}


def default_orchestra(*, dvd_count: int = 4, dvd_mode: str = 'independent') -> OrchestraConfig:
    """Testowa orkiestra; dvd_count=0 odtwarza bazowe siedem urządzeń."""
    if not 0 <= dvd_count <= 57:
        raise ValueError('dvd_count poza zakresem 0..57')
    if dvd_mode not in ('independent', 'reinforcement') or (dvd_mode == 'reinforcement' and dvd_count != 4):
        raise ValueError(f'unknown DVD mode: {dvd_mode}')
    devices: list[dict] = []
    counters: dict[str, int] = {}

    inventory = (DEFAULT_INVENTORY[0], ('DVD_SLED', dvd_count, 'DVD_REFERENCE'),
                 *DEFAULT_INVENTORY[1:])
    for kind, count, profile in inventory:
        if profile not in PROFILES:
            raise ValueError(f'brak profilu {profile} dla {kind}')

        for _ in range(count):
            counters[kind] = counters.get(kind, 0) + 1
            ident = f'{kind.lower()}-{counters[kind]}'
            devices.append(_device(ident, kind, profile, f'{kind} #{counters[kind]}'))

    return OrchestraConfig(
        name=('Balanced 3FDD + 4DVD + VHS + 3HDD' if dvd_count == 4
              else f'Balanced 3FDD + {dvd_count}DVD + VHS + 3HDD'),
        devices=devices, policy=dict(BALANCED), dvd_mode=dvd_mode)


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
                   'releaseGapMs', 'maxSustainExtensionMs'):
        policy[key] = float(policy[key])

        if policy[key] < 0:
            raise ValueError(f'{key} nie moze byc ujemny')

    for key in ('preserveLead', 'preserveBass', 'allowVoiceSteal', 'softenRepeats',
                'mechanicalSustain'):
        policy[key] = bool(policy[key])

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
    )
    config.allocation_devices()
    return config
