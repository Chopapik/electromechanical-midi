"""Pure descriptions of runtime stages and hardware backbone refinements.

The public preset catalog remains arrangement_presets.py. These descriptions
resolve only existing algorithm dependencies; they never choose new notes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from .orchestra import OrchestraConfig, parse_policy
from arrangement_presets import (
    FDD_EXPRESSIVE as EXPRESSIVE, FDD_EXPRESSIVE_SOLO as SOLO_PRESET,
    FDD_LEGATO as LEGATO, ADAPTIVE_LEGATO as ADAPTIVE,
    INSTRUMENT_ROLES, INSTRUMENT_ROLES_UNISON, INSTRUMENT_ROLES_DUET,
    INSTRUMENT_ROLES_UNISON4, UNIVERSAL, FDD_QUALITY, FDD_QUALITY_ADAPTIVE,
)


@dataclass(frozen=True)
class ArrangementStrategy:
    requested: str
    allocation: str
    remove_accents: bool = False
    phrase_legato: bool = False
    adaptive: bool = False

    @classmethod
    def for_preset(cls, preset):
        derived = preset in (SOLO_PRESET, LEGATO, ADAPTIVE)
        return cls(preset, EXPRESSIVE if derived else preset, derived,
                   preset in (LEGATO, ADAPTIVE), preset == ADAPTIVE)

    @property
    def supports_recovery(self):
        return self.allocation in ('universal', 'instrument_roles_unison4', EXPRESSIVE)

    def allocation_config(self, requested_config):
        # A distinct config expresses the shared allocator strategy. The user's
        # requested configuration is never temporarily relabelled or modified.
        return replace(requested_config, policy={**requested_config.policy,
                       'arrangementPreset': self.allocation})


@dataclass(frozen=True)
class FddGrouping:
    """Number of physical FDD lanes sharing one backbone voice; zero is independent."""

    size: int = 0

    @classmethod
    def from_legacy(cls, value):
        # The historical True means groups of FOUR, while integer 2 means pairs.
        # Keep the old entry keyword compatible without mixing bool/int internally.
        return cls(4 if value is True else value or 0)

    @property
    def enabled(self):
        return bool(self.size)


class HardwareRefinement(Enum):
    NONE = 'none'
    FDD_GROUPS = 'fdd_groups'
    ADAPTIVE_QUALITY = 'adaptive_quality'


@dataclass(frozen=True)
class HardwareAllocationStrategy:
    requested_config: OrchestraConfig
    backbone_config: OrchestraConfig
    grouping: FddGrouping
    refinement: HardwareRefinement = HardwareRefinement.NONE

    @classmethod
    def for_config(cls, config, grouping):
        policy = parse_policy(config.policy)
        if policy['arrangementPreset'] in (INSTRUMENT_ROLES_UNISON, INSTRUMENT_ROLES_DUET, INSTRUMENT_ROLES_UNISON4, EXPRESSIVE):
            quad = policy['arrangementPreset'] == INSTRUMENT_ROLES_UNISON4
            expressive = policy['arrangementPreset'] == EXPRESSIVE
            if expressive:
                # Disable the global listening experiment only in this strategy.
                policy = {**policy, 'fddFixedToneMs': 0., 'fddUnisonEnabled': False}
                config = replace(config, policy=policy)
            base_preset = UNIVERSAL if quad or expressive else INSTRUMENT_ROLES
            backbone = replace(config, policy={**policy, 'arrangementPreset': base_preset})
            group_size = 2 if expressive else 4 if quad else 0
            return cls(config, backbone, FddGrouping(group_size), HardwareRefinement.FDD_GROUPS)
        if policy['arrangementPreset'] == FDD_QUALITY_ADAPTIVE:
            backbone = replace(config, policy={**policy,
                'arrangementPreset': FDD_QUALITY, 'dvdContinuousSustain': False})
            return cls(config, backbone, FddGrouping(), HardwareRefinement.ADAPTIVE_QUALITY)
        return cls(config, config, grouping)
