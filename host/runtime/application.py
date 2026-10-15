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
    def set_preset(self, preset):
        if preset not in ('balanced','fdd_quality','dvd_lead_low_fdd','fdd_quality_adaptive','instrument_roles','instrument_roles_unison','instrument_roles_duet','universal'): raise ValueError('Unknown arrangement preset')
        with self.player.lock:
            if self.service.busy: raise ValueError('DeviceService jest zajęty')
            self.player.stop()  # STOP confirmation/cancellation precedes any planning.
            parameters=self.registry.document.setdefault('parameters',{})
            old=parameters.get('arrangementPreset','balanced')
            parameters['arrangementPreset']=preset
            try:
                if self.source:
                    plan=arrange(self.source,self.registry);timeline=compile_plan(plan)
                    self.player.load(timeline)
                    self.plan=plan;self.timeline=timeline;self.lab.session=None
                self.revision+=1
            except Exception:
                parameters['arrangementPreset']=old
                raise
    def set_speaker_volume(self, ident, output, value):
        with self.player.lock:
            if self.service.busy: raise ValueError('DeviceService jest zajęty')
            self.registry.set_volume(ident,output,value)
            if output=='REAL' and self.router.mode=='REAL' and ident not in self.router.muted:
                self.real.set_speaker_amplitude(ident)

    def set_speaker_waveform(self,ident,waveform):
        with self.player.lock:
            if self.service.busy: raise ValueError('DeviceService jest zajęty')
            self.registry.validate_waveform(ident,waveform)
            if self.router.mode=='REAL' and ident in self.real.active_speakers:
                self.real.require_waveform(waveform)
            self.registry.set_waveform(ident,waveform)
            if self.router.mode=='REAL' and ident not in self.router.muted:
                self.real.set_speaker_waveform(ident)

    def orchestra(self):
        self.player.select_owner('orchestra'); self.lab.session=None
        if self.timeline: self.player.load(self.timeline)
    def snapshot(self):
        return {**self.player.snapshot(),'file':self.source.path.name if self.source else None,
                'revision':self.revision,'arrangementPreset':self.registry.document.get('parameters',{}).get('arrangementPreset','balanced'),'devices':self.registry.catalog(),'service':self.service.status(),
                'audioOwner':self.virtual.owner}
