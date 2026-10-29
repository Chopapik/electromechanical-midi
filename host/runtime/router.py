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
    def ready(self, commands, *, auto_home=False):
        commands=self.accepted(commands)
        if self.mode=='REAL': return self.real.ready(commands,auto_home=auto_home)
        self.virtual.ready(commands)
        return True
    def stop(self): self.output.stop()
    def mute(self, ident, muted):
        if ident not in self.registry.by_id: raise ValueError('Unknown device')
        if not isinstance(muted,bool): raise ValueError('mute must be boolean')
        if muted:
            self.muted.add(ident)  # Fail closed even when physical STOP fails.
            self.output.stop_device(ident)
        else: self.muted.discard(ident)
    def mute_group(self, identifiers, muted):
        if not isinstance(identifiers,list) or not identifiers or any(
                not isinstance(ident,str) or ident not in self.registry.by_id for ident in identifiers):
            raise ValueError('Unknown device group')
        if not isinstance(muted,bool): raise ValueError('mute must be boolean')
        identifiers=list(dict.fromkeys(identifiers))
        if muted:
            # Close every gate before the first physical STOP. A partial failure
            # must never leave the rest of the requested group playing later.
            self.muted.update(identifiers)
            for ident in identifiers: self.output.stop_device(ident)
        else: self.muted.difference_update(identifiers)

    def dispatch(self, commands, **clock):
        accepted=self.accepted(commands)
        if accepted: self.output.dispatch(accepted,**clock)
    def accepted(self, commands):
        # Disabled catalog entries retain addressing and always retain STOP.
        return [c for c in commands if c.kind=='stop' or
                (c.device_id not in self.muted and self.registry.by_id[c.device_id]['enabled'])]
    def status(self): return {'mode':self.mode, **self.output.status(), 'muted':sorted(self.muted)}
