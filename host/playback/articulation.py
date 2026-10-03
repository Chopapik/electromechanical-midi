"""Mechaniczna artykulacja: ``sourceDuration`` vs ``performedDuration``.

MIDI gitary to czesto bardzo krotkie nuty (szarpniecie struny + naturalne
wybrzmienie instrumentu). Stacja dyskietek nie ma naturalnego decayu: jesli
zagramy literalnie 62 ms i STOP, slychac "puk, cisza, puk, cisza".

Ten modul dodaje warstwe WYKONAWCZA. Nie zmienia zrodla i nie rusza NOTE_ON -
wydluza tylko NOTE_OFF, i to wylacznie tam, gdzie na tym samym monofonicznym
urzadzeniu jest wolne miejsce do nastepnej nuty.

    Allocator -> PerformancePlan (sourceDuration + zaplanowany start)
              -> ten pass  (performedDuration)
              -> Virtual Orchestra / hardware scheduler

Dzieki temu wirtualizacja i sprzet dostaja DOKLADNIE te sama dlugosc wykonawcza.

Zasady:
  * NOTE_ON / ``actual_start`` nigdy sie nie zmienia,
  * ``performedEnd >= sourceEnd`` - sustain niczego nie skraca,
  * decyzje SHORTEN / STOLEN sa respektowane (nie przywracamy starej dlugosci),
  * ``performedEnd <= nextStart - releaseGap`` - zero nakladek na monofonii,
  * przy powtorce tego samego pitchu releaseGap rosnie do artykulacji
    mechanicznej, inaczej dwie nuty zleja sie w jedna ciagla,
  * tylko urzadzenia z capability ``articulation == 'sustain'`` (FDD).
"""
from __future__ import annotations

import dataclasses
import statistics

from .capabilities import DeviceCapability
from .performance import PerformancePlan
from .timeline import ARTICULATION_S

# Ponizej tego zysku nie warto ruszac planu (szum zaokraglen).
MIN_EXTENSION_S = 0.004

SUSTAIN = 'sustain'
NONE = 'none'

_DEFAULT_MIN_MS = 120.0
_DEFAULT_PREFERRED_MS = 190.0
_DEFAULT_RELEASE_MS = 3.0
_DEFAULT_MAX_EXTENSION_MS = 200.0


@dataclasses.dataclass(frozen=True)
class SustainParams:
    """Parametry FDD articulation. Wartosci w sekundach."""

    enabled: bool
    minimum: float          # krotsze nute traktujemy jako "szarpniete"
    preferred: float        # docelowa dlugosc wykonawcza
    release: float          # minimalna przerwa przed nastepna nuta
    max_extension: float    # ile maksymalnie dodajemy ponad zrodlo

    def as_dict(self) -> dict:
        return {
            'enabled': self.enabled,
            'minMechanicalSustainMs': round(self.minimum * 1000, 1),
            'preferredMechanicalSustainMs': round(self.preferred * 1000, 1),
            'releaseGapMs': round(self.release * 1000, 1),
            'maxSustainExtensionMs': round(self.max_extension * 1000, 1),
        }


def params_from_policy(policy: dict) -> SustainParams:
    def seconds(key: str, default_ms: float) -> float:
        return max(0.0, float(policy.get(key, default_ms)) / 1000.0)

    minimum = seconds('minMechanicalSustainMs', _DEFAULT_MIN_MS)
    preferred = seconds('preferredMechanicalSustainMs', _DEFAULT_PREFERRED_MS)

    if preferred < minimum:
        preferred = minimum

    return SustainParams(
        enabled=bool(policy.get('mechanicalSustain', True)),
        minimum=minimum,
        preferred=preferred,
        release=seconds('releaseGapMs', _DEFAULT_RELEASE_MS),
        max_extension=seconds('maxSustainExtensionMs', _DEFAULT_MAX_EXTENSION_MS),
    )


def planned_end(start: float, source_end: float, limit: float,
                params: SustainParams) -> float:
    """Koniec wykonawczy jednej nuty. Czysta funkcja - latwa do testow."""
    if not params.enabled or limit <= start:
        return source_end

    desired = max(source_end, start + params.preferred)
    desired = min(desired, source_end + params.max_extension)
    performed = min(desired, limit)

    # Nigdy nie skracamy: sustain dziala tylko w wolnej przestrzeni.
    if performed <= source_end + MIN_EXTENSION_S:
        return source_end

    return performed


def _release_for(current, following, params: SustainParams) -> float:
    """Przerwa przed nastepna nuta - dluzsza przy powtorce tego samego pitchu."""
    if current.played_note is not None and current.played_note == following.played_note:
        return max(params.release, ARTICULATION_S)

    return params.release


def apply(plan: PerformancePlan, capabilities: dict[str, DeviceCapability],
          params: SustainParams) -> dict:
    """Wydluza krotkie nuty na urzadzeniach sustain. Modyfikuje plan w miejscu.

    Zwraca statystyki do raportu. Nie zmienia liczby zdarzen, nie rusza
    ``actual_start`` i nie lamie decyzji SHORTEN / STOLEN.
    """
    if not params.enabled:
        return {'extended': 0, 'meanExtensionMs': 0.0, 'maxExtensionMs': 0.0,
                'addedSeconds': 0.0, 'sustainedDevices': []}

    by_device: dict[str, list[int]] = {}

    for position, event in enumerate(plan.events):
        if not event.played or event.device_id is None:
            continue

        capability = capabilities.get(event.device_id)

        if capability is None or capability.articulation != SUSTAIN:
            continue

        by_device.setdefault(event.device_id, []).append(position)

    extensions: list[float] = []
    added = 0.0

    for device_id, positions in sorted(by_device.items()):
        positions.sort(key=lambda index: (plan.events[index].actual_start,
                                          plan.events[index].id))

        for order, position in enumerate(positions):
            event = plan.events[position]

            # Allocator swiadomie skrocil te nute - nie przywracamy jej dlugosci.
            if event.outcome == 'SHORTENED':
                continue

            following = None

            if order + 1 < len(positions):
                following = plan.events[positions[order + 1]]

            limit = (following.actual_start - _release_for(event, following, params)
                     if following is not None else float('inf'))
            source_end = event.actual_start + event.actual_duration
            end = planned_end(event.actual_start, source_end, limit, params)
            gain = end - source_end

            if gain <= MIN_EXTENSION_S:
                continue

            plan.events[position] = dataclasses.replace(
                event, actual_duration=end - event.actual_start,
                sustain_added=event.sustain_added + gain)
            extensions.append(gain)
            added += gain

    return {
        'extended': len(extensions),
        'meanExtensionMs': round(statistics.fmean(extensions) * 1000, 1) if extensions else 0.0,
        'maxExtensionMs': round(max(extensions) * 1000, 1) if extensions else 0.0,
        'addedSeconds': round(added, 2),
        'sustainedDevices': sorted(by_device),
        'params': params.as_dict(),
    }
