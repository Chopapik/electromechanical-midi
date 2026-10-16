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
    preserved_articulation = plan.execution_articulation
    tonal,_=resolve(plan)
    plan.execution_articulation={key:asdict(art) for key,art in tonal.items()}
    plan.execution_articulation.update(preserved_articulation)
    sources={e.id:e for e in plan.events}
    for e in plan.events:
        if e.played and e.device_type=='HDD_VCM':
            neighbors=[abs(other.actual_start-e.actual_start) for other in plan.events if other.played and other.device_id==e.device_id and other.id!=e.id]
            art=adapt(classify(e.note,e.channel,e.velocity,e.articulation),min(neighbors,default=float('inf')))
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
    if routing['mode']=='AUTO' and plan.policy.get('arrangementPreset')=='universal':
        from playback.universal_recovery import recover
        existing_extras=len(plan.reinforcements)
        recovered = recover(plan, registry, source)
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
    return plan
