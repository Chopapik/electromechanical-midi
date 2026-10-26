"""Source-derived rhythmic priorities and stable VCM roles, with shared limits.

Only routes existing MIDI hits. No generated strikes or stronger coil settings.
"""
from bisect import bisect_left
from collections import defaultdict

MAX_HDD_HITS_PER_SECOND = 8
RATE_LIMIT_REASON = 'HDD_RATE_LIMIT'


def family(note, channel):
    if channel != 9:
        return 'tom'
    if note in (35,36): return 'kick'
    if note in (37,38,39,40): return 'snare'
    if note in (42,44,46): return 'hat'
    if note in (49,51,52,55,57,59): return 'cymbal'
    if note in (41,43,45,47,48,50): return 'tom'
    return 'aux'


def priority(item):
    span=item['span']
    return ({'kick':0,'snare':1,'tom':2,'cymbal':3,'hat':4,'aux':5}[family(span.note,span.channel)],
            -span.velocity,item['track'],item['order'])


def _select(rows):
    """Keep at most 8 hits in any half-open one-second window, across all HDD.

    Offline lookahead may evict a weaker earlier hit for a later kick/snare.
    No onset is moved. Active storage is bounded by the shared hit budget.
    """
    chosen, active = set(), []
    for token, time, rank in sorted(rows, key=lambda row:(row[1],row[2],row[0])):
        active = [row for row in active if time-row[1] < 1.]
        row = (token,time,rank)
        if len(active) == MAX_HDD_HITS_PER_SECOND:
            weakest = max(active,key=lambda row:(row[2],row[0]))
            if (rank,token) >= (weakest[2],weakest[0]):
                continue
            active.remove(weakest)
            chosen.remove(weakest[0])
        active.append(row)
        chosen.add(token)
    return chosen


def source_drops(notes, pins, hdd_ids):
    """Select source accents before low-value hits can consume physical lanes."""
    if not hdd_ids:
        return set()
    rows = []
    for item in notes:
        pin = pins.get(item['id'])
        if item['role'] != 'percussion' or pin is not None and pin.device_id not in hdd_ids:
            continue
        span = item['span']
        rank = (*priority(item)[:2],span.start,item['track'],item['order'],item['id'])
        rows.append((item['id'],span.start,rank))
    return {row[0] for row in rows} - _select(rows)


def peak_hits(times):
    """Actual command count in a moving one-second window; no integer bins."""
    from collections import deque
    active, peak = deque(), 0
    for time in sorted(times):
        while active and time-active[0] >= 1.:
            active.popleft()
        active.append(time)
        peak = max(peak,len(active))
    return peak


def limit_plan(plan):
    """Cover manual assignments, delayed hits and optional HDD reinforcement too.

    This final pass shares the source selector, preserves tonal events exactly,
    and records drops in the plan rather than silently filtering one output.
    """
    from dataclasses import replace
    hdd = {d['id'] for d in plan.devices if d['type']=='HDD_VCM'}
    sources = {e.id:e for e in plan.events}
    rows = []
    def rank(event, extra):
        item = {'span':event,'track':event.track,'order':event.id}
        return (extra,*priority(item),event.start,event.id)
    for e in plan.events:
        if e.played and e.device_id in hdd:
            rows.append(('event:'+e.id,e.actual_start,rank(e,0)))
    for i,e in enumerate(plan.reinforcements):
        if e.device_id in hdd:
            rows.append(('extra:'+str(i),e.start,rank(sources[e.source_id],1)))
    chosen = _select(rows)
    for i,e in enumerate(plan.events):
        if e.played and e.device_id in hdd and 'event:'+e.id not in chosen:
            plan.events[i] = replace(e,outcome='DROPPED',reason=RATE_LIMIT_REASON,
                                     actual_duration=0.,sustain_added=0.)
            plan.execution_articulation.pop(e.id,None)
    old_art = plan.execution_articulation
    primary_art = {key:value for key,value in old_art.items() if not key.startswith('extra:')}
    from .planning_context import replace_extras
    retained, removed = [], 0
    for i,e in enumerate(plan.reinforcements):
        if e.device_id in hdd and 'extra:'+str(i) not in chosen:
            removed += 1
            continue
        retained.append((i, e))
    replace_extras(plan, retained, primary=primary_art)
    previous = plan.articulation.get('hddRateLimit',{})
    plan.articulation['hddRateLimit'] = {
        'maxHitsPerSecond':MAX_HDD_HITS_PER_SECOND,'windowSeconds':1.,
        'sourceDrops':sum(e.reason==RATE_LIMIT_REASON for e in plan.events),
        'reinforcementDrops':previous.get('reinforcementDrops',0)+removed,
        'peakHitsPerSecond':peak_hits(time for token,time,_ in rows if token in chosen),
        'scope':'shared HDD command budget; excludes virtual articulation impulses',
    }


class Rhythm:
    def __init__(self, notes, devices, lanes):
        ordered=sorted(devices,key=lambda s:int(lanes[s.device.id].split(':')[-1]))
        self.two_drive = len(ordered)==2
        self.roles={s.device.id: ('kick','snare','hat','tom')[i%4] for i,s in enumerate(ordered)}
        self.attacks=defaultdict(list)
        for item in notes:
            if item['role']=='percussion':
                span=item['span'];self.attacks[family(span.note,span.channel)].append(span.start)
        for starts in self.attacks.values():starts.sort()

    def preserves_backbeat(self, item, ident, profile, state, note, evaluation):
        """With two voices, let fills borrow a lane only if its backbone still fits.

        Replay upcoming owner hits with and without this candidate through the
        existing mechanical evaluator. Protect only attacks feasible without it;
        an intrinsically unplayable roll must not reserve a whole lane forever.
        """
        owner=self.roles.get(ident)
        # Kick/snare may borrow either lane. Only optional fills yield to a
        # future owner: reserving a kick lane must never discard a live snare.
        if not self.two_drive or family(item['span'].note,item['span'].channel) in ('kick','snare'):
            return True
        from dataclasses import replace
        from .hardware_profiles import HardwareNote,evaluate,advance_state
        window=max(1.,profile.get('burstWindowMs')/1000.)
        starts=self.attacks[owner]
        i=bisect_left(starts,note.start-1e-9)
        if i==len(starts) or starts[i]>note.start+window:
            return True
        recent=[t for t in state.hit_times if t>note.start-window]
        baseline=replace(state,hit_times=list(recent))
        proposed=replace(state,hit_times=list(recent))
        advance_state(proposed,profile,note,evaluation)
        duration=sum(profile.get(k) for k in ('parkMs','settleMs','strikeMs'))/1000.
        for j in range(i,len(starts)):
            start=starts[j]
            if start>note.start+window:break
            future=HardwareNote(None,duration,start)
            before=evaluate(profile,future,baseline)
            if not before.authorized or before.ready_at>start+1e-9:continue
            after=evaluate(profile,future,proposed)
            if not after.authorized or after.ready_at>start+1e-9:return False
            advance_state(baseline,profile,future,before)
            advance_state(proposed,profile,future,after)
        return True

    def cost(self, item, ident, arrival, ready_after):
        kind=family(item['span'].note,item['span'].channel)
        owner=self.roles.get(ident)
        cost=0. if kind==owner else .2
        if kind=='cymbal' and owner=='tom':cost=.05
        if kind=='aux' and owner=='tom':cost=.1
        # Borrowing remains possible, but avoid consuming a lane just before
        # its kick/snare attack when another equally feasible lane exists.
        if owner in ('kick','snare') and kind!=owner:
            starts=self.attacks[owner];i=bisect_left(starts,arrival-1e-9)
            if i<len(starts) and starts[i]<ready_after-1e-9:cost+=1.
        return cost
