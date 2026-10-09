"""Application composition; musical planning stays pure and offline."""
from midi_source import MidiSource
from .registry import DeviceRegistry
from .arranger import arrange
from .compiler import compile_plan
from .outputs import RealOutput, VirtualOutput
from .router import Router
from .player import Player
from .laboratory import Laboratory
from .device_service import DeviceService

class Application:
    def __init__(self, registry=None, emit=lambda message:None, connect=None):
        self.registry=registry or DeviceRegistry()
        self.real=RealOutput(self.registry); self.virtual=VirtualOutput(emit)
        self.router=Router(self.registry,self.real,self.virtual)
        self.player=Player(self.router)
        self.lab=Laboratory(self.registry,self.player)
        self.service=DeviceService(self.player,**({'connect':connect} if connect else {}))
        self.source=None; self.plan=None; self.timeline=None; self.revision=0
    def load(self, path):
        source=MidiSource(path)
        plan=arrange(source,self.registry)
        timeline=compile_plan(plan)
        with self.player.lock:
            self.player.load(timeline)
            self.lab.session=None
            self.source=source; self.plan=plan; self.timeline=timeline; self.revision+=1
    def orchestra(self):
        self.player.select_owner('orchestra'); self.lab.session=None
        if self.timeline: self.player.load(self.timeline)
    def snapshot(self):
        return {**self.player.snapshot(),'file':self.source.path.name if self.source else None,
                'revision':self.revision,'devices':self.registry.catalog(),'service':self.service.status(),
                'audioOwner':self.virtual.owner}
