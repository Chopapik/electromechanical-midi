"""Phrase-aware orchestration over the existing physical allocator.

No filename rules, generated harmony, new clocks or weaker actuator limits.
Source attacks remain separate; optional speakers never occupy a reserved vocal/FX.
"""
from bisect import bisect_left, bisect_right
from collections import defaultdict, Counter
from statistics import median

PRESET = 'universal'


def enabled(policy):
    return policy.get('arrangementPreset') == PRESET


class Phrases:
    def __init__(self, notes, context, source, fx_tracks):
        self.context = context
        self.next_voice = {}
        self.next_part = {}
        self.cadence = {}
        self.rank = {}
        self.upper_bass = set()
        part_notes = defaultdict(list)
        self.reserved = {'lead': [], 'fx': []}
        self.reservation_starts = {}
        self.last_attack = {}
        self.last_voice = {}
        self.usage = Counter()
        self.routes = Counter()
        self.fdd_rejected = 0
        self.fallbacks = 0
        raw = getattr(source, 'source', source)
        self.tempos = raw.tempo._segments
        self.tempo_times = [s.seconds for s in self.tempos]
        voices = defaultdict(list)
        parts = defaultdict(list)
        groups = defaultdict(list)
        for item in notes:
            span = item['span']
            if item['role'] == 'percussion': continue
            voices[self.voice(item)].append(item)
            part_notes[item['track'],span.channel].append(item)
            parts[span.channel, item['track']].append(span.start)
            groups[span.start, item['track'], span.channel].append(item)
            if item['role'] == 'lead': self.reserved['lead'].append((span.start, span.end))
            if item['track'] in fx_tracks: self.reserved['fx'].append((span.start, span.end))
        for items in part_notes.values():
            active=[]
            for item in sorted(items,key=lambda i:(i['span'].start,i['span'].note,i['order'])):
                span=item['span']
                active=[n for n in active if n.end>span.start+1e-9]
                # A track labelled bass can contain a complete strummed guitar
                # chord. Only its concurrent upper voices may use melodic relief;
                # a monophonic bass jump is never reclassified this way.
                if item['role']=='bass' and any(n.note<=span.note-12 for n in active):
                    self.upper_bass.add(item['id'])
                active.append(span)
        for voice in voices.values():
            voice.sort(key=lambda n:(n['span'].start,n['order']))
            for a,b in zip(voice,voice[1:]): self.next_voice[a['id']] = b['span'].start
            for index,item in enumerate(voice):
                local=voice[max(0,index-2):index+3]
                gaps=[b['span'].start-a['span'].start for a,b in zip(local,local[1:])
                      if b['span'].start>a['span'].start]
                self.cadence[item['id']]=median(gaps) if gaps else float('inf')
        for part in parts.values(): part[:] = sorted(set(part))
        for item in notes:
            if item['role']=='percussion': continue
            times=parts[item['span'].channel,item['track']]
            i=bisect_right(times,item['span'].start+1e-9)
            self.next_part[item['id']] = times[i] if i<len(times) else float('inf')
        for group in groups.values():
            # Retain a bass anchor, a salient upper voice and longer inner beds
            # before duplicates. All are real source notes; no chord is invented.
            low=min(i['span'].note for i in group); high=max(i['span'].note for i in group)
            group.sort(key=lambda i:(i['span'].note not in (low,high),
                -i['span'].duration,-i['span'].velocity,i['order']))
            for index,item in enumerate(group): self.rank[item['id']]=index
        for kind in self.reserved:
            merged=[]
            for a,b in sorted(self.reserved[kind]):
                if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
                else:merged.append((a,b))
            self.reserved[kind]=merged
            self.reservation_starts[kind]=[a for a,b in merged]

    def voice(self, item):
        return (item['track'],item['span'].channel,self.context[item['id']]['voiceId'])

    def beat(self, start):
        i=max(0,bisect_right(self.tempo_times,start)-1)
        return self.tempos[i].tempo/1e6

    def prioritized(self, notes):
        # At the SAME timestamp, one voice from each part precedes the additional
        # chord tones of an already represented part. Preserve percussion order.
        bands={'lead':0,'bass':1,'percussion':2,'harmony':3}
        return sorted(notes,key=lambda i:(i['span'].start,bands[i['role']],
            self.rank.get(i['id'],0),0 if i['role']=='percussion' else -i['span'].velocity,
            i['span'].duration if i['role']=='percussion' else -min(i['span'].duration,2.),
            i['track'],i['order']))

    def occupied(self, kind, start, end):
        intervals=self.reserved[kind];starts=self.reservation_starts[kind]
        i=bisect_left(starts,end-1e-9)
        return i>0 and intervals[i-1][1]>start+1e-9

    def pool(self, item, slots, profiles, lead, fx, accompaniment, fx_tracks, pin):
        if item['role']=='percussion':
            return [s for s in slots.values() if profiles[s.device.id].name=='HDD_PERCUSSION']
        if item['role']=='lead': return lead+fx+accompaniment
        if item['track'] in fx_tracks: return fx+accompaniment
        # Secondary speaker is a melodic relief voice. Long beds and low bass
        # remain on motors; main speaker is available only outside source vocal.
        span=item['span']
        melodic=((item['role']!='bass' and span.note>=60 or item['id'] in self.upper_bass and span.note>=55)
                 and span.duration<=.65)
        return accompaniment+(fx+lead if melodic else [])

    def gate(self, item, profile, duration, speaker_role=None, fx_event=False, source_gate=None):
        span=item['span']; kind=profile.name
        source_gate=span.duration if source_gate is None else source_gate
        if kind=='HDD_PERCUSSION': return duration
        if kind=='FDD':
            duration=min(source_gate,.4)
            # Free the carriage before the next attack in this melodic voice;
            # a neighbouring chord voice does not truncate this note.
            following=self.next_voice.get(item['id'],float('inf'))
            duration=min(duration,max(0.,following-span.start-.003))
        elif kind=='VHS':
            duration=source_gate
            # A MIDI legato overlap must not silence the next vocal syllable.
            # Polyphonic notes remain independent and can use other devices.
            if item['role']=='lead' or fx_event:
                duration=min(duration,self.next_part[item['id']]-span.start)
            category=speaker_role
            if (item['role']!='lead' and category=='lead'
                    and self.occupied('lead',span.start,span.start+duration+.012)):
                return None
            if category=='fx' and not fx_event and self.occupied('fx',span.start,span.start+duration+.012):
                return None
        elif kind=='DVD_SLED':
            duration=source_gate
        return max(.01,duration)

    def bonus(self, item, profile, ident, arrival, played, shifted, base, speaker_role=None):
        span=item['span']; kind=profile.name
        detail=dict(base)
        if kind=='VHS':
            primary=speaker_role=='lead'
            score=(3.5 if primary else 2.5) if item['role']=='lead' else .25
            detail.update(reason='reserved melody / secondary melodic relief',universal=True)
        else:
            affinity=base.get('sustainAffinity',0.)
            score=(1.25*affinity if kind=='DVD_SLED' else -1.25*affinity)
            if kind=='DVD_SLED' and span.duration>=.65:score+=.35
            if kind=='FDD':score-=.18*min(1.,span.duration/.4)
            detail.update(universal=True,reason='local phrase, range and attack-aware allocation')
        voice=self.voice(item)
        if self.last_voice.get(voice)==ident:score+=.35
        # Octave displacement relative to THIS device's explicit transpose is
        # a fidelity cost; legitimate source bass and speaker transposes remain.
        score-=.16*abs(played-shifted)/12.
        score-=2.*(arrival-span.start)
        detail['registerOctaves']=abs(played-shifted)/12.
        detail['voiceId']=voice[2]
        detail['localCadenceBeats']=round(self.cadence[item['id']]/self.beat(span.start),3) if self.cadence[item['id']]!=float('inf') else None
        return score,detail

    def reserved_conflict(self,item,device,arrival,duration,fx_tracks):
        if device.type!='VHS':return False
        category='fx' if device.role=='fx' else 'lead'
        own=item['role']=='lead' if category=='lead' else item['track'] in fx_tracks
        return not own and self.occupied(category,arrival,arrival+duration+.012)

    def accepted(self,item,ident,kind,start):
        if item['role']=='percussion':return
        self.last_attack[ident]=start
        self.last_voice[self.voice(item)]=ident
        self.usage[ident]+=1
        self.routes[kind]+=1

    def report(self):
        return {'version':1,'scope':'source-derived phrases; software planning, not acoustic measurement',
            'routes':dict(self.routes),'fddAttackCandidatesDeferred':self.fdd_rejected,'allocatedByDevice':dict(self.usage),
            'speakerAndMotorFallbacks':self.fallbacks,'synthesizedNotes':0}
