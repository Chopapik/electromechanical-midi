"""Pure PerformancePlan -> transport-independent, ordered execution events."""
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class ExecutionCommand:
    time: float
    device_id: str
    kind: str
    duration: float = 0.
    hz: float = 0.
    velocity: int = 100
    track: int | None = None
    source_id: str | None = None
    articulation: dict | None = None
    direction: str = 'FWD'
    def as_dict(self): return asdict(self)

@dataclass(frozen=True)
class ExecutionTimeline:
    commands: tuple[ExecutionCommand, ...] = ()
    duration: float = 0.
    def as_dict(self): return {'duration':self.duration, 'commands':[c.as_dict() for c in self.commands]}

def compile_plan(plan):
    commands = []
    articulation = plan.execution_articulation
    kinds = {d['id']:d['type'] for d in plan.devices}
    def add(ident, start, duration, hz, velocity, track, source, art=None, direction='FWD'):
        kind = 'hit' if kinds[ident]=='HDD_VCM' else 'pulse' if kinds[ident]=='DVD_TRAY' else 'tone'
        commands.append(ExecutionCommand(start,ident,kind,duration,hz or 0.,velocity,track,source,
                                         art,direction))
        if kind=='tone': commands.append(ExecutionCommand(start+duration,ident,'stop'))
    for e in plan.events:
        if e.played:
            add(e.device_id,e.actual_start,e.actual_duration,e.played_hz,e.velocity,e.track,e.id,articulation.get(e.id))
    for i,e in enumerate(plan.reinforcements):
        art = articulation.get("extra:"+str(i))
        add(e.device_id,e.start,e.duration,e.hz,e.velocity,None,e.source_id,art)
    for e in plan.tray_events:
        add(e.device_id,e.start,e.duration,0,e.velocity,e.track,e.source_id,direction='FWD' if e.direction>0 else 'REV')
    # Touching tones change pitch without an extra actuator STOP, as before.
    starts={(c.device_id,c.time) for c in commands if c.kind=='tone'}
    commands=[c for c in commands if c.kind!='stop' or (c.device_id,c.time) not in starts]
    commands.sort(key=lambda c:(c.time, 0 if c.kind=='stop' else 1,c.device_id,c.source_id or ''))
    return ExecutionTimeline(tuple(commands), max(plan.duration,max((c.time+c.duration for c in commands),default=0.)))
