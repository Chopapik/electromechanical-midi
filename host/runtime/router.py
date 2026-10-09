"""Exactly one output, device mute gates, no musical decisions."""
from .outputs import OutputError

class Router:
    def __init__(self, registry, real, virtual):
        self.registry=registry
        self.real=real
        self.virtual=virtual
        self.mode='REAL'
        self.muted=set()
    @property
    def output(self): return self.real if self.mode=='REAL' else self.virtual
    def switch(self, mode):
        if mode not in ('REAL','VIRTUAL'): raise ValueError('Unknown output')
        self.output.stop()  # Failure leaves selection unchanged.
        self.mode=mode
    def ready(self, commands):
        self.output.ready([c for c in commands if c.device_id not in self.muted])
    def stop(self): self.output.stop()
    def mute(self, ident, muted):
        if ident not in self.registry.by_id: raise ValueError('Unknown device')
        if not isinstance(muted,bool): raise ValueError('mute must be boolean')
        if muted:
            self.muted.add(ident)  # Fail closed even when physical STOP fails.
            self.output.stop_device(ident)
        else: self.muted.discard(ident)
    def dispatch(self, commands, **clock):
        accepted=[c for c in commands if c.kind=='stop' or
                  (c.device_id not in self.muted and self.registry.by_id[c.device_id]['enabled'])]
        if accepted: self.output.dispatch(accepted,**clock)
    def status(self): return {'mode':self.mode, **self.output.status(), 'muted':sorted(self.muted)}
