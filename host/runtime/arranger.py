"""Deterministic musical planning. No output, transport or UI dependency."""
from dataclasses import asdict, replace
from playback.tonal_articulation import resolve, retarget
from playback.hdd_articulation import classify, adapt
from playback.allocator import allocate
from playback.duplicates import normalize
from playback.strict_tracks import allocate_strict
from .registry import PlanningProfiles

def arrange(source, registry):
    config = registry.configuration()
    from playback.fdd_expression import PRESET, SOLO_PRESET, without_accents
    from playback.fdd_legato import PRESET as LEGATO_PRESET, apply as phrase_legato
    requested_preset = config.policy['arrangementPreset']
    if requested_preset in (SOLO_PRESET, LEGATO_PRESET):
        # Run the exact original preset, including its reservations and recovery.
        # Muting early would change the next primary allocation and confound A/B.
        config.policy['arrangementPreset'] = PRESET
    profiles = PlanningProfiles(registry)
    routing = registry.document.get('routing', {'mode':'AUTO'})
    if routing['mode'] == 'STRICT_TRACKS':
        config.devices = [d for d in config.devices if d['type']=='FDD']
        config.dvd_mode = 'independent'
        config.idle_reinforcement['enabled'] = False
        plan=allocate_strict(source, config, routing['tracks'], profiles)
    elif routing['mode']=='AUTO':
        plan=allocate(normalize(source), config, hardware_context=profiles)
    else: raise ValueError('Unknown routing mode')
    from playback.fdd_duration import apply as fix_fdd_duration
    fix_fdd_duration(plan)
    preserved_articulation = plan.execution_articulation
    tonal,_=resolve(plan)
    plan.execution_articulation={key:asdict(art) for key,art in tonal.items()}
    plan.execution_articulation.update(preserved_articulation)
    sources={e.id:e for e in plan.events}
    from collections import defaultdict
    percussion=defaultdict(list)
    gaps={}
    for e in plan.events:
        if e.played and e.device_type=='HDD_VCM':percussion[e.device_id].append(e)
    for events in percussion.values():
        events.sort(key=lambda e:(e.actual_start,e.id))
        for i,e in enumerate(events):
            gaps[e.id]=min((abs(events[j].actual_start-e.actual_start) for j in (i-1,i+1)
                            if 0<=j<len(events)),default=float('inf'))
    for e in plan.events:
        if e.played and e.device_type=='HDD_VCM':
            art=adapt(classify(e.note,e.channel,e.velocity,e.articulation),gaps[e.id])
            plan.execution_articulation[e.id]=asdict(art)
    types={d['id']:d['type'] for d in plan.devices}
    for i,e in enumerate(plan.reinforcements):
        if 'extra:'+str(i) in preserved_articulation:
            continue
        if e.source_id in tonal:
            plan.execution_articulation['extra:'+str(i)]=asdict(retarget(tonal[e.source_id],types[e.device_id],e.duration,e.velocity,e.start-sources[e.source_id].actual_start))
        elif e.source_id in plan.execution_articulation:
            plan.execution_articulation['extra:'+str(i)]=plan.execution_articulation[e.source_id]
    from playback.fdd_attack_rate import apply as limit_fdd_attacks
    limit_fdd_attacks(plan, registry)
    from playback.fdd_pairs import synchronize_unison4
    synchronize_unison4(plan, registry)
    from playback.fdd_expression import finalize as finalize_fdd_expression
    finalize_fdd_expression(plan)
    if routing['mode']=='AUTO' and plan.policy.get('arrangementPreset') in ('universal','instrument_roles_unison4','fdd_expressive'):
        from playback.universal_recovery import recover
        existing_extras=len(plan.reinforcements)
        recovered = recover(plan, registry, source)
        fix_fdd_duration(plan)
        if recovered or len(plan.reinforcements)>existing_extras:
            # Existing command sidecars are immutable. Resolve expression for
            # inserted source notes only, keeping prior envelopes/FX/HDD exact.
            source_events={e.id:e for e in plan.events}
            wanted=set(recovered)|{e.source_id for e in plan.reinforcements[existing_extras:]}
            # Capture expression over the complete ORIGINAL source gate. A short
            # FDD sidecar has no controller changes from its later held tail.
            expression_plan=replace(plan,events=[replace(e,actual_duration=e.duration)
                if e.id in wanted else e for e in plan.events])
            recovered_tonal, _ = resolve(expression_plan)
            for ident in recovered:
                event=source_events[ident]
                if ident in recovered_tonal:
                    plan.execution_articulation[ident]=asdict(retarget(recovered_tonal[ident],
                        event.device_type,event.actual_duration,event.velocity,
                        event.actual_start-event.start))
            for index in range(existing_extras,len(plan.reinforcements)):
                extra=plan.reinforcements[index]
                art=recovered_tonal.get(extra.source_id)
                if art is not None:
                    plan.execution_articulation['extra:'+str(index)]=asdict(retarget(art,
                        types[extra.device_id],extra.duration,extra.velocity,
                        extra.start-source_events[extra.source_id].start))
        # Recovery can add new FDD reservations; apply the same fixed gate and
        # spacing to the complete final plan.
        limit_fdd_attacks(plan, registry)
        synchronize_unison4(plan, registry)
        finalize_fdd_expression(plan)
    from playback.dvd_register import apply as set_dvd_register
    set_dvd_register(plan, registry, source)
    if requested_preset in (SOLO_PRESET, LEGATO_PRESET):
        without_accents(plan, registry)
        if requested_preset == LEGATO_PRESET:
            phrase_legato(plan, registry, source)
        plan.policy['arrangementPreset'] = requested_preset
    return plan
