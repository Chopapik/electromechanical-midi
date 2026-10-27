"""Named planning stages. Execution order is explicit and preset-specific.

Stages may mutate the plan, never transports or application playback state.
The selected preset and its shared allocation strategy are separate inputs.
"""
from collections import defaultdict
from dataclasses import asdict, replace
from playback.tonal_articulation import resolve, retarget
from playback.hdd_articulation import classify, adapt
from playback.allocator import allocate
from playback.duplicates import normalize
from playback.strict_tracks import allocate_strict
from playback.fdd_duration import apply as fix_fdd_duration
from playback.fdd_attack_rate import apply as limit_fdd_attacks
from playback.fdd_pairs import synchronize_unison4
from playback.fdd_expression import (
    finalize as finalize_fdd_expression, without_accents)
from playback.fdd_legato import apply as phrase_legato
from playback.dvd_register import apply as set_dvd_register
from playback.planning_context import (ensure_extra_bindings, import_extra_articulation,
                                       set_extra_articulation)
from playback.arrangement_strategy import ArrangementStrategy
from .registry import PlanningProfiles


def allocate_backbone(source, registry, strategy):
    config = strategy.allocation_config(registry.configuration())
    profiles = PlanningProfiles(registry)
    mode = registry.document.get('routing', {'mode':'AUTO'})
    if mode['mode'] == 'STRICT_TRACKS':
        config = replace(config, devices=[d for d in config.devices if d['type']=='FDD'],
                         dvd_mode='independent',
                         idle_reinforcement={**config.idle_reinforcement, 'enabled':False})
        return allocate_strict(source, config, mode['tracks'], profiles)
    if mode['mode'] != 'AUTO':
        raise ValueError('Unknown routing mode')
    return allocate(normalize(source), config, hardware_context=profiles)


def resolve_expression(plan):
    ensure_extra_bindings(plan)
    fix_fdd_duration(plan)
    preserved_articulation = plan.execution_articulation
    tonal,_=resolve(plan)
    plan.execution_articulation={key:asdict(articulation) for key,articulation in tonal.items()}
    plan.execution_articulation.update(preserved_articulation)
    import_extra_articulation(plan)
    source_events={event.id:event for event in plan.events}
    percussion_events=defaultdict(list)
    gaps={}
    for event in plan.events:
        if event.played and event.device_type=='HDD_VCM':
            percussion_events[event.device_id].append(event)
    for events in percussion_events.values():
        events.sort(key=lambda event:(event.actual_start,event.id))
        for index,event in enumerate(events):
            gaps[event.id]=min((abs(events[j].actual_start-event.actual_start) for j in (index-1,index+1)
                            if 0<=j<len(events)),default=float('inf'))
    for event in plan.events:
        if event.played and event.device_type=='HDD_VCM':
            articulation=adapt(classify(event.note,event.channel,event.velocity,event.articulation),gaps[event.id])
            plan.execution_articulation[event.id]=asdict(articulation)
    device_types={d['id']:d['type'] for d in plan.devices}
    for index,event in enumerate(plan.reinforcements):
        if 'extra:'+str(index) in preserved_articulation:
            continue
        if event.source_id in tonal:
            set_extra_articulation(plan, index, asdict(retarget(tonal[event.source_id],device_types[event.device_id],event.duration,event.velocity,event.start-source_events[event.source_id].actual_start)))
        elif event.source_id in plan.execution_articulation:
            set_extra_articulation(plan, index, plan.execution_articulation[event.source_id])


def enforce_fdd_limits(plan, registry):
    limit_fdd_attacks(plan, registry)
    synchronize_unison4(plan, registry)
    finalize_fdd_expression(plan)


def resolve_recovered_expression(plan, recovered, existing_extras):
    # Resolve only new reservations; existing command envelopes remain exact.
    types = {device['id']: device['type'] for device in plan.devices}
    source_events = {event.id: event for event in plan.events}
    wanted = set(recovered)|{extra.source_id for extra in plan.reinforcements[existing_extras:]}
    expression_plan = replace(plan, events=[replace(event, actual_duration=event.duration)
        if event.id in wanted else event for event in plan.events])
    recovered_tonal, _ = resolve(expression_plan)
    for ident in recovered:
        event = source_events[ident]
        if ident in recovered_tonal:
            plan.execution_articulation[ident] = asdict(retarget(recovered_tonal[ident],
                event.device_type, event.actual_duration, event.velocity,
                event.actual_start-event.start))
    for index in range(existing_extras, len(plan.reinforcements)):
        extra = plan.reinforcements[index]
        art = recovered_tonal.get(extra.source_id)
        if art is not None:
            set_extra_articulation(plan, index, asdict(retarget(art,
                types[extra.device_id], extra.duration, extra.velocity,
                extra.start-source_events[extra.source_id].start)))


def recover_voices(plan, registry, source):
    from playback.universal_recovery import recover
    existing_extras = len(plan.reinforcements)
    recovered = recover(plan, registry, source)
    fix_fdd_duration(plan)
    if recovered or len(plan.reinforcements) > existing_extras:
        resolve_recovered_expression(plan, recovered, existing_extras)
    # New reservations must pass the same final gate/spacing synchronisation.
    enforce_fdd_limits(plan, registry)


def finish_articulation(plan, registry, source, strategy):
    set_dvd_register(plan, registry, source)
    if strategy.remove_accents:
        without_accents(plan, registry)
        if strategy.phrase_legato:
            phrase_legato(plan, registry, source, adaptive=strategy.adaptive)
        # This is the public selected preset; the allocation strategy remains
        # internal and is never represented as a temporary user selection.
        plan.policy['arrangementPreset'] = strategy.requested


def run(source, registry):
    strategy = ArrangementStrategy.for_preset(registry.configuration().policy['arrangementPreset'])
    plan = allocate_backbone(source, registry, strategy)
    resolve_expression(plan)
    enforce_fdd_limits(plan, registry)
    auto = registry.document.get('routing', {'mode':'AUTO'})['mode'] == 'AUTO'
    if auto and strategy.supports_recovery:
        recover_voices(plan, registry, source)
    finish_articulation(plan, registry, source, strategy)
    return plan
