"""Internal planner state and stable reinforcement expression bindings.

Public report dictionaries and extra:N API keys are projections. Stable IDs are
allocated in insertion order; equal reinforcement values remain distinct events.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .performance import PerformancePlan, ReinforcementEvent


@dataclass
class ExtraBinding:
    identity: str
    event: ReinforcementEvent
    articulation: dict | None = None


@dataclass
class PlanningContext:
    physical_lanes: dict[str, str] = field(default_factory=dict)
    fdd_groups: tuple[tuple[str, ...], ...] = ()
    expressive_fdd: bool = False
    join_fdd_tones: bool = False
    extras: list[ExtraBinding] = field(default_factory=list)
    next_extra_id: int = 0

    def bind(self, event, articulation):
        binding = ExtraBinding('extra-event:'+str(self.next_extra_id), event, articulation)
        self.next_extra_id += 1
        return binding


def ensure_extra_bindings(plan: PerformancePlan):
    """Adopt legacy input once; normal planner edits use the helpers below.

    Object references identify occurrences only while adopting an existing
    list. IDs never contain object addresses and are not hashes of values.
    Dataclass replacements explicitly retain their original binding via index.
    """
    context = plan.internal_context
    if len(context.extras) == len(plan.reinforcements) and all(
            binding.event is event for binding, event in zip(context.extras, plan.reinforcements)):
        return context.extras
    previous = defaultdict(deque)
    for binding in context.extras:
        previous[id(binding.event)].append(binding)
    bindings = []
    for index, event in enumerate(plan.reinforcements):
        candidates = previous[id(event)]
        bindings.append(candidates.popleft() if candidates else context.bind(
            event, plan.execution_articulation.get('extra:'+str(index))))
    context.extras = bindings
    return bindings


def import_extra_articulation(plan: PerformancePlan):
    """Compatibility boundary after a legacy producer resolves a whole sidecar."""
    bindings = ensure_extra_bindings(plan)
    for index, binding in enumerate(bindings):
        binding.articulation = plan.execution_articulation.get('extra:'+str(index))


def extra_articulation(plan: PerformancePlan, index: int):
    return ensure_extra_bindings(plan)[index].articulation


def project_extra_articulation(plan: PerformancePlan, primary=None):
    """Retain the established external extra:N representation and insertion order."""
    values = ({key: value for key, value in plan.execution_articulation.items()
               if not key.startswith('extra:')} if primary is None else dict(primary))
    for index, binding in enumerate(ensure_extra_bindings(plan)):
        if binding.articulation is not None:
            values['extra:'+str(index)] = binding.articulation
    plan.execution_articulation = values


def replace_extras(plan: PerformancePlan, retained, *, articulations=None, primary=None):
    """Keep (old index, replacement event) rows, preserving binding identities.

    Supplying an articulation value of None deliberately removes its sidecar.
    Omitting an override preserves the prior association, including absent data.
    """
    old = ensure_extra_bindings(plan)
    overrides = articulations or {}
    bindings = [ExtraBinding(old[index].identity, event,
                            overrides.get(index, old[index].articulation))
                for index, event in retained]
    plan.reinforcements = [binding.event for binding in bindings]
    plan.internal_context.extras = bindings
    project_extra_articulation(plan, primary)


def append_extra(plan: PerformancePlan, event: ReinforcementEvent, articulation=None):
    ensure_extra_bindings(plan)
    binding = plan.internal_context.bind(event, articulation)
    plan.reinforcements.append(event)
    plan.internal_context.extras.append(binding)
    if articulation is not None:
        plan.execution_articulation['extra:'+str(len(plan.reinforcements)-1)] = articulation
    return binding.identity


def set_extra_articulation(plan: PerformancePlan, index: int, articulation):
    ensure_extra_bindings(plan)[index].articulation = articulation
    key = 'extra:'+str(index)
    if articulation is None:
        plan.execution_articulation.pop(key, None)
    else:
        plan.execution_articulation[key] = articulation
