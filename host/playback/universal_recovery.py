"""Recover source voices in final idle reservations without editing played primaries.

The initial Universal plan is an immutable musical backbone. Recovery may use
only genuinely free time, original pitches/octave equivalents and full physical
chronology. Held harmony may enter late, bounded by tempo and its source gate;
held FDD tails may continue on DVD at the same performed pitch.
"""
from bisect import bisect_left
from collections import Counter
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

from .capabilities import capabilities_for
from .hardware_arranger import DVD_MAX_HZ, fold_for_profile
from .hardware_profiles import (min_note_ms, sled_frequency_range, HardwareDeviceState,
    HardwareNote, evaluate, advance_state)
from .instrument_roles import contexts
from .mechanical_arrangement import _chronology
from .universal import Phrases

EPS = 1e-9
RELEASE = .003


def recover(plan, registry, source):
    """Recover omitted sources/held tails; return new primary IDs for articulation."""
    report = {'version':1, 'scope':'offline free-gap recovery; no physical safety claim',
        'considered':0, 'recovered':0, 'addedSourceSeconds':0., 'mechanicalVetoes':0,
        'byRole':{}, 'byDevice':{}, 'primaryEventsChanged':0, 'originalReinforcementsChanged':0, 'lateSustainEntries':0,
        'continuations':0, 'continuationSeconds':0.}
    plan.hardware.setdefault('universal', {})['recovery'] = report
    dropped = [e for e in plan.events if not e.played and e.role in ('lead','bass','harmony')
               and not e.rule_id and not e.articulation and e.reason != 'MANUAL_DROP']
    from runtime.compiler import compile_plan
    report['backboneTimelineFingerprint'] = hashlib.sha256(json.dumps(
        compile_plan(plan).as_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    config = registry.configuration()
    devices = {d.id:d for d in config.instances()}
    caps = capabilities_for(list(devices.values()))
    profiles = {ident:registry.profile(ident) for ident in plan.hardware['physicalLanes']
                if devices[ident].type in ('FDD','DVD_SLED','VHS')
                and not (plan.policy.get('arrangementPreset')=='instrument_roles_unison4' and devices[ident].type=='FDD')}
    slots = {}
    for ident, profile in profiles.items():
        cap = caps[ident]
        if profile.name=='DVD_SLED':
            interval = [x*profile.get('pitchRatio') for x in sled_frequency_range(profile)]
            interval[1] = min(interval[1], DVD_MAX_HZ)
        else:
            interval = profile.get('musicalHz')
        if not interval: continue
        low, high = interval
        if profile.name=='FDD':
            step = profile.get('executionMinStepUs') or profile.get('datasheetMinStepMs')*1000
            low, high = max(low,cap.min_hz), min(high,cap.max_hz,1e6/step)
        caps[ident] = replace(cap,min_hz=low,max_hz=high)
        slots[ident] = SimpleNamespace(device=devices[ident],capability=caps[ident])
    profiles = {ident:p for ident,p in profiles.items() if ident in slots}
    tonal = [e for e in plan.events if e.role in ('lead','bass','harmony')]
    items = [{'id':e.id, 'track':e.track, 'role':e.role, 'order':i,
              'span':SimpleNamespace(start=e.start,end=e.start+e.duration,duration=e.duration,
                                     note=e.note,channel=e.channel,velocity=e.velocity)}
             for i,e in enumerate(tonal)]
    by_id = {i['id']:i for i in items}
    phrase = Phrases(items,contexts(items,plan.policy['mechanicalPhraseWindowMs']/1000.),
                     source,set(plan.analysis.get('fxTracks',[])))
    fx_tracks = set(plan.analysis.get('fxTracks',[]))
    lead = [s for i,s in slots.items() if profiles[i].name=='VHS' and s.device.role!='fx']
    fx = [s for i,s in slots.items() if profiles[i].name=='VHS' and s.device.role=='fx']
    motors = [s for i,s in slots.items() if profiles[i].name in ('FDD','DVD_SLED')]
    lanes = {ident:sorted([e for e in plan.events if e.played and e.device_id==ident],key=lambda e:(e.actual_start,e.id))
             for ident in slots}
    extras = {ident:[e for e in plan.reinforcements if e.device_id==ident] for ident in slots}
    def reservations(ident):
        rows = [(e.actual_start,e.end,e.played_hz) for e in lanes[ident]]
        rows += [(e.start,e.start+e.duration,e.hz) for e in extras[ident]]
        return sorted(rows)
    books = {ident:reservations(ident) for ident in slots}
    starts = {ident:[a for a,b,hz in rows] for ident,rows in books.items()}
    replacements = {}; roles=Counter(); used=Counter()
    rank={'lead':0,'bass':1,'harmony':2}
    for event in sorted(dropped,key=lambda e:(e.start,rank[e.role],-e.velocity,-e.duration,e.id)):
        report['considered'] += 1
        item = by_id[event.id]; candidates=[]
        for slot in phrase.pool(item,slots,profiles,lead,fx,motors,fx_tracks,None):
            ident=slot.device.id;profile=profiles[ident];cap=caps[ident]
            folded=fold_for_profile(event.note+slot.device.transpose,cap.min_hz,cap.max_hz,
                                    plan.policy['foldMode'],profile)
            if not folded.in_range:continue
            hz=folded.hz;played=folded.midi_note+folded.octave_shift*12
            rows=books[ident]
            entries=[event.start]
            held=(event.role=='harmony' and event.duration>=max(.65,phrase.beat(event.start))
                  and phrase.context[event.id]['sustainAffinity']>=.35)
            if held and profile.name=='DVD_SLED':
                latest=event.start+min(.35,.5*phrase.beat(event.start))
                entries += [b+RELEASE for a,b,f in rows if event.start<b+RELEASE<=latest]
            for entry in sorted(set(entries)):
                rows=books[ident];pos=bisect_left(starts[ident],entry)
                previous=rows[pos-1] if pos else None
                following=rows[pos] if pos<len(rows) else None
                if previous and previous[1]>entry+EPS:continue
                if following and following[0]<=entry+EPS:continue
                # Same-pitch source attacks need an actual release. Never shorten an
                # existing note merely to make an optional recovered attack fit.
                if previous and abs(previous[2]-hz)<1e-6 and entry-previous[1]<.012-EPS:continue
                if profile.name=='FDD':
                    interval=plan.policy['fddMinAttackIntervalMs']/1000.
                    if previous and entry-previous[0]<interval-EPS:continue
                    if following and following[0]-entry<interval-EPS:continue
                gate=phrase.gate(item,profile,event.duration,
                    'fx' if slot.device.role=='fx' else 'lead',event.track in fx_tracks)
                if gate is None:continue
                if following:
                    release=.012 if abs(following[2]-hz)<1e-6 else RELEASE
                    gate=min(gate,following[0]-entry-release)
                gate=min(gate,event.start+event.duration-entry)
                minimum=(1000.*max(cap.min_note_s,3./hz) if profile.name=='VHS' else min_note_ms(profile,hz))
                if minimum is None or gate+EPS<max(.04 if profile.name=='FDD' else .03,minimum/1000.):continue
                if phrase.reserved_conflict(item,slot.device,entry,gate,fx_tracks):continue
                # Keep the part's register/timbre preference; recovered duration is
                # an additional tie-break, not a reason to seize a primary voice.
                affinity=phrase.context[event.id]['sustainAffinity']
                musical=(affinity if profile.name=='DVD_SLED' else -affinity if profile.name=='FDD' else 0.)
                displacement=abs(played-(event.note+slot.device.transpose))/12.
                key=(entry>event.start+EPS,-gate/max(event.duration,EPS)-.25*musical+.1*displacement,entry,ident)
                proposal=replace(event,device_id=ident,device_type=slot.device.type,
                    played_note=played,played_hz=hz,actual_start=entry,actual_duration=gate,
                    outcome='REASSIGNED',preferred_device=event.preferred_device or ident,
                    reason='UNIVERSAL_SUSTAIN_ENTRY_RECOVERY' if entry>event.start+EPS else 'UNIVERSAL_FREE_GAP_RECOVERY',sustain_added=0.)
                candidates.append((key,proposal))
        for _,proposal in sorted(candidates,key=lambda c:c[0]):
            ident=proposal.device_id
            chronology=_chronology(profiles[ident],lanes[ident]+[proposal],extras[ident])
            if (chronology is None or profiles[ident].name=='DVD_SLED'
                    and chronology[proposal.id].transition_time + min_note_ms(profiles[ident],proposal.played_hz)/1000.
                        > proposal.actual_duration+EPS):
                report['mechanicalVetoes'] += 1
                continue
            proposal=replace(proposal,hardware={**chronology[proposal.id].as_dict(),
                'lane':plan.hardware['physicalLanes'][ident],
                'selection':{'reason':'existing primary reservations preserved',
                             'universalRecovery':True,
                             'sourceOnsetPreserved':proposal.actual_start==event.start}})
            replacements[event.id]=proposal;lanes[ident].append(proposal)
            lanes[ident].sort(key=lambda e:(e.actual_start,e.id))
            books[ident]=reservations(ident);starts[ident]=[a for a,b,hz in books[ident]]
            roles[event.role]+=1;used[ident]+=1
            report['lateSustainEntries'] += int(proposal.actual_start>event.start+EPS)
            report['addedSourceSeconds'] += proposal.actual_duration
            break
    if replacements:
        plan.events=[replacements.get(e.id,e) for e in plan.events]
    from .performance import ReinforcementEvent
    for event in sorted(plan.events,key=lambda e:(e.end,e.id)):
        if (not event.played or event.device_type!='FDD' or event.role not in ('bass','harmony')
                or event.id in replacements or event.rule_id or event.articulation
                or event.outcome in ('SHORTENED','STOLEN')
                or event.duration<max(.8,2*phrase.beat(event.start))):
            continue
        # Leave a release before the next attack of the tracked source voice.
        # Concurrent independent source voices keep their original gates.
        source_end=min(event.start+event.duration,
                       phrase.next_voice.get(event.id,float('inf'))-RELEASE)
        if source_end-event.end<.25:continue
        choices=[]
        for ident,profile in profiles.items():
            if profile.name!='DVD_SLED' or not profile.get('continuousRotation'):continue
            hz=event.played_hz;cap=caps[ident]
            if not cap.min_hz<=hz<=cap.max_hz:continue
            rows=books[ident]
            entries=[event.end]+[b+RELEASE for a,b,f in rows
                if event.end<b+RELEASE<=event.end+min(.35,.5*phrase.beat(event.start))]
            for entry in sorted(set(entries)):
                pos=bisect_left(starts[ident],entry)
                previous=rows[pos-1] if pos else None
                following=rows[pos] if pos<len(rows) else None
                if previous and previous[1]>entry+EPS:continue
                if previous and abs(previous[2]-hz)<1e-6 and entry-previous[1]<.012-EPS:continue
                end=min(source_end,following[0]-RELEASE if following else source_end)
                if end-entry<.25:continue
                # An already sounding DVD at the same performed pitch already
                # supplies this bed; do not reserve another motor for it.
                if any(a<=entry+EPS and b>=end-EPS and abs(f-hz)<1e-6
                       for other,book in books.items() if profiles[other].name=='DVD_SLED'
                       for a,b,f in book):continue
                extra=ReinforcementEvent(source_id=event.id,source_device=event.device_id,
                    device_id=ident,start=entry,duration=end-entry,hz=hz,velocity=event.velocity,
                    kind='CONTINUATION',role=event.role,reason='original held source continues on idle DVD',
                    semantic_compatibility='same source ID and performed pitch; no generated harmony')
                choices.append(((entry,-extra.duration,ident),extra))
        for _,extra in sorted(choices,key=lambda c:c[0]):
            ident=extra.device_id;profile=profiles[ident]
            proposed=extras[ident]+[extra]
            chronology=_chronology(profile,lanes[ident],proposed)
            key='extra:'+str(len(proposed)-1)
            if (chronology is None or chronology[key].transition_time+
                    min_note_ms(profile,extra.hz)/1000.>extra.duration+EPS):
                report['mechanicalVetoes']+=1
                continue
            plan.reinforcements.append(extra);extras[ident].append(extra)
            books[ident]=reservations(ident);starts[ident]=[a for a,b,hz in books[ident]]
            report['continuations']+=1;report['continuationSeconds']+=extra.duration
            break
    for ident in sorted(set(used)|{e.device_id for e in plan.reinforcements if e.kind=='CONTINUATION'}):
        count=used[ident]
        profile=profiles[ident]
        state=HardwareDeviceState(position=0. if profile.name=='DVD_SLED' else None)
        for a,b,hz in books[ident]:
            note=HardwareNote(hz,b-a,a)
            advance_state(state,profile,note,evaluate(profile,note,state))
        plan.hardware['states'][ident]=state.as_dict()
        if ident in plan.hardware.get('counters',{}):
            plan.hardware['counters'][ident]['recoveryAcceptedNotes']=count
            plan.hardware['counters'][ident]['finalPlayedNotes']=len(lanes[ident])
    plan.articulation['fddAttackRate']['postRecoveryByDevice']={
        ident:count for ident,count in used.items() if profiles[ident].name=='FDD'}
    report['continuationSeconds']=round(report['continuationSeconds'],6)
    report.update(recovered=len(replacements),byRole=dict(roles),byDevice=dict(used),
                  addedSourceSeconds=round(report['addedSourceSeconds'],6))
    return set(replacements)
