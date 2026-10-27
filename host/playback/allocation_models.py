"""Shared allocation inputs and reservation state, independent of allocators.

Slot state belongs to one allocation invocation. SourceNote describes the existing
mapping without changing serialization, ordering, or mutation semantics.
"""
from __future__ import annotations

import dataclasses
from typing import NotRequired, TypedDict
from midi_source import NoteSpan
from .capabilities import DeviceCapability
from .device_models import DeviceInstance


class SourceNote(TypedDict):
    id: str
    span: NoteSpan
    track: int
    track_name: str
    role: str
    order: int
    priority: float
    name: str | None
    source_tracks: NotRequired[tuple[int, ...]]
    group_id: NotRequired[str | None]
    duplicate_confidence: NotRequired[float | None]


@dataclasses.dataclass(frozen=True)
class ManualPin:
    """Reczna decyzja uzytkownika (z Arrangement JSON) - tylko preferencja."""

    device_id: str | None
    rule_id: str
    articulation: str | None = None
    transpose: int = 0
    gate: float = 1.0
    octave_fold: bool = True


@dataclasses.dataclass
class AllocationSlot:
    """Stan jednego urzadzenia w trakcie allokacji."""

    device: DeviceInstance
    capability: DeviceCapability
    busy_until: float = 0.0
    last_played: int | None = None
    event_index: int | None = None      # indeks aktywnego zdarzenia (do voice steal)

    @property
    def headroom(self) -> int:
        """Wysokosc ostatnio granej nuty - do prowadzenia glosow i travelu."""
        return self.last_played if self.last_played is not None else 60


@dataclasses.dataclass(frozen=True)
class AllocationCandidate:
    slot: AllocationSlot
    played: int | None
    hz: float | None
    folded: bool
