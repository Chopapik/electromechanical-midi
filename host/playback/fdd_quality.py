"""Experimental, soft musical/mechanical FDD selection inside the allocator."""
import bisect
import math
from collections import defaultdict
from .hardware_profiles import reversal_penalty_ms

DEFAULTS = {
    'arrangementPreset': 'balanced',
    'fddQualityPreferredNoteMs': 350.,
    'fddQualityPhraseSteps': 240.,
    'fddQualityReversalCost': .35,
    'fddQualityDensity': .55,
    'fddQualityWindowMs': 2000.,
    'fddQualityRestMs': 120.,
    'fddQualityCostWeight': .65,
    'fddQualityExtensionPenalty': .4,
    'fddQualityOptionalPriority': .65,
    'fddQualityOptionalCost': .85,
    'fddQualityUnisonPriority': .8,
    'fddQualityUnisonDuty': .12,
}


def enabled(policy): return policy.get('arrangementPreset') == 'fdd_quality'


def musical_values(notes, phrases, source):
    """Value includes phrase entry, motif motion and MIDI beat/meter, not velocity alone."""
    raw = getattr(source, 'source', source)
    tempo = raw.tempo
    segments = tempo._segments
    times = [s.seconds for s in segments]
    signatures = [(0,4,4)]
    for track in raw._midi.tracks:
        tick=0
        for msg in track:
            tick += msg.time
            if msg.type=='time_signature': signatures.append((tick,msg.numerator,msg.denominator))
    signatures.sort()
    lanes=defaultdict(list)
    for item in notes: lanes[(item['track'],item['span'].channel)].append(item)
    result={}
    for items in lanes.values():
        previous=None;entries={};anchors={}
        by_start=defaultdict(list)
        for item in items: by_start[item['span'].start].append(item['span'])
        for start,group in sorted(by_start.items()):
            entries[start]=previous is None or start-previous>.25
            anchors[start]=min(n.note for n in group)
            previous=max(n.end for n in group)
        for item in items:
            s=item['span'];phrase=phrases[item['id']]
            segment=segments[max(0,bisect.bisect_right(times,s.start)-1)]
            tick=segment.tick+(s.start-segment.seconds)*1e6/segment.tempo*raw.ticks_per_beat
            sig=signatures[max(0,bisect.bisect_right([x[0] for x in signatures],tick)-1)]
            beat=(tick-sig[0])/raw.ticks_per_beat*sig[2]/4
            onbeat=abs(beat-round(beat))<.06
            downbeat=onbeat and round(beat)%sig[1]==0
            entry=entries[s.start]
            anchor=s.note==anchors[s.start]
            motif=phrase['onsetsPerSecond']>=2 and phrase['repeatFraction']<.7 and s.duration<.6
            value=.28+s.velocity/127*.16+.22*entry+.12*onbeat+.1*downbeat+.17*motif+.08*(anchor and downbeat)
            if item['role']=='lead': value=max(value,.95)
            elif item['role']=='bass': value=max(value,.88)
            # Normalization already merges confident doubles. No second voice bonus.
            if item.get('duplicate_confidence') is not None: value-=.04
            value=max(0.,min(1.,value))
            result[item['id']]={'musicalValue':round(value,6),'phraseEntry':entry,
                'onBeat':onbeat,'downBeat':downbeat,'motif':motif,
                'important': item['role'] in ('lead','bass') or entry or motif or (anchor and downbeat) or value>=.8}
    return result


def mechanical_cost(profile, state, hz, duration, start, history, policy):
    rate=hz/profile.get('pitchRatio');steps=rate*duration;travel=profile.get('travelSteps')
    reversals=math.floor((state.away_steps+steps)/travel) if travel else 0
    window=policy['fddQualityWindowMs']/1000.
    recent=[e for e in history if e['end']>start-window]
    active=sum(max(0.,min(start,e['end'])-max(start-window,e['start'])) for e in recent)
    gap=max(0.,start-history[-1]['end']) if history else window
    rest=policy['fddQualityRestMs']/1000.
    phrase_steps=sum(e['steps'] for e in recent) if gap<rest else 0.
    chain=duration
    for e in reversed(recent):
        if start-e['end']>=rest: break
        chain=duration+start-e['chainStart'];break
    preferred=policy['fddQualityPreferredNoteMs']/1000.
    density=(active+duration)/(window+duration)
    reversal_delay=(reversal_penalty_ms(profile,rate) or 0.)/1000.*reversals
    cost=(.25*(phrase_steps+steps)/policy['fddQualityPhraseSteps']+
        reversals*policy['fddQualityReversalCost']+
        .25*chain/window+.25*density/policy['fddQualityDensity']+
        policy['fddQualityExtensionPenalty']*max(0.,duration/preferred-1)+.15*max(0.,1-gap/rest)+reversal_delay)
    return {'steps':steps,'estimatedReversals':reversals,'awayStepsBefore':state.away_steps,
        'directionBefore':state.direction,'reversalDelaySeconds':reversal_delay,
        'phraseSteps':phrase_steps+steps,'continuousSeconds':chain,'restSeconds':gap,
        'density':density,'cost':min(3.,cost), 'scope':'command-space estimate; physical head position unknown'}


def target_duration(duration, value, policy):
    preferred=policy['fddQualityPreferredNoteMs']/1000.
    if duration<=preferred:return duration
    retained=.7 if value['important'] else .2
    return preferred+(duration-preferred)*retained


def reserve(history,start,duration,steps,rest):
    chain_start=history[-1]['chainStart'] if history and start-history[-1]['end']<rest else start
    history.append({'start':start,'end':start+duration,'steps':steps,'chainStart':chain_start})


def diagnostics(plan):
    from .hardware_profiles import HardwareDeviceState, HardwareNote, evaluate, advance_state
    from .hardware_profiles import HardwareProfile, HardwareQuantity
    lanes=plan.hardware.get('physicalLanes',{})
    events=[e for e in plan.events if e.played and e.device_type=='FDD']
    extras=[e for e in plan.reinforcements if e.kind=='UNISON']
    steps=0.;reversals=0
    for ident,lane in lanes.items():
        if not lane.startswith('fdd:'):continue
        data=plan.hardware['profiles'][ident]
        p=HardwareProfile(data['id'],{k:HardwareQuantity.parse(v) for k,v in data['quantities'].items()},lane)
        state=HardwareDeviceState()
        notes=[HardwareNote(e.played_hz,e.actual_duration,e.actual_start) for e in events if e.device_id==ident]
        notes += [HardwareNote(e.hz,e.duration,e.start) for e in extras if e.device_id==ident]
        for n in sorted(notes,key=lambda n:n.start):
            ev=evaluate(p,n,state);steps+=(ev.step_rate or 0)*n.duration
            before=state.travel_reversals;advance_state(state,p,n,ev);reversals+=state.travel_reversals-before
    selected=[e for e in plan.events if e.played and e.device_type=='DVD_SLED' and 'fddQualityAlternatives' in e.hardware.get('selection',{})]
    return {'preset':plan.policy.get('arrangementPreset','balanced'),'fddNotes':len(events),
        'fddPrimarySeconds':round(sum(e.actual_duration for e in events),6),
        'fddSeconds':round(sum(e.actual_duration for e in events)+sum(e.duration for e in extras),6),
        'fddMeanSeconds':round(sum(e.actual_duration for e in events)/len(events),6) if events else 0.,
        'estimatedSteps':round(steps,3),'estimatedReversals':reversals,
        'estimateIncludesUnison':True,'omittedNotes':sum(not e.played for e in plan.events),
        'qualityOmittedNotes':sum(e.reason=='FDD_QUALITY_OPTIONAL_COST' for e in plan.events),
        'dvdTakeovers':len(selected),'unisonEvents':len(extras),
        'unisonSeconds':round(sum(e.duration for e in extras),6)}
