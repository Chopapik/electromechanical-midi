"""MIDI expression sidecar and device-specific tonal decisions; no allocation policy.

Audio tails never reserve a physical voice. The virtual lane scheduler may shorten
one tail when the next PRIMARY needs its actuator.
"""
from __future__ import annotations
import bisect
import dataclasses
import math


@dataclasses.dataclass(frozen=True)
class Curve:
    times: tuple[float, ...] = (0.,)
    values: tuple[float, ...] = (1.,)

    def at(self, t, np=None):
        if np is not None:
            return np.interp(t, self.times, self.values)
        i = bisect.bisect_right(self.times, t)-1
        if i < 0: return self.values[0]
        if i+1 >= len(self.times): return self.values[-1]
        f = (t-self.times[i]) / max(1e-12, self.times[i+1]-self.times[i])
        return self.values[i]*(1-f)+self.values[i+1]*f

    def integral(self, t, np=None):
        # Exact integral of the linearly interpolated frequency curve. This
        # keeps phase continuous through bends in both Python and NumPy paths.
        result = t*self.values[0]
        for i in range(1, len(self.times)):
            lo, hi = self.times[i-1:i+1]; delta = self.values[i]-self.values[i-1]
            if np is None:
                x = max(0., min(t-lo, hi-lo)); tail = max(0., t-hi)
            else:
                x = np.clip(t-lo, 0., hi-lo); tail = np.maximum(0., t-hi)
            result += delta*(x*x/(2*max(1e-12,hi-lo))+tail)
        return result


@dataclasses.dataclass(frozen=True)
class TonalArticulation:
    profile: str
    device: str
    attack: float
    decay: float
    sustain: float
    release: float
    gate: float
    brightness: float
    transient: float
    intensity: float
    legato: bool = False
    staccato: bool = False
    strum_like: bool = False
    source_duration: float = 0.
    velocity: int = 100
    role: str = ''
    program: int = 0
    pedal: bool = False
    gain: Curve = Curve()
    frequency: Curve = Curve()
    modulation: Curve = Curve((0.,), (0.,))
    raw: bool = False
    extreme: bool = False
    extreme_v2: bool = False
    extreme_v15: bool = False

    def debug(self):
        return {'profile':self.profile,'deviceType':self.device,'attackMs':self.attack*1000,
            'decayMs':self.decay*1000,'releaseMs':self.release*1000,'gateMs':self.gate*1000,
            'sourceDuration':self.source_duration,'velocity':self.velocity,'semanticRole':self.role,
            'program':self.program,'legato':self.legato,'staccato':self.staccato,
            'strumLike':self.strum_like,'sustainPedal':self.pedal,'ccGainAtStart':self.gain.values[0],
            'raw':self.raw, 'extreme':self.extreme, 'extremeV2':self.extreme_v2, 'extremeV15':self.extreme_v15, 'sustainLevel':self.sustain,
            'brightness':self.brightness, 'transient':self.transient}


def capture(source):
    """Keep timed channel-wide expression, including conductor/controller tracks."""
    raw = getattr(source, 'source', source)
    streams = {}
    for e in raw.expression_events():
        streams.setdefault(str(e['channel']), []).append(e)
    for channel, events in streams.items():
        events.append({'time':raw.duration,'track':-1,'order':0,'channel':int(channel),'kind':'end','value':0})
        events.sort(key=lambda e:(e['time'],e['track'],e['order']))
    return streams


def _state(events, time):
    state={'volume':100,'expression':127,'modulation':0,'pressure':0,'bend':0,
           'range':2.,'rpnMSB':127,'rpnLSB':127,'rangeMSB':2,'rangeLSB':0,'pedal':0,'program':0}
    for e in events:
        if e['time'] > time+1e-9: break
        _update(state,e)
    return state


def _update(s,e):
    kind,value=e['kind'],e['value']
    if kind=='program_change': s['program']=value
    elif kind=='pitchwheel': s['bend']=value
    elif kind in ('aftertouch','polytouch'): s['pressure']=value
    elif kind=='control_change':
        cc=e['control']
        key={7:'volume',11:'expression',1:'modulation',64:'pedal',101:'rpnMSB',100:'rpnLSB'}.get(cc)
        if key: s[key]=value
        if cc in (6,38) and (s['rpnMSB'],s['rpnLSB'])==(0,0):
            s['rangeMSB' if cc==6 else 'rangeLSB']=value
            s['range']=s['rangeMSB']+s['rangeLSB']/100
        if cc==121:
            s.update(expression=127,modulation=0,pressure=0,bend=0,pedal=0,rpnMSB=127,rpnLSB=127)
        if cc in (120,123): s['pedal']=0


def _curves(events, start, length, hz):
    s=_state(events,start)
    def values():
        return ((s['volume']/127)*(s['expression']/127)*(1+.1*s['pressure']/127),
                hz*2**(s['bend']/8192*s['range']/12),s['modulation']/127)
    times=[0.]; vals=[values()]
    for e in events:
        dt=e['time']-start
        if not 1e-9 < dt < length: continue
        _update(s,e); v=values()
        if v==vals[-1]: continue
        # A short ramp, never chromatic retriggers or source-onset edits.
        ramp=min(.005,dt-times[-1])
        if dt-ramp>times[-1]: times.append(dt-ramp); vals.append(vals[-1])
        times.append(dt); vals.append(v)
    return tuple(Curve(tuple(times),tuple(v[i] for v in vals)) for i in range(3))


def chord_context(events):
    """Source onset groups; simultaneous chord members are not legato notes."""
    context={}; strums=[]
    tracks={}
    for e in events: tracks.setdefault(e.track,[]).append(e)
    for notes in tracks.values():
        notes.sort(key=lambda e:(e.start,e.note,e.id))
        groups=[]
        for e in notes:
            if not groups or e.start-groups[-1][0].start>1e-9: groups.append([])
            groups[-1].append(e)
        previous_end=-math.inf
        for i,g in enumerate(groups):
            next_start=groups[i+1][0].start if i+1<len(groups) else math.inf
            spacing=min(g[0].start-groups[i-1][0].start if i else math.inf,next_start-g[0].start)
            for e in g: context[e.id]=(previous_end>=e.start-1e-3,spacing,False)
            previous_end=max(e.start+e.duration for e in g)
        # Nonoverlapping candidate windows, monotonic pitches and distinct onsets.
        i=0
        while i<len(groups):
            window=[e for g in groups[i:i+6] if g[0].start-groups[i][0].start<=.05 for e in g]
            pitches=[e.note for e in window]
            ordered=all(a<=b for a,b in zip(pitches,pitches[1:])) or all(a>=b for a,b in zip(pitches,pitches[1:]))
            if (len(set(pitches))>=3 and window[-1].start>window[0].start+1e-6 and ordered
                    and all(e.start+e.duration>window[-1].start for e in window)):
                strums.append([e.id for e in window])
                for e in window:
                    legato,gap,_=context[e.id]; context[e.id]=(legato,gap,True)
                i+=len(set(e.start for e in window))
            else: i+=1
    return context,strums


def resolve(plan):
    context,strums=chord_context(plan.events); decisions={}
    classifications={c['index']:c for c in plan.analysis.get('trackClassification',[])}
    for e in plan.events:
        if not e.played or e.device_type not in ('FDD','DVD_SLED','STEPPER_FREE','VHS'): continue
        stream=[x for x in plan.expression.get(str(e.channel),[])
                if x['kind']!='polytouch' or x.get('note')==e.note]
        state=_state(stream,e.start)
        # Older/manually constructed plans may have program metadata only.
        program=state['program'] if stream else next(iter(plan.analysis.get('trackPrograms',{}).get(str(e.track),[0])),0)
        role=classifications.get(e.track,{}).get('finalRole',e.role)
        plucked=24<=program<40 or program<8 or role in ('GUITAR','BASS','KEYS')
        legato,gap,strum=context.get(e.id,(False,math.inf,False))
        # Chord overlap is not a monophonic legato gesture for guitar/keys.
        legato=legato and not plucked
        short=e.duration<=.12
        v=e.velocity/127; smooth=e.device_type in ('DVD_SLED','VHS')
        attack=(.004 if e.device_type=='FDD' else .008 if e.device_type=='DVD_SLED' else .018)*(1.3-.6*v)
        if legato: attack*=.45
        attack=min(attack,max(.0005,e.actual_duration*.18))
        decay=min(.28 if plucked else .12,max(.012,e.actual_duration*.45))*(1.1-.25*v)
        sustain=(.22+.15*v if plucked else .78)
        release=(.045 if e.device_type=='FDD' else .07 if e.device_type=='DVD_SLED' else .095)
        if short: release=min(release,e.duration*.16)
        if gap<.15: release=min(release,.018)
        gate=e.actual_duration; pedal=False
        source_off=e.start+e.duration
        # Sustain extends audible gate only; subsequent PRIMARY always preempts.
        if _state(stream,source_off)['pedal']>=64 and e.actual_duration>=e.duration-1e-6:
            pedal=True
            up=next((x['time'] for x in stream if x['time']>source_off and
                x['kind']=='control_change' and (x.get('control')==64 and x['value']<64 or x.get('control') in (120,121,123))),max(plan.duration,max((x['time'] for x in stream),default=0.)))
            gate=max(gate,up-e.start)
        gain,freq,mod=_curves(stream,e.start,gate+release,e.played_hz or 0.)
        decisions[e.id]=TonalArticulation('PLUCKED' if plucked else 'CONTINUOUS',e.device_type,
            attack,decay,sustain,release,gate,.15+.75*v,.1+.35*v,v**.65,
            legato,short,strum and plucked,e.duration,e.velocity,role,program,pedal,gain,freq,mod)
    strums=[g for g in strums if any(ident in decisions and decisions[ident].profile=='PLUCKED' for ident in g)]
    return decisions,strums


def retarget(art, device, duration, velocity, offset=0.):
    """Inherit source expression/profile, adapt only actuator attack and extra gate."""
    def shifted(curve):
        return Curve((0.,)+tuple(t-offset for t in curve.times if t>offset),
                     (curve.at(offset),)+tuple(v for t,v in zip(curve.times,curve.values) if t>offset))
    factor={'FDD':1.,'DVD_SLED':2.,'STEPPER_FREE':2.,'VHS':4.5}
    return dataclasses.replace(art,device=device,gate=duration,velocity=velocity,
        attack=min(duration*.18,art.attack*factor.get(device,1)/factor.get(art.device,1)),
        intensity=(velocity/127)**.65,gain=shifted(art.gain),frequency=shifted(art.frequency),modulation=shifted(art.modulation))


def apply_mode(art, mode):
    """Temporary diagnostic exaggeration, after semantic/physical decisions."""
    if mode == 'raw':
        return dataclasses.replace(art, attack=.001, decay=0., sustain=1., release=.002, raw=True)
    if mode == 'extreme_v15' and art.profile == 'PLUCKED':
        v1=apply_mode(art,'extreme')
        v2=apply_mode(art,'extreme_v2')
        fields=('attack','decay','sustain','release','brightness','transient')
        return dataclasses.replace(art,**{k:(getattr(v1,k)+getattr(v2,k))*.5 for k in fields},
            extreme=True,extreme_v15=True,extreme_v2=False)
    if mode == 'extreme_v2' and art.profile == 'PLUCKED':
        v=art.velocity/127
        # Source length shapes sound; the allocated gate stays untouched.
        x=max(0.,min(1.,(art.source_duration-.08)/.72))
        blend=x*x*(3-2*x)
        dvd=art.device=='DVD_SLED'
        attack=(.015-.010*v)*(1-blend)+(.070-.030*v)*blend
        release=(.150+.150*v)*(1-blend)+(.700+.400*v)*blend
        return dataclasses.replace(art,
            attack=min(art.gate*.35,attack*(1.08 if dvd else 1.)),
            decay=(.180-.080*v)*(1-blend)+(.550-.200*v)*blend,
            sustain=(.05+.05*v)*(1-blend)+(.05+.07*v)*blend,
            release=release*(1. if dvd else .92),
            brightness=.02+2.0*v**4, transient=.02+4.2*v**4,
            extreme=True,extreme_v2=True)
    if mode != 'extreme' or art.profile != 'PLUCKED':
        return art
    v=art.velocity/127
    scale=min(1., art.gate/.12)
    return dataclasses.replace(art, attack=(.040-.015*v)*scale,
        decay=(.350-.100*v)*scale, sustain=.10+.10*v,
        release=min((.300+.200*v)*scale, art.gate*.5) if scale<1 else .300+.200*v,
        brightness=.03+1.5*v**3, transient=.05+2.2*v**3, extreme=True)


def envelope(t, art, length, np=None):
    """Amplitude shape consumed by both actual PCM render paths."""
    exp=math.exp if np is None else np.exp
    minimum=min if np is None else np.minimum; maximum=max if np is None else np.maximum
    if art.raw:
        return minimum(1.,t/.001)*minimum(1.,maximum(0.,length-t)/.002)
    decay_time=art.decay/4 if art.extreme else art.decay
    shape=minimum(1.,t/max(.0005,art.attack))*(art.sustain+(1-art.sustain)*exp(-maximum(0.,t-art.attack)/max(.001,decay_time)))
    shape*=exp(-maximum(0.,t-art.gate)/max(.001,art.release/4))
    return shape*minimum(1.,maximum(0.,length-t)/.006)


def render(t, art, hz, length, np=None):
    if art.extreme_v15:
        # One envelope/gate, halfway between existing mechanical carriers.
        v1=dataclasses.replace(art,extreme_v15=False,extreme_v2=False)
        v2=dataclasses.replace(art,extreme_v15=False,extreme_v2=True)
        return .5*(render(t,v1,hz,length,np)+render(t,v2,hz,length,np))
    exp=math.exp if np is None else np.exp; sin=math.sin if np is None else np.sin
    minimum=min if np is None else np.minimum; maximum=max if np is None else np.maximum
    phase=art.frequency.integral(t,np)
    # Modulation is only enabled by MIDI CC1; bounded mechanical vibrato.
    phase+=art.modulation.at(t,np)*hz*.002/(2*math.pi*5)*(1-sin(2*math.pi*5*t+math.pi/2))
    if art.device=='VHS':
        carrier=sin(2*math.pi*phase)+(.08+.16*art.brightness)*sin(6*math.pi*phase)
    else:
        sharp=(14 if art.device=='FDD' else 9)*(1.25-.45*art.brightness)
        pulse=exp(-(phase%1)*sharp)
        resonance=900 if art.device=='FDD' else 1300 if art.device=='DVD_SLED' else 600
        carrier=pulse*(.55+(.25+.2*art.brightness)*sin(2*math.pi*resonance*t))
    if not art.raw:
        # EXTREME deliberately puts a conspicuous mechanical burst at the
        # envelope peak. Regular ARTICULATED math is unchanged.
        burst=(exp(-abs(t-art.attack)/.003) if art.extreme else exp(-t/.003))
        carrier+=art.transient*(.45 if art.extreme_v2 and art.device=='DVD_SLED' else 1.)*burst*sin(2*math.pi*(1800 if art.device=='FDD' else 1400)*t)
    if art.extreme_v2 and art.device!='VHS':
        v=art.velocity/127
        dvd=art.device=='DVD_SLED'
        burst=exp(-abs(t-art.attack)/(.0045 if dvd else .0018))
        # Deterministic short mechanical impact: inharmonic modes, no samples.
        impact=(sin(2*math.pi*(1250 if dvd else 2300)*t)
                +.55*sin(2*math.pi*(2170 if dvd else 3710)*t)
                +.30*sin(2*math.pi*(3190 if dvd else 5270)*t))
        carrier+=(.03+3.2*v**4)*burst*impact*(.45 if dvd else 1.)
        # Velocity changes sustained body/harmonic energy as well as gain.
        carrier+=(.04+.28*v*v)*sin(2*math.pi*phase)
        carrier+=(.02+.25*v**4)*sin((4 if dvd else 8)*math.pi*phase)
    return carrier*envelope(t,art,length,np)*art.intensity*art.gain.at(t,np)
