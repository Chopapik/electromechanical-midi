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

    name: str = 'Balanced 3FDD + VHS + 3HDD'
    devices: list[dict] = dataclasses.field(default_factory=list)
    policy: dict = dataclasses.field(default_factory=lambda: dict(BALANCED))

    def instances(self) -> list[VirtualDeviceInstance]:
        return [VirtualDeviceInstance.parse(device) for device in self.devices]

    def as_dict(self) -> dict:
        return {'name': self.name, 'devices': self.devices, 'policy': self.policy}


def _device(ident: str, kind: str, profile: str, name: str, mode: str = 'virtual') -> dict:
    return {'id': ident, 'type': kind, 'name': name, 'track': None, 'role': '',
            'volume': 0.6, 'pan': 0.0, 'mute': False, 'solo': False,
            'transpose': 0, 'gate': 1.0, 'profile': profile, 'mode': mode,
            'overrides': {}}


def default_orchestra() -> OrchestraConfig:
    """Orkiestra v1: 3x FDD, 1x VHS, 3x HDD VCM - bez zadnego JSON-a."""
    devices: list[dict] = []
    counters: dict[str, int] = {}

    for kind, count, profile in DEFAULT_INVENTORY:
        if profile not in PROFILES:
            raise ValueError(f'brak profilu {profile} dla {kind}')

        for _ in range(count):
            counters[kind] = counters.get(kind, 0) + 1
            ident = f'{kind.lower()}-{counters[kind]}'
            devices.append(_device(ident, kind, profile, f'{kind} #{counters[kind]}'))

    return OrchestraConfig(devices=devices, policy=dict(BALANCED))


def parse_policy(payload: dict | None) -> dict:
    """Uzupelnia polityke o domyslne BALANCED, odrzuca nieznane klucze."""
    policy = dict(BALANCED)

    for key, value in (payload or {}).items():
        if key not in _POLICY_KEYS:
            raise ValueError(f'nieznany klucz polityki: {key}')

        policy[key] = value

    for key in ('maxMicroDelayMs', 'maxArpeggioMs', 'stealMargin', 'maxNoteSeconds', 'leadMaxNoteSeconds',
                   'leadMaxMicroDelayMs', 'capacitySafety'):
        policy[key] = float(policy[key])

        if policy[key] < 0:
            raise ValueError(f'{key} nie moze byc ujemny')

    for key in ('preserveLead', 'preserveBass', 'allowVoiceSteal', 'softenRepeats'):
        policy[key] = bool(policy[key])

    if policy['mode'] not in ('balanced', 'melody', 'rhythm', 'strict'):
        raise ValueError(f'nieznany tryb polityki: {policy["mode"]}')

    return policy


def parse_orchestra(payload: dict | None) -> OrchestraConfig:
    """Buduje konfiguracje z JSON-a; brak urzadzen = domyslna orkiestra v1."""
    payload = payload or {}

    if not payload.get('devices'):
        config = default_orchestra()
        config.policy = parse_policy(payload.get('policy'))
        config.name = str(payload.get('name') or config.name)

        return config

    devices = [VirtualDeviceInstance.parse(device) for device in payload['devices']]

    if len(devices) > 64 or len({device.id for device in devices}) != len(devices):
        raise ValueError('maximum 64 devices; ids must be unique')

    return OrchestraConfig(
        name=str(payload.get('name') or 'Orchestra')[:100],
        devices=[dataclasses.asdict(device) for device in devices],
        policy=parse_policy(payload.get('policy')),
    )
