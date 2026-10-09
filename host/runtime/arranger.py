"""Deterministic musical planning. No output, transport or UI dependency."""
from dataclasses import asdict
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
        config.tray_enabled = False
        config.idle_reinforcement['enabled'] = False
        plan=allocate_strict(source, config, routing['tracks'], profiles)
    elif routing['mode']=='AUTO':
        plan=allocate(normalize(source), config, hardware_context=profiles)
    else: raise ValueError('Unknown routing mode')
    tonal,_=resolve(plan)
    plan.execution_articulation={key:asdict(art) for key,art in tonal.items()}
    sources={e.id:e for e in plan.events}
    for e in plan.events:
        if e.played and e.device_type=='HDD_VCM':
            neighbors=[abs(other.actual_start-e.actual_start) for other in plan.events if other.played and other.device_id==e.device_id and other.id!=e.id]
            art=adapt(classify(e.note,e.channel,e.velocity,e.articulation),min(neighbors,default=float('inf')))
            plan.execution_articulation[e.id]=asdict(art)
    types={d['id']:d['type'] for d in plan.devices}
    for i,e in enumerate(plan.reinforcements):
        if e.source_id in tonal:
            plan.execution_articulation['extra:'+str(i)]=asdict(retarget(tonal[e.source_id],types[e.device_id],e.duration,e.velocity,e.start-sources[e.source_id].actual_start))
        elif e.source_id in plan.execution_articulation:
            plan.execution_articulation['extra:'+str(i)]=plan.execution_articulation[e.source_id]
    return plan
