"""Calibrated finite test commands through the same Player/Router, never a transport."""
import math
import time
from playback.hardware_profiles import HardwareNote, HardwareDeviceState, evaluate
from .compiler import ExecutionCommand, ExecutionTimeline

class Laboratory:
    def __init__(self, registry, player):
        self.registry=registry; self.player=player; self.session=None; self.lease=0.; self.history={}
    def enter(self, session):
        self.player.select_owner('lab'); self.session=session; self.touch(session)
    def touch(self, session):
        if session==self.session: self.lease=time.monotonic()+3
    def leave(self, session):
        if session==self.session:
            self.player.select_owner('orchestra'); self.session=None
    def expire(self):
        if self.session and time.monotonic()>self.lease: self.leave(self.session)
    def test(self, session, ident, hz, duration):
        if session!=self.session or self.player.owner!='lab': raise ValueError('Wejdź do Laboratory')
        if any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) for x in (hz,duration)) or not .1<=duration<=10:
            raise ValueError('Czas testu: 0.1–10 s; częstotliwość musi być liczbą')
        d=self.registry.by_id[ident]; p=self.registry.profile(ident)
        if not d['enabled'] or p is None: raise ValueError('Urządzenie bez zatwierdzonego profilu')
        kind='hit' if d['type']=='HDD_VCM' else 'tone'
        now=time.monotonic()
        history=self.history.setdefault(ident,HardwareDeviceState())
        ev=evaluate(p,HardwareNote(None if kind=='hit' else hz,duration,now),history)
        if not ev.authorized or ev.ready_at>now: raise ValueError('Profil nie dopuszcza testu: '+', '.join(ev.reasons))
        if kind=='hit':
            duration=max(.1,ev.transition_time)
            history.hit_times.append(now)
            history.hit_times[:]=[t for t in history.hit_times if now-t<=(p.get('burstWindowMs') or 1000)/1000]
            history.ready_at=now+max(duration,(p.get('nominalStartToStartMs') or 0)/1000)
        commands=(ExecutionCommand(0,ident,kind,duration,hz),ExecutionCommand(duration,ident,'stop'))
        self.player.load(ExecutionTimeline(commands,duration),'lab'); self.player.play(); self.touch(session)
