"""Single owner of playback state and monotonic song time.

REAL retains same-timestamp batching and drops superseded tones / one-shots
older than 100 ms. No catch-up burst or reconnect-resume. VIRTUAL receives
these same commands 150 ms ahead and maps Player time to AudioContext time.
"""
from dataclasses import replace
import bisect
import math
import threading
import time
from .compiler import ExecutionTimeline
from .outputs import OutputError

class Player:
    def __init__(self, router, clock=time.monotonic):
        self.router=router; self.clock=clock
        self.lock=threading.RLock()
        self.timeline=ExecutionTimeline(); self.lanes={}
        self.state='stopped'; self.owner='orchestra'
        self.base=0.; self.origin=0.; self.index=0; self.epoch=0
        self.error=None; self.dropped=0; self.max_lag=0.
        self.running=False
    def position(self):
        return max(0.,min(self.timeline.duration,self.clock()-self.origin if self.state=='playing' else self.base))
    def invalidate(self):
        self.base=self.position(); self.state='stopped'; self.epoch+=1
        self.index=len(self.timeline.commands)
    def stop(self, reset=True):
        with self.lock:
            self.invalidate()
            try: self.router.stop()
            except Exception as exc:
                self.error=str(exc); raise
            if reset: self.base=0.
            self.error=None
    def pause(self):
        with self.lock:
            self.stop(reset=False); self.state='paused'
    def select_owner(self, owner):
        with self.lock:
            if owner not in ('lab','orchestra','service'): raise ValueError('Unknown owner')
            self.stop(); self.owner=owner
    def load(self, timeline, owner='orchestra'):
        with self.lock:
            self.select_owner(owner); self.timeline=timeline; self.base=0.; self.index=0
            self.lanes={}
            for c in timeline.commands: self.lanes.setdefault(c.device_id,[]).append(c)
    def play(self):
        with self.lock:
            if self.owner=='service': raise OutputError('Sprzęt jest zajęty przez DeviceService')
            if self.state=='playing': return
            if not any(c.kind!='stop' for c in self.timeline.commands): raise OutputError('Brak nut do odtworzenia')
            self.router.ready(self.timeline.commands)
            if self.base>=self.timeline.duration: self.base=0.
            self.index=bisect.bisect_left([c.time for c in self.timeline.commands],self.base)
            self.epoch+=1; self.error=None
            # Browser receives a short preparation window, with no shift of MIDI timing.
            self.origin=self.clock()-self.base+(.12 if self.router.mode=='VIRTUAL' else 0.)
            self.state='playing'
            current={}
            for c in self.timeline.commands[:self.index]:
                if c.kind=='stop': current.pop(c.device_id,None)
                elif c.kind=='tone' and c.time+c.duration>self.base: current[c.device_id]=c
            resumed=[replace(c,time=self.base,duration=c.time+c.duration-self.base) for c in current.values()]
            if resumed:
                try: self.router.dispatch(resumed,epoch=self.epoch,origin=self.origin,serverTime=self.clock())
                except Exception as exc:
                    self.invalidate(); self.error=str(exc); raise
    def seek(self, position):
        if isinstance(position,bool) or not isinstance(position,(int,float)) or not math.isfinite(position): raise ValueError('Invalid position')
        with self.lock:
            self.stop(); self.base=max(0.,min(position,self.timeline.duration))
    def switch(self, mode):
        if mode not in ('REAL','VIRTUAL'): raise ValueError('Unknown output')
        with self.lock:
            self.invalidate()
            try: self.router.switch(mode)
            except Exception as exc:
                self.error=str(exc); raise
            self.base=0.; self.error=None
    def mute(self, ident, muted):
        with self.lock:
            try: self.router.mute(ident,muted)
            except Exception as exc:
                self.invalidate(); self.error=str(exc); raise
    def tick(self):
        with self.lock:
            try:
                if self.owner=='service': return
                if self.router.mode=='REAL': self.router.real.poll()
                if self.state!='playing': return
                position=self.position()
                horizon=position+self.router.output.lookahead
                commands=self.timeline.commands
                started=self.clock()
                while self.index<len(commands) and commands[self.index].time<=horizon:
                    stamp=commands[self.index].time; batch=[]
                    while self.index<len(commands) and commands[self.index].time==stamp:
                        c=commands[self.index]; self.index+=1
                        lag=position-c.time; self.max_lag=max(self.max_lag,lag)
                        # Preserve STOP even if stale or muted. Never replay expired notes.
                        stale=c.kind!='stop' and (c.time+c.duration<=position or
                              (c.kind in ('hit','pulse') and lag>.1))
                        if stale: self.dropped+=1
                        else: batch.append(c)
                    self.router.dispatch(batch,epoch=self.epoch,origin=self.origin,serverTime=self.clock())
                    position=self.position(); horizon=position+self.router.output.lookahead
                    if self.clock()-started>=.05: break
                if position>=self.timeline.duration:
                    self.stop(reset=False)
            except Exception as exc:
                self.invalidate(); self.state='paused'; self.error=str(exc)
                try: self.router.stop()
                except Exception: pass
    def snapshot(self):
        with self.lock:
            position=self.position(); activity={}
            if self.state=='playing':
                for ident,commands in self.lanes.items():
                    i=bisect.bisect_right([c.time for c in commands],position)-1
                    if i>=0:
                        c=commands[i]
                        if c.kind!='stop' and c.time+c.duration>position and ident not in self.router.muted:
                            activity[ident]=c.as_dict()
            return {'activity':activity,'state':self.state,'position':self.position(),'duration':self.timeline.duration,
                    'owner':self.owner,'epoch':self.epoch,'origin':self.origin,'serverTime':self.clock(),
                    'output':self.router.status(),'error':self.error,
                    'timing':{'droppedExpired':self.dropped,'maxLag':self.max_lag}}
    def start(self):
        self.running=True
        def work():
            while self.running:
                self.tick(); time.sleep(.01)
        self.thread=threading.Thread(target=work,daemon=True,name='player')
        self.thread.start()
    def close(self):
        self.running=False
        if hasattr(self,'thread'): self.thread.join(timeout=2)
        self.stop()
