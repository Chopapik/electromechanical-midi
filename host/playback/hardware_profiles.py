"""Physical planning profiles. Unknown safety data never implies unlimited drive.

No Serial/BLE imports: this entire module can be exercised offline.
"""
from __future__ import annotations
import dataclasses
import enum
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = ROOT / 'config/hardware-profiles'

class Verdict(str, enum.Enum):
    PASS='PASS'; DEGRADED='DEGRADED'; UNKNOWN='UNKNOWN'; BLOCKED='BLOCKED'

@dataclasses.dataclass(frozen=True)
class HardwareQuantity:
    value: object
    confidence: str
    evidence_type: str
    source: str
    unit: str = ''
    uncertainty: object = None

    @classmethod
    def parse(cls, data):
        if not isinstance(data,dict): raise ValueError('hardware quantity must include metadata')
        confidence=data['confidence']; evidence=data['evidenceType']; value=data['value']
        if confidence not in ('HIGH','MEDIUM','LOW','UNKNOWN') or evidence not in ('FACT','DERIVED','HYPOTHESIS','MEASURED'):
            raise ValueError('invalid hardware evidence/confidence')
        def finite(v):
            if isinstance(v,float) and not math.isfinite(v): raise ValueError('non-finite hardware quantity')
            if isinstance(v,dict):
                for x in v.values(): finite(x)
            if isinstance(v,(list,tuple)):
                for x in v: finite(x)
        finite(value)
        finite(data.get('uncertainty'))
        if value is None and confidence!='UNKNOWN': raise ValueError('null quantity requires UNKNOWN confidence')
        if not data.get('source'): raise ValueError('hardware source required')
        return cls(value,confidence,evidence,data['source'],data.get('unit',''),data.get('uncertainty'))

    def as_dict(self):
        return dict(value=self.value,confidence=self.confidence,evidenceType=self.evidence_type,
                    source=self.source,unit=self.unit,uncertainty=self.uncertainty)

@dataclasses.dataclass(frozen=True)
class HardwareProfile:
    name: str
    quantities: dict[str,HardwareQuantity]
    lane: str | None = None

    def get(self,key):
        q=self.quantities.get(key)
        return q.value if q else None

    def overlay(self, overrides):
        result=dict(self.quantities)
        for key,value in overrides.items():
            if key not in result and key!='executionMinStepUs': raise ValueError('unknown hardware quantity: '+key)
            quantity=HardwareQuantity.parse(value)
            previous=result.get(key)
            if (previous and previous.evidence_type=='MEASURED' and quantity.value is not None
                    and quantity.evidence_type!='MEASURED'):
                continue
            result[key]=quantity
        profile=dataclasses.replace(self,quantities=result)
        profile.validate()
        return profile

    def validate(self):
        for key in ('pitchRatio','accelerationLimit','travelSteps','minCycles','executionMinStepUs','reversalIntervalMs', 'datasheetMinStepMs','minNoteFloorMs','preferredNoteMs',
                    'maxNoteChangeRatePerSec','parkMs','settleMs','strikeMs','nominalStartToStartMs',
                    'burstWindowMs','maxContinuousHitsPerSec','maxBurstHitsPerSec','transitionCycles','modalTransientMs'):
            value=self.get(key)
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or value<=0):
                raise ValueError('hardware '+key+' must be positive or UNKNOWN')
        for key in ('parkMs','settleMs','strikeMs','reversalIntervalMs'):
            v=self.get(key)
            if v is not None and not 1<=round(v*1000)<=2147483647:
                raise ValueError('execution timing outside microsecond protocol bounds')
        travel=self.get('travelSteps')
        if travel is not None and self.name in ('FDD','DVD_SLED') and (int(travel)!=travel or travel>(255 if self.name=='FDD' else 32767)):
            raise ValueError('travel exceeds protocol counter bounds')
        for key in ('musicalHz','stableHz','preferredHz','musicalStepRate','stableStepRate','preferredStepRate'):
            v=self.get(key)
            if v is not None and (len(v)!=2 or not 0<v[0]<=v[1]): raise ValueError('invalid hardware range: '+key)
        return self

    def as_dict(self):
        return {'id':self.name,'lane':self.lane,'quantities':{k:q.as_dict() for k,q in self.quantities.items()}}

class HardwareRegistry:
    def __init__(self, directory=PROFILE_DIR):
        data=json.loads((Path(directory)/'theoretical.json').read_text())
        instances=json.loads((Path(directory)/'instances.json').read_text())
        if data['schemaVersion']!=1 or instances['schemaVersion']!=1: raise ValueError('hardware schema version')
        self.profiles={k:HardwareProfile(k,{n:HardwareQuantity.parse(q) for n,q in v.items()}).validate()
                       for k,v in data['profiles'].items()}
        self.instances={k.lower():v for k,v in instances['instances'].items()}; self.protocol=data['protocolConstants']
        for lane,instance in self.instances.items(): self.effective(instance['profile'],lane)

    def effective(self,name,lane=None,overrides=None):
        profile=dataclasses.replace(self.profiles[name],lane=lane)
        instance=self.instances.get(lane.lower() if lane else None,{})
        if instance.get('profile')==name: profile=profile.overlay(instance.get('quantities',{}))
        return profile.overlay(overrides or {})

@dataclasses.dataclass
class HardwareDeviceState:
    current_frequency: float | None = None
    target_frequency: float | None = None
    current_step_rate: float = 0.
    target_step_rate: float = 0.
    direction: int = 1
    position: float | None = None
    position_confidence: str = 'UNKNOWN'
    playing: bool = False
    last_event_time: float | None = None
    ready_at: float = 0.
    thermal_state: object = None
    thermal_ready_at: float | None = None
    impact_ready_at: float | None = None
    physical_state_confidence: str = 'UNKNOWN'
    percussion_state: str = 'IDLE'
    hit_times: list[float] = dataclasses.field(default_factory=list)
    away_steps: float = 0.
    travel_reversals: int = 0

    def as_dict(self): return dataclasses.asdict(self)

@dataclasses.dataclass(frozen=True)
class HardwareNote:
    audio_frequency: float | None
    duration: float
    start: float
    direction: int | None = None
    aggressive: bool = False
    pulse_ms: float | None = None
    peak_current_a: float | None = None
    impact_energy_j: float | None = None
    excursion_rad: float | None = None
    waveform: str = 'square'

    def __post_init__(self):
        for key in ('audio_frequency','duration','start','pulse_ms','peak_current_a','impact_energy_j','excursion_rad'):
            value=getattr(self,key)
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0):
                raise ValueError('invalid physical note '+key)
        if self.duration<=0 or self.audio_frequency==0 or self.direction not in (None,-1,1):
            raise ValueError('invalid physical note duration/frequency/direction')

@dataclasses.dataclass(frozen=True)
class HardwareEvaluation:
    timing: Verdict
    quality: Verdict
    physical_load: Verdict
    score: float
    reasons: tuple[str,...]
    quality_reasons: tuple[str,...]
    ready_at: float
    transition_time: float
    braking_distance: float | None
    audio_frequency: float | None
    step_rate: float | None
    harmonic_risk: float = 0.
    reversal_rate: float | None = None
    round_trip_rate: float | None = None
    authorized: bool = True
    readiness: dict = dataclasses.field(default_factory=dict)

    def as_dict(self):
        return {'timing':self.timing.value,'quality':self.quality.value,'physicalLoad':self.physical_load.value,
                'qualityScore':round(self.score,4),'reasons':list(self.reasons),'qualityReasons':list(self.quality_reasons),
                'readyAt':self.ready_at,'transitionTime':self.transition_time,'brakingDistance':self.braking_distance,
                'audioFrequency':self.audio_frequency,'stepRate':self.step_rate,'harmonicRisk':self.harmonic_risk,
                'reversalEventRate':self.reversal_rate,'roundTripRate':self.round_trip_rate,'authorized':self.authorized,'readiness':self.readiness}


def step_rate_limit(min_step_ms): return 1000./min_step_ms

def min_note_ms(profile, audio_frequency):
    floor=profile.get('minNoteFloorMs'); cycles=profile.get('minCycles')
    if floor is None or cycles is None or audio_frequency is None or audio_frequency<=0:return None
    return max(floor,1000.*cycles/audio_frequency)

def reversal_penalty_ms(profile, step_rate):
    interval=profile.get('reversalIntervalMs')
    return None if interval is None else max(0.,interval-1000./abs(step_rate))

def signed_transition_time(current,target,acceleration):
    return None if acceleration is None else abs(target-current)/acceleration

def braking_distance(speed, acceleration):
    return None if acceleration is None else speed*speed/(2*acceleration)

def harmonic_risk(profile,frequency,waveform='square'):
    bands=profile.get('candidateResonances') or []
    references=profile.get('referenceResonancesHz') or []
    harmonics=(1,3,5,7,9) if waveform=='square' else (1,)
    hits=[]
    for n in harmonics:
        hz=n*frequency
        if any(a<=hz<=b for a,b in bands) or any(abs(hz-r)<1e-6 for r in references): hits.append(1./n)
    return max(hits,default=0.)


def evaluate(profile: HardwareProfile, note: HardwareNote, state: HardwareDeviceState | None=None):
    state=dataclasses.replace(state) if state is not None else HardwareDeviceState()
    if profile.name=='DVD_SLED' and note.start>state.ready_at+1e-9:
        state.current_step_rate=0. # STOP in a free gap removes commanded velocity
    timing=Verdict.PASS;quality=Verdict.PASS;load=Verdict.PASS
    reasons=[];qr=[];score=1.;ready=max(note.start,state.ready_at)
    transition=0.;brake=None;step=None;risk=0.;rr=None;roundtrip=None;authorized=True
    if ready>note.start+1e-9:timing=Verdict.DEGRADED;reasons.append('DEVICE_BUSY')
    f=note.audio_frequency; name=profile.name
    readiness={}
    required={'FDD':('travelSteps','reversalIntervalMs'),
              'HDD_PERCUSSION':('parkMs','settleMs','strikeMs','burstWindowMs','maxContinuousHitsPerSec','maxBurstHitsPerSec','nominalStartToStartMs','baselineStrikeMs'),
              'HDD_TONAL':('transitionCycles','modalTransientMs')}.get(name,())
    unknown=[key for key in required if profile.get(key) is None]
    if name!='HDD_PERCUSSION' and f is None:
        return HardwareEvaluation(Verdict.BLOCKED,Verdict.UNKNOWN,Verdict.UNKNOWN,0.,
                                  ('AUDIO_FREQUENCY_REQUIRED',),(),ready,0.,None,None,None,authorized=False)
    if unknown:
        return HardwareEvaluation(Verdict.UNKNOWN,Verdict.UNKNOWN,Verdict.UNKNOWN,0.,
                                  tuple('PROFILE_PARAMETER_UNKNOWN:'+key for key in unknown),(),ready,0.,None,f,None,authorized=False)
    if name in ('FDD','DVD_SLED') and f:
        ratio=profile.get('pitchRatio')
        if ratio is None: timing=Verdict.UNKNOWN;reasons.append('PITCH_RATIO_UNKNOWN');authorized=False
        else:step=f/ratio
    if name=='DVD_SLED':
        travel=profile.get('travelSteps');accel=profile.get('accelerationLimit')
        if travel is None: timing=Verdict.UNKNOWN;reasons.append('TRAVEL_LIMIT_UNKNOWN');authorized=False
        if accel is None:timing=Verdict.UNKNOWN;reasons.append('ACCELERATION_UNKNOWN');authorized=False
        if step is not None and accel is not None:
            target=step*(note.direction or state.direction)
            transition=signed_transition_time(state.current_step_rate,target,accel)
            brake=braking_distance(state.current_step_rate,accel)
            if transition>0:qr.append('ACCELERATION_LIMIT');score-=min(.3,transition/max(note.duration,.001)*.15)
            if travel is not None and state.position is not None:
                remaining=travel-state.position if state.current_step_rate>=0 else state.position
                if remaining<=brake+1:qr.append('TRAVEL_REVERSAL');score-=.1
        # A hypothesis about mapping acoustics to steps remains explicitly uncertain.
        if profile.quantities['pitchRatio'].confidence in ('LOW','UNKNOWN'):qr.append('PITCH_RATIO_UNCERTAIN');score-=.1
    if name=='FDD' and step:
        minimum_us=profile.get('executionMinStepUs')
        if minimum_us is None and profile.get('datasheetMinStepMs') is not None:
            minimum_us=profile.get('datasheetMinStepMs')*1000
        if minimum_us is None:
            timing=Verdict.UNKNOWN;reasons.append('STEP_INTERVAL_UNKNOWN');authorized=False
        elif step>1000000./minimum_us+1e-6:
            timing=Verdict.BLOCKED;reasons.append('STEP_INTERVAL_LIMIT');authorized=False
        travel=profile.get('travelSteps')
        if travel is not None:
            rr=step/travel;roundtrip=step/(2*travel)
            penalty=reversal_penalty_ms(profile,step)
            if state.away_steps+step*note.duration>=travel:
                qr.append('TRAVEL_REVERSAL');score-=min(.2,(penalty or 0)*rr/1000.)
        if note.direction is not None and note.direction!=state.direction:
            transition=(reversal_penalty_ms(profile,step) or 0)/1000.
            qr.append('REVERSAL_CONFLICT');ready=max(ready,note.start+transition)
            if transition:timing=Verdict.DEGRADED
    if name=='HDD_PERCUSSION':
        # Existing drive timing is kept; a planning prior is not a coil rating.
        mechanical=(profile.get('parkMs')+profile.get('settleMs')+profile.get('strikeMs'))/1000.
        ready=max(ready,state.ready_at)
        window=profile.get('burstWindowMs')/1000.
        hits=[t for t in state.hit_times if note.start-window<t<=note.start]
        recent=[t for t in state.hit_times if note.start-1<t<=note.start]
        if len(hits)>=math.ceil(window*profile.get('maxBurstHitsPerSec')):
            ready=max(ready,hits[0]+window);reasons.append('BURST_WINDOW')
        if len(recent)>=profile.get('maxContinuousHitsPerSec'):
            ready=max(ready,recent[0]+1.);reasons.append('CONTINUOUS_HIT_RATE')
        if ready>note.start+1e-9:timing=Verdict.DEGRADED
        transition=mechanical
        reset=profile.get('parkMs')/1000.;settle=profile.get('settleMs')/1000.
        readiness={'mechanicalReadyAt':state.ready_at,'thermalBudgetReadyAt':state.thermal_ready_at,
                   'impactBudgetReadyAt':state.impact_ready_at, 'contactDetected':None,
                   'commandPhases':[{'state':'HIT','time':ready}, {'state':'RESET','time':ready},
                                    {'state':'SETTLE','time':ready+reset},
                                    {'state':'CONTACT/STRIKE','time':ready+reset+settle},
                                    {'state':'READY','time':ready+mechanical}]}
        # Safety budgets have no known time until calibration; mechanical readiness is separate.
        if state.thermal_ready_at is None or state.impact_ready_at is None:load=Verdict.UNKNOWN
        else:ready=max(ready,state.thermal_ready_at,state.impact_ready_at)
    if name=='HDD_TONAL' and f:
        transition=max(profile.get('transitionCycles')/f,profile.get('modalTransientMs')/1000.) if state.current_frequency!=f else 0.
        risk=harmonic_risk(profile,f,note.waveform)
        if risk:qr.append('HARMONIC_RESONANCE_CANDIDATE');score-=.3*risk
        avoid=profile.get('avoidBands')
        if avoid is None:qr.append('RESONANCE_BANDS_UNKNOWN')
        elif profile.quantities['avoidBands'].evidence_type!='MEASURED':
            qr.append('UNMEASURED_AVOID_BANDS')
        elif any(a<=f*n<=b for a,b in avoid for n in ((1,3,5,7,9) if note.waveform=='square' else (1,))):
            quality=Verdict.BLOCKED;reasons.append('MEASURED_AVOID_BAND');authorized=False
        # No automatic power/excursion settings or oscillator authorization from theoretical ranges.
        if profile.get('allowedExcursionRad') is None:
            reasons.append('PHYSICAL_UNKNOWN');authorized=False
        reasons.append('HDD_TONAL_EXECUTOR_UNAVAILABLE');authorized=False
    if f and name!='HDD_PERCUSSION':
        value=step if name=='DVD_SLED' else f
        suffix='StepRate' if name=='DVD_SLED' else 'Hz'
        musical=profile.get('musical'+suffix);stable=profile.get('stable'+suffix);preferred=profile.get('preferred'+suffix)
        if musical is None:quality=Verdict.UNKNOWN;qr.append('MUSICAL_RANGE_UNKNOWN')
        elif value is None:quality=Verdict.UNKNOWN;qr.append('PITCH_RATIO_UNKNOWN');authorized=False
        elif not musical[0]<=value<=musical[1]:quality=Verdict.BLOCKED;reasons.append('OUTSIDE_MUSICAL_RANGE');authorized=False
        if value is not None and preferred is not None and not preferred[0]<=value<=preferred[1]:qr.append('OUTSIDE_PREFERRED_RANGE');score-=.2
        if stable is None:qr.append('STABLE_RANGE_UNKNOWN');quality=Verdict.UNKNOWN if quality==Verdict.PASS else quality
        elif value is not None and not stable[0]<=value<=stable[1]:qr.append('OUTSIDE_STABLE_RANGE');score-=.2
        if preferred is None:
            qr.append('PREFERRED_RANGE_UNKNOWN')
            if quality==Verdict.PASS:quality=Verdict.UNKNOWN
        minimum=min_note_ms(profile,f)
        if minimum is None:
            qr.append('MIN_NOTE_UNKNOWN')
            if quality==Verdict.PASS:quality=Verdict.UNKNOWN
        if minimum is not None and note.duration*1000<minimum:qr.append('NOTE_TOO_SHORT');score-=.25
        pref=profile.get('preferredNoteMs')
        if pref is not None and note.duration*1000<pref:qr.append('SHORTER_THAN_PREFERRED');score-=.1*(1-note.duration*1000/pref)
        if transition and note.duration<transition:qr.append('TRANSITION_DOMINATES_NOTE');score-=.2
        rate=profile.get('maxNoteChangeRatePerSec')
        if rate and state.last_event_time is not None and note.start>state.last_event_time and 1/(note.start-state.last_event_time)>rate:
            qr.append('NOTE_CHANGE_RATE');score-=.1
        aggressive=note.aggressive or (name=='FDD' and f>400 and (stable is None or f>stable[1])) or (name=='DVD_SLED' and stable is not None and value is not None and value>stable[1])
    else:aggressive=note.aggressive
    if name=='HDD_PERCUSSION':
        # Raising the existing 4 ms bridge impulse is an aggressive change,
        # not authorized by a guessed planner pulse window.
        baseline=profile.get('baselineStrikeMs')
        aggressive=aggressive or profile.get('strikeMs')>baseline
    limits=[('safePeakCurrentA',note.peak_current_a),('safeImpactEnergyJ',note.impact_energy_j),
            ('allowedExcursionRad',note.excursion_rad)]
    if name=='HDD_PERCUSSION':limits.append(('safePulseMaxMs',note.pulse_ms if note.pulse_ms is not None else profile.get('strikeMs')))
    for key,value in limits:
        if key not in profile.quantities:continue
        bound=profile.get(key)
        if bound is None or value is None:load=Verdict.UNKNOWN if load!=Verdict.BLOCKED else load
        elif value>bound:load=Verdict.BLOCKED;reasons.append('PHYSICAL_LIMIT');authorized=False
    if load==Verdict.UNKNOWN:
        if 'PHYSICAL_UNKNOWN' not in reasons:reasons.append('PHYSICAL_UNKNOWN')
        if aggressive:authorized=False
    if ready>note.start+1e-9 and timing==Verdict.PASS:timing=Verdict.DEGRADED
    if qr and quality==Verdict.PASS:quality=Verdict.DEGRADED
    if not authorized and timing==Verdict.PASS and quality!=Verdict.BLOCKED:timing=Verdict.UNKNOWN
    return HardwareEvaluation(timing,quality,load,max(0.,score),tuple(dict.fromkeys(reasons)),tuple(dict.fromkeys(qr)),ready,transition,brake,f,step,risk,rr,roundtrip,authorized,readiness)


@dataclasses.dataclass
class HardwareContext:
    connected: bool
    registry: HardwareRegistry = dataclasses.field(default_factory=HardwareRegistry)
    inventory: dict[str,bool] | None = None
    protocol_version: int = 2

    def present(self,lane):
        if not self.connected or self.protocol_version!=2:return False
        lane=lane.lower()
        return (self.inventory if self.inventory is not None else
                {k:v.get('present',False) for k,v in self.registry.instances.items()}).get(lane,False)

    def profile_for(self,device,lane):
        name=getattr(device,'hardware_role','') or {'FDD':'FDD','DVD_SLED':'DVD_SLED','HDD_VCM':'HDD_PERCUSSION','VHS':'VHS'}.get(device.type)
        if not name:return None
        return self.registry.effective(name,lane,getattr(device,'hardware_overrides',{}))


def advance_sled(state,profile,target,seconds):
    """Deterministic command-space projection, not a measured physical trajectory."""
    travel=profile.get('travelSteps');a=profile.get('accelerationLimit')
    if travel is None or a is None:return
    if state.position is None:state.position=0.
    state.position_confidence='LOW';state.physical_state_confidence='LOW'
    # Host estimates need not duplicate the firmware's integer phase accumulator.
    count=max(1,math.ceil(seconds/.005));dt=seconds/count
    for _ in range(count):
        v=state.current_step_rate;remaining=travel-state.position if v>=0 else state.position
        direction=state.direction
        if remaining<=braking_distance(v,a)+1:direction=-1 if v>=0 else 1
        requested=abs(target)*direction;dv=max(-a*dt,min(a*dt,requested-v));new=v+dv
        state.position=max(0.,min(travel,state.position+(v+new)*.5*dt))
        if (v>=0 and new<0) or (v<0 and new>=0):state.travel_reversals+=1
        state.current_step_rate=new;state.direction=direction;state.target_step_rate=requested
    state.current_frequency=abs(state.current_step_rate)*profile.get('pitchRatio')


def advance_state(state,profile,note,evaluation):
    if profile.name=='DVD_SLED' and evaluation.step_rate:
        advance_sled(state,profile,evaluation.step_rate,note.duration)
    elif profile.name=='FDD' and evaluation.step_rate:
        travel=profile.get('travelSteps');steps=state.away_steps+evaluation.step_rate*note.duration
        if travel:
            count=int(steps/travel);state.travel_reversals+=count
            state.direction*=(-1 if count%2 else 1);state.away_steps=steps%travel
        state.current_frequency=note.audio_frequency
    elif profile.name=='HDD_PERCUSSION':
        state.hit_times.append(note.start);state.percussion_state='READY'
        state.ready_at=note.start+max(evaluation.transition_time,profile.get('nominalStartToStartMs')/1000.)
    else:state.current_frequency=note.audio_frequency
    state.target_frequency=note.audio_frequency;state.playing=False;state.last_event_time=note.start
    state.ready_at=max(state.ready_at,note.start+note.duration)


def execution_command(profile, lane):
    """Bounded execution settings; absent parameters cannot become zero/infinity."""
    prefix = lane.split(':')[0].upper() + ' ' + lane.split(':')[1]
    if profile.name=='DVD_SLED':
        acceleration=profile.get('accelerationLimit');ratio=profile.get('pitchRatio')
        if acceleration is None or ratio is None:return None
        travel=profile.get('travelSteps')
        return f"{prefix} PROFILE {travel if travel is not None else -1} {acceleration} {ratio}"
    if profile.name=='HDD_PERCUSSION':
        values=[profile.get(k) for k in ('parkMs','settleMs','strikeMs')]
        if any(v is None for v in values):return None
        return prefix+' PROFILE '+' '.join(str(v) for v in values)
    if profile.name=='FDD':
        travel=profile.get('travelSteps');reverse=profile.get('reversalIntervalMs')
        minimum=profile.get('executionMinStepUs')
        if minimum is None and profile.get('datasheetMinStepMs') is not None:minimum=profile.get('datasheetMinStepMs')*1000
        if travel is None or reverse is None or minimum is None:return None
        return f"{prefix} PROFILE {int(travel)} {int(reverse*1000)} {int(minimum)}"
    return None
