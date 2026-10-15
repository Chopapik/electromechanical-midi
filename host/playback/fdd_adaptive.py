"""Tempo/meter windows and soft density adaptation. No song-name rules."""
import bisect
import math
import statistics
from collections import defaultdict, Counter

PRESET = 'fdd_quality_adaptive'

def enabled(policy):
    return policy.get('arrangementPreset') == PRESET


def smooth(value):
    value=max(0.,min(1.,value))
    return value*value*(3-2*value)


class DensityMap:
    """Half-beat updates over a local bar; tick conversion respects all tempos."""
    def __init__(self, source, notes, fdd_count):
        raw=getattr(source,'source',source);tpb=raw.ticks_per_beat
        segments=raw.tempo._segments;times=[s.seconds for s in segments]
        def tick(seconds):
            s=segments[max(0,bisect.bisect_right(times,seconds)-1)]
            return s.tick+(seconds-s.seconds)*1e6/s.tempo*tpb
        signatures={0:(4,4)}
        for track in raw._midi.tracks:
            t=0
            for msg in track:
                t+=msg.time
                if msg.type=='time_signature':signatures[t]=(msg.numerator,msg.denominator)
        meters=sorted(signatures)
        tonal=[i for i in notes if i['role']!='percussion']
        lanes=defaultdict(list)
        for item in tonal:
            n=item['span'];a=tick(n.start);b=tick(n.end)
            lanes[(item['track'],n.channel)].append((a,b,n.velocity,item['id']))
        for lane in lanes.values():lane.sort()
        self.frames=[];self.starts=[];self.by_id={}
        end=max((tick(i['span'].end) for i in tonal),default=0.)
        level=0.
        for index in range(math.ceil(end/(tpb/2))+1):
            centre=index*tpb/2
            meter=signatures[meters[max(0,bisect.bisect_right(meters,centre)-1)]]
            bar=tpb*meter[0]*4/meter[1]
            low=max(0.,centre-bar/2);high=centre+bar/2
            fast=[];all_notes=[];onsets=set();parts=0
            for lane in lanes.values():
                starts=[n[0] for n in lane]
                group=lane[bisect.bisect_left(starts,low):bisect.bisect_left(starts,high)]
                if not group:continue
                parts+=1;all_notes.extend(group);unique=sorted({n[0] for n in group});onsets.update(unique)
                gaps=[(b-a)/tpb for a,b in zip(unique,unique[1:]) if b>a]
                rate=1/statistics.median(gaps) if gaps else 0.
                velocity=statistics.mean(n[2] for n in group)
                coverage_rate=len(unique)/max(1.,(high-low)/tpb)
                strength=smooth((rate-5.)/3.)*smooth((coverage_rate-5.)/3.)*smooth((velocity-65.)/25.)
                if strength:fast.append(strength)
            short=sum(b-a<=tpb*.5 for a,b,_,_ in all_notes)/len(all_notes) if all_notes else 0.
            # Rapid coherent lanes drive the response; chord size alone cannot.
            drive=max(fast,default=0.)
            target=drive*(.55+.25*min(1.,len(fast)/2)+.2*short)
            # Smoothed attack/release measured in beats, independent of seconds/BPM.
            alpha=1-math.exp(-.5/(.75 if target>level else 1.5))
            level+=alpha*(target-level)
            if level<.005:level=0.
            seconds=raw.tempo.seconds_at(round(centre))
            frame={'start':seconds,'end':raw.tempo.seconds_at(round(centre+tpb/2)),
                'beat':centre/tpb,'beatSeconds':raw.tempo.seconds_at(round(centre+tpb))-seconds,'barBeats':bar/tpb,'level':round(level,6),
                'target':round(target,6),'independentParts':parts,'fastParts':len(fast),
                'tonalNotesPerBeat':round(len(all_notes)/max(1.,(high-low)/tpb),3),
                'onsetsPerBeat':round(len(onsets)/max(1.,(high-low)/tpb),3),
                'shortFraction':round(short,3),'availableFdd':fdd_count}
            self.frames.append(frame);self.starts.append(seconds)
        for item in notes:self.by_id[item['id']]=self.at(item['span'].start)

    def at(self, seconds):
        i=max(0,bisect.bisect_right(self.starts,seconds)-1)
        return self.frames[i] if self.frames else {'level':0.,'availableFdd':0}

    def amount(self, seconds):
        if not self.frames:return 0.
        i=max(0,bisect.bisect_right(self.starts,seconds)-1);a=self.frames[i]
        if i+1==len(self.frames):return a['level']
        b=self.frames[i+1];mix=(seconds-a['start'])/max(1e-9,b['start']-a['start'])
        return a['level']+(b['level']-a['level'])*max(0.,min(1.,mix))


def adjusted_value(value, phrase, item, amount):
    result=dict(value)
    # Repeated rhythmic attacks can matter even when pitches do not change.
    rhythmic=phrase['onsetsPerSecond']>=3 and item['span'].velocity>=80 and item['span'].duration<=.5
    if amount>.15 and rhythmic:
        result['important']=True;result['rhythmicMotif']=True
        result['musicalValue']=max(result['musicalValue'],.75)
    return result


def activity(plan):
    primary=[(e.actual_start,e.end,e.device_id) for e in plan.events if e.played and e.device_type=='FDD']
    extras=[(e.start,e.start+e.duration,e.device_id) for e in plan.reinforcements if e.kind=='UNISON']
    def sweep(intervals):
        points=defaultdict(list);points[0.];points[plan.duration]
        for a,b,d in intervals:points[a].append((d,1));points[b].append((d,-1))
        active=Counter();hist=[0.]*5;timeline=[];last=0.
        for t,changes in sorted(points.items()):
            count=sum(v>0 for v in active.values())
            if t>last:hist[min(4,count)]+=t-last;timeline.append({'start':last,'end':t,'activeFdd':count})
            for d,delta in changes:active[d]+=delta
            last=t
        return {'seconds':hist,'fractions':[x/max(plan.duration,1e-9) for x in hist],'timeline':timeline}
    return {'primary':sweep(primary),'includingUnison':sweep(primary+extras)}


def summarize(plan, reference, density, source, opportunities):
    """Plan-relative recovery and intervals; silence causes are model estimates."""
    old={e.id:e for e in reference.events};played=[e for e in plan.events if e.played]
    recovered=[e.id for e in played if not old[e.id].played]
    restored=[e.id for e in played if old[e.id].played and e.device_type=='FDD' and e.actual_duration>old[e.id].actual_duration+1e-8]
    current={e.id:e for e in plan.events}
    lost=[e.id for e in reference.events if e.played and not current[e.id].played]
    important=lambda e:e.role in ('lead','bass') or any(c.get('musical',{}).get('fddQuality',{}).get('important') for c in e.hardware.get('candidates',{}).values())
    raw=getattr(source,'source',source)
    planned_activity=activity(plan)
    frames=annotate_density(density.frames,planned_activity['primary']['timeline'])
    return {'frames':frames,'activity':planned_activity,'qualityActivity':activity(reference),
        'rawNotes':sum(len(raw.notes(t.index)) for t in raw.tracks),
        'normalizedNotes':sum(len(source.notes(t.index)) for t in source.tracks),
        'recoveredNotes':len(recovered),'recoveredIds':recovered,'restoredGates':len(restored),'restoredGateIds':restored,
        'lostVsQuality':lost,'omittedNotes':sum(not e.played for e in plan.events),
        'valuableOmittedNotes':sum(not e.played and important(e) for e in plan.events),
        'dropReasons':dict(Counter(e.reason for e in plan.events if not e.played)),
        'silence':silence_causes(plan,reference,opportunities),'qualitySilence':silence_causes(reference,reference,opportunities),
        'opportunities':opportunities,'scope':'MIDI and planned activity; not acoustic measurement',
        'dvdPrimaryPreserved':all(current[e.id]==e for e in reference.events if e.played and e.device_type=='DVD_SLED')}


def density_level(frames,seconds):
    if not frames:return 0.
    starts=[f['start'] for f in frames]
    return frames[max(0,bisect.bisect_right(starts,seconds)-1)]['level']


def silence_causes(plan, reference, opportunities):
    """Exclusive silence buckets, based on MIDI overlap and candidate evidence."""
    points=defaultdict(list);points[0.];points[plan.duration]
    def add(a,b,key):
        if b>a:points[a].append((key,1));points[b].append((key,-1))
    fdd_ids={ident for ident,lane in reference.hardware['physicalLanes'].items() if lane.startswith('fdd:')}
    for e in reference.events:
        if e.role=='percussion':continue
        add(e.start,e.start+e.duration,'source')
        if e.played and e.device_type=='FDD':
            add(e.end,e.start+e.duration,'qualityGate')
        elif not e.played:
            add(e.start,e.start+e.duration,'policyDrop' if e.reason=='FDD_QUALITY_OPTIONAL_COST' else 'conflict')
        if e.played and e.device_type!='FDD':add(e.actual_start,e.end,'otherDevice')
        if any(v.get('authorized') and 'NOTE_TOO_SHORT' not in v.get('qualityReasons',[]) for d,v in e.hardware.get('candidates',{}).items() if d in fdd_ids):
            add(e.start,e.start+e.duration,'suitable')
    for e in plan.events:
        if e.played and e.device_type=='FDD':add(e.actual_start,e.end,'active')
    for o in opportunities:
        if o['feasibleFdd']:add(o['start'],o['end'],'opportunity')
    hist=Counter();active=Counter();last=0.;one=0.
    for t,changes in sorted(points.items()):
        delta=t-last
        if active['active']==1 and active['opportunity']>0:one+=delta
        if not active['active'] and delta>0:
            cause=('naturalCompositionRest' if not active['source'] else
                'qualityGateOrSelection' if active['qualityGate'] or active['policyDrop'] else
                'noSuitableFddMaterial' if not active['suitable'] else
                'materialOnOtherDevices' if active['otherDevice'] else 'allocationOrMechanicalConflict')
            hist[cause]+=delta
        for key,change in changes:active[key]+=change
        last=t
    return {'zeroFddSecondsByCause':{k:round(v,6) for k,v in hist.items()},
        'oneFddWithFeasibleUnusedSourceSeconds':round(one,6),
        'scope':'source overlaps and full-lane recovery feasibility; causes are estimates'}


def annotate_density(frames,timeline):
    result=[];cursor=0
    for frame in frames:
        a,b=frame['start'],frame['end']
        while cursor<len(timeline) and timeline[cursor]['end']<=a:cursor+=1
        j=cursor;seconds=weighted=0.
        while j<len(timeline) and timeline[j]['start']<b:
            interval=timeline[j];overlap=max(0.,min(b,interval['end'])-max(a,interval['start']))
            seconds+=overlap;weighted+=overlap*interval['activeFdd'];j+=1
        result.append({**frame,'meanActiveFdd':round(weighted/seconds,3) if seconds else 0.})
    return result
