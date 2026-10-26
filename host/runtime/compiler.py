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
    def as_dict(self): return asdict(self)

@dataclass(frozen=True)
class ExecutionTimeline:
    commands: tuple[ExecutionCommand, ...] = ()
    duration: float = 0.
    def as_dict(self): return {'duration':self.duration, 'commands':[c.as_dict() for c in self.commands]}

def compile_plan(plan):
    commands = []
    articulation = plan.execution_articulation
    from playback.planning_context import ensure_extra_bindings
    bindings = ensure_extra_bindings(plan)
    kinds = {d['id']:d['type'] for d in plan.devices}
    def add(ident, start, duration, hz, velocity, track, source, art=None):
        kind = 'hit' if kinds[ident]=='HDD_VCM' else 'tone'
        commands.append(ExecutionCommand(start,ident,kind,duration,hz or 0.,velocity,track,source,
                                         art))
        if kind=='tone': commands.append(ExecutionCommand(start+duration,ident,'stop'))
    for e in plan.events:
        if e.played:
            add(e.device_id,e.actual_start,e.actual_duration,e.played_hz,e.velocity,e.track,e.id,articulation.get(e.id))
    for i,e in enumerate(plan.reinforcements):
        art = bindings[i].articulation
        add(e.device_id,e.start,e.duration,e.hz,e.velocity,None,e.source_id,art)
    # Touching tones change pitch without an extra actuator STOP, as before.
    starts={(c.device_id,c.time) for c in commands if c.kind=='tone'}
    # Nanosecond tolerance for DVD and explicit FDD phrase legato: touching
    # gates can differ by an ULP. Real musical release gaps remain STOPs.
    from bisect import bisect_left
    dvd_starts = {}
    for c in commands:
        if c.kind == 'tone' and (kinds[c.device_id] == 'DVD_SLED' or
                                kinds[c.device_id] == 'FDD' and plan.internal_context.join_fdd_tones):
            dvd_starts.setdefault(c.device_id, []).append(c.time)
    for times in dvd_starts.values(): times.sort()
    def dvd_touch(c):
        times = dvd_starts.get(c.device_id, [])
        i = bisect_left(times, c.time - 1e-9)
        return i < len(times) and abs(times[i] - c.time) <= 1e-9
    commands=[c for c in commands if c.kind!='stop' or ((c.device_id,c.time) not in starts and not dvd_touch(c))]
    commands.sort(key=lambda c:(c.time, 0 if c.kind=='stop' else 1,c.device_id,c.source_id or ''))
    from playback.percussion_routing import peak_hits, MAX_HDD_HITS_PER_SECOND
    if peak_hits(c.time for c in commands if c.kind=='hit') > MAX_HDD_HITS_PER_SECOND:
        raise ValueError(f'HDD rate limit exceeded: at most {MAX_HDD_HITS_PER_SECOND} HIT commands in any one-second window')
    return ExecutionTimeline(tuple(commands), max(plan.duration,max((c.time+c.duration for c in commands),default=0.)))
