"""Musical preferences and optional, fully reserved FDD unison.

No transport decisions: both outputs consume this same deterministic plan.
"""
from collections import defaultdict
from dataclasses import replace
import statistics

from .hardware_profiles import HardwareDeviceState, HardwareNote, Verdict, evaluate, advance_state
from .performance import ReinforcementEvent


def phrase_context(notes, window):
    """Local same-track/channel onsets; chord tones do not imply fast changes."""
    lanes = defaultdict(list)
    for item in notes:
        lanes[(item['track'], item['span'].channel)].append(item)
    result = {}
    for items in lanes.values():
        onsets = sorted({i['span'].start for i in items})
        import bisect
        for position, item in enumerate(items):
            s = item['span']
            index = bisect.bisect_left(onsets, s.start)
            low, high = max(0, index-2), min(len(onsets), index+3)
            times = [t for t in onsets[low:high] if abs(t-s.start) <= window]
            neighbors = [i['span'] for i in items[max(0, position-4):position+5]
                         if abs(i['span'].start-s.start) <= window]
            gaps = [b-a for a,b in zip(times,times[1:]) if b>a]
            changes = [n for n in neighbors if n.start != s.start]
            repeated = sum(n.note == s.note for n in changes)/len(changes) if changes else 0.
            rate = 1/statistics.median(gaps) if gaps else 0.
            result[item['id']] = {'onsetsPerSecond': round(rate, 3),
                'repeatFraction': round(repeated, 3),
                'meanDuration': statistics.fmean(n.duration for n in neighbors) if neighbors else s.duration}
    return result


def preference(item, profile, phrase, policy, previous):
    if not policy['mechanicalAware'] or profile.name not in ('FDD', 'DVD_SLED'):
        return 0., {'reason': 'existing physical selection'}
    duration = item['span'].duration
    threshold = policy['dvdSustainThresholdMs']/1000.
    length = (duration-threshold)/(duration+threshold)
    phrase_length = (phrase['meanDuration']-threshold)/(phrase['meanDuration']+threshold)
    # Rapid pitch changes favor articulation; repeats favor continuous sustain.
    dynamic = min(1., phrase['onsetsPerSecond']/6.)*(1.-phrase['repeatFraction'])
    sustain = .65*length + .25*phrase_length - .35*dynamic + .2*phrase['repeatFraction']
    if item['role'] == 'bass': sustain += .15*(1.-dynamic)
    musical = policy['mechanicalPreferenceWeight']*sustain*(1 if profile.name=='DVD_SLED' else -1)
    continuity = policy['partContinuityWeight'] if previous else 0.
    return musical+continuity, {**phrase, 'sustainAffinity': round(sustain,4),
        'preferenceScore': round(musical+continuity,4), 'samePartDevice': previous,
        'reason': ('DVD sustain / stable phrase' if profile.name=='DVD_SLED' else 'FDD articulated phrase')}


def _chronology(profile, primaries, extras):
    state = HardwareDeviceState(position=0. if profile.name=='DVD_SLED' else None)
    result = {}
    sequence = [(e.actual_start,e.id,HardwareNote(e.played_hz,e.actual_duration,e.actual_start)) for e in primaries]
    sequence += [(e.start,'extra:'+str(i),HardwareNote(e.hz,e.duration,e.start)) for i,e in enumerate(extras)]
    for start, ident, note in sorted(sequence, key=lambda x:(x[0],x[1])):
        ev = evaluate(profile,note,state)
        if not ev.authorized or Verdict.BLOCKED in (ev.timing,ev.quality,ev.physical_load) or ev.ready_at>start+1e-8:
            return None
        result[ident] = ev
        advance_state(state,profile,note,ev)
    return result


class ChronologyCache:
    """Reuse an unchanged validated prefix, still check the complete new suffix.

    Local to one profile and planning pass; no global or cross-song cache.
    Snapshots retain the exact projection, including position and ready_at.
    """
    def __init__(self, profile):
        self.profile = profile
        self.sequence = []
        self.values = []
        self.states = [HardwareDeviceState(position=0. if profile.name=='DVD_SLED' else None)]

    @staticmethod
    def snapshot(state):
        return replace(state, hit_times=list(state.hit_times))

    def check(self, primaries, extras):
        sequence = [(e.actual_start,e.id,HardwareNote(e.played_hz,e.actual_duration,e.actual_start)) for e in primaries]
        sequence += [(e.start,'extra:'+str(i),HardwareNote(e.hz,e.duration,e.start)) for i,e in enumerate(extras)]
        sequence.sort(key=lambda x:(x[0],x[1]))
        common = 0
        while common < min(len(sequence),len(self.sequence)) and sequence[common] == self.sequence[common]:
            common += 1
        self.sequence = self.sequence[:common]
        self.values = self.values[:common]
        self.states = self.states[:common+1]
        state = self.snapshot(self.states[-1])
        for start, ident, note in sequence[common:]:
            ev = evaluate(self.profile,note,state)
            if not ev.authorized or Verdict.BLOCKED in (ev.timing,ev.quality,ev.physical_load) or ev.ready_at>start+1e-8:
                return None
            advance_state(state,self.profile,note,ev)
            self.sequence.append((start,ident,note))
            self.values.append(ev)
            self.states.append(self.snapshot(state))
        return {item[1]:ev for item,ev in zip(self.sequence,self.values)}


def add_unison(plan, profiles, priority):
    """Reserve whole performed notes only after independent voices are complete.

    A complete chronology including earlier dubs and future primary notes must
    remain feasible and must not degrade a primary's physical quality score.
    This is deliberately conservative; no partial or late unison attacks.
    """
    policy = plan.policy
    if not policy['fddUnisonEnabled'] or policy['fddUnisonMaxVoices'] < 2:
        plan.hardware['unison'] = {'enabled': False, 'events': 0, 'seconds': 0., 'primaryDropsAdded': 0}
        return
    primaries = {d: [e for e in plan.events if e.played and e.device_id==d] for d in profiles}
    baseline = {d: _chronology(p,primaries[d],[]) for d,p in profiles.items() if p.name=='FDD'}
    candidates = sorted([e for e in plan.events if e.played and e.device_type=='FDD'
        and e.velocity>=policy['fddUnisonMinVelocity']
        and .04<=e.actual_duration<=policy['fddUnisonMaxDurationMs']/1000.],
        key=lambda e:(e.actual_start,-priority(e),e.id))
    from . import fdd_quality as quality
    quality_mode=quality.enabled(policy) or policy.get('arrangementPreset') in ('dvd_lead_low_fdd','fdd_quality_adaptive')
    added = []; rejected = 0
    for source in candidates:
        value=source.hardware.get('candidates',{}).get(source.device_id,{}).get('musical',{}).get('fddQuality',{})
        if quality_mode and (value.get('musicalValue',0)<policy['fddQualityUnisonPriority'] or
            sum(e.duration for e in added)+source.actual_duration>plan.duration*policy['fddQualityUnisonDuty']):
            continue
        if policy.get('arrangementPreset')=='dvd_lead_low_fdd' and value.get('cost',float('inf'))>policy['fddQualityOptionalCost']:
            continue
        if policy.get('arrangementPreset')=='fdd_quality_adaptive':
            from .fdd_adaptive import density_level
            if density_level(plan.hardware.get('adaptiveDensityFrames',[]),source.actual_start)>.15:
                continue
        existing = [e for e in plan.reinforcements if e.source_id==source.id and profiles.get(e.device_id)
                    and profiles[e.device_id].name=='FDD']
        if existing: continue
        for ident in sorted(baseline, key=lambda d:(len(primaries[d]),d)):
            if ident == source.device_id or baseline[ident] is None: continue
            extras = [e for e in plan.reinforcements if e.device_id==ident]
            dub = ReinforcementEvent(source.id,ident,source.actual_start,source.actual_duration,
                source.played_hz,source.velocity,kind='UNISON',source_device=source.device_id,
                reason='FDD accent; full idle reservation; independent voices preserved',
                score=priority(source),semantic_compatibility='same pitch, onset and performed duration',role=source.role)
            if any(e.actual_start < source.end-1e-9 and e.end > source.actual_start+1e-9 for e in primaries[ident]):
                rejected += 1; continue
            if any(e.start < source.end-1e-9 and e.start+e.duration > source.actual_start+1e-9 for e in extras):
                rejected += 1; continue
            if quality_mode:
                state=HardwareDeviceState();history=[]
                prior=[(e.actual_start,e.actual_duration,e.played_hz) for e in primaries[ident] if e.end<=source.actual_start]
                prior += [(e.start,e.duration,e.hz) for e in extras if e.start+e.duration<=source.actual_start]
                for start,duration,hz in sorted(prior):
                    note=HardwareNote(hz,duration,start);ev=evaluate(profiles[ident],note,state)
                    advance_state(state,profiles[ident],note,ev)
                    quality.reserve(history,start,duration,(ev.step_rate or 0)*duration,policy['fddQualityRestMs']/1000.)
                cost=quality.mechanical_cost(profiles[ident],state,source.played_hz,source.actual_duration,source.actual_start,history,policy)
                if cost['cost']>policy['fddQualityOptionalCost']: continue
            combined = _chronology(profiles[ident],primaries[ident],extras+[dub])
            if combined is None or any(combined[e.id].score+1e-8<baseline[ident][e.id].score for e in primaries[ident]):
                rejected += 1; continue
            plan.reinforcements.append(dub); added.append(dub); break
    plan.hardware['unison'] = {'enabled': True, 'events': len(added),
        'seconds': round(sum(e.duration for e in added),3), 'rejectedReservations': rejected,
        'primaryDropsAdded': 0, 'maxVoices': policy['fddUnisonMaxVoices']}
