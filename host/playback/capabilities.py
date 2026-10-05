"""Co potrafi kazdy typ urzadzenia - jedyne miejsce do rozszerzania orkiestry.

Dodanie nowego sprzetu (DVD sled, free stepper, solenoid) ma byc dopisaniem
wiersza w ``CAPABILITIES``, a NIE zmiana algorytmu allokacji. Allocator pyta
wylacznie o pojemnosc (tonalna/perkusyjna), monofonie, zakres, minimalna
dlugosc nuty i czas retriggeru.
"""
from __future__ import annotations

import dataclasses

from .virtual import PROFILES, VirtualDeviceInstance, effective_profile

TONAL = 'tonal'
PERCUSSIVE = 'percussive'

# Minimalna nuta, ktora mechanika w ogole zagra (patrz timeline.MIN_NOTE_S).
MIN_NOTE_S = 0.010

# Polityka rol jest TWARDA, nie punktowana. Dwa rodzaje urzadzen tonalnych:
#
#   'lead-only'     - dedykowane WYLACZNIE linii melodycznej. Nigdy nie trafia
#                     do puli akompaniamentu, wiec nie ma go nawet na liscie
#                     kandydatow dla basu/harmonii. To nie "niski score" -
#                     to brak kwalifikacji.
#   'accompaniment' - pula dla basu, gitary, harmonii i chord tones.
#
# Dzieki temu VHS nie moze "walczyc" o kilka rol w trakcie utworu.
_ROLE_POLICY = {
    'VHS': 'lead-only',
    'FDD': 'accompaniment',
    'DVD_SLED': 'accompaniment',
    'STEPPER_FREE': 'accompaniment',
    'HDD_VCM': 'percussion',
    'SOLENOID_RESONATOR': 'percussion',
    'DVD_TRAY': 'reinforcement-only',
}

# Jaka artykulacje mechaniczna stosuje dany typ urzadzenia. To wlasciwosc
# SPRZETU, nie utworu: FDD nie ma naturalnego wybrzmienia, wiec krotkie nuty
# trzeba przedluzyc. VHS i HDD tego nie potrzebuja.
_ARTICULATION = {
    'FDD': 'sustain',
    'DVD_SLED': 'none',
    'STEPPER_FREE': 'none',
    'VHS': 'none',
    'HDD_VCM': 'none',
    'SOLENOID_RESONATOR': 'none',
    'DVD_TRAY': 'none',
}

LEAD_ONLY = 'lead-only'
ACCOMPANIMENT = 'accompaniment'
PERCUSSION_POLICY = 'percussion'

_ROLE = {
    'FDD': TONAL,
    'DVD_SLED': TONAL,
    'STEPPER_FREE': TONAL,
    'VHS': TONAL,
    'HDD_VCM': PERCUSSIVE,
    'SOLENOID_RESONATOR': PERCUSSIVE,
    'DVD_TRAY': PERCUSSIVE,
}


@dataclasses.dataclass(frozen=True)
class DeviceCapability:
    """Pojemnosc jednej instancji - wszystko, czego potrzebuje allocator."""

    kind: str
    role: str                                   # TONAL | PERCUSSIVE
    monophonic: bool
    min_hz: float | None
    max_hz: float | None
    min_note_s: float
    retrigger_s: float                          # odstep do nastepnej nuty/uderzenia
    overflow: str                               # 'fold' | 'drop'
    role_policy: str = ACCOMPANIMENT            # LEAD_ONLY | ACCOMPANIMENT | PERCUSSION_POLICY
    articulation: str = 'none'                  # 'sustain' | 'none'

    @property
    def tonal(self) -> bool:
        return self.role == TONAL

    @property
    def lead_only(self) -> bool:
        """Urzadzenie dedykowane linii melodycznej - nieakompaniamentowe."""
        return self.role_policy == LEAD_ONLY

    def accepts(self, role: str) -> bool:
        """Czy to urzadzenie moze w ogole dostac te role.

        To jest twarda kwalifikacja, nie punktacja: akompaniament nie ma
        prawa trafic na urzadzenie ``lead-only`` w ZADNEJ sytuacji.
        """
        if not self.tonal:
            return False

        if role == 'lead':
            return True

        return not self.lead_only

    @property
    def percussive(self) -> bool:
        return self.role == PERCUSSIVE

    @property
    def has_range(self) -> bool:
        return self.min_hz is not None and self.max_hz is not None

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def cycle_seconds(profile) -> float:
    """Pelny cykl mechaniczny urzadzenia uderzeniowego."""
    park = float(profile.get('parkMs') or 0) / 1000.0
    settle = float(profile.get('settleMs') or 0) / 1000.0
    strike = float(profile.get('strikeMs') or 0) / 1000.0
    cooldown = float(profile.get('cooldownMs') or 0) / 1000.0
    retrigger = float(profile.get('minRetriggerMs') or 0) / 1000.0

    return max(park + settle + strike + cooldown, retrigger)


def capability_for(device: VirtualDeviceInstance) -> DeviceCapability:
    """Buduje pojemnosc instancji z jej profilu (z uwzglednieniem overrides)."""
    kind = device.type
    role = _ROLE.get(kind)

    if role is None:
        raise ValueError(f'brak capability dla typu urzadzenia: {kind}')

    profile = effective_profile(device)
    low, high = profile.playback_range()
    retrigger = cycle_seconds(profile) if role == PERCUSSIVE else 0.0

    return DeviceCapability(
        kind=kind,
        role=role,
        monophonic=bool(profile.get('polyphony') or 1) <= 1,
        min_hz=low,
        max_hz=high,
        min_note_s=MIN_NOTE_S,
        retrigger_s=retrigger,
        overflow=profile.overflow,
        role_policy=_ROLE_POLICY.get(kind, ACCOMPANIMENT),
        articulation=_ARTICULATION.get(kind, 'none'),
    )


def capabilities_for(devices: list[VirtualDeviceInstance]) -> dict[str, DeviceCapability]:
    return {device.id: capability_for(device) for device in devices}
