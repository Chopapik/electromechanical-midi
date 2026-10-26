"""Application composition; musical planning stays pure and offline."""
import contextlib
import time
from midi_source import MidiSource
from arrangement_presets import is_preset
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

    def require_available(self):
        if self.service.busy: raise ValueError('DeviceService jest zajęty')

    def play(self, session):
        self.require_available()
        if self.router.mode=='VIRTUAL':
            self.virtual.claim_owner(session,exclusive=True)
        if self.player.owner!='orchestra' or self.player.timeline is not self.timeline:
            self.orchestra()
        self.player.play()

    def pause(self):
        self.require_available()
        self.player.pause()

    def stop(self):
        self.require_available()
        self.player.stop()

    def seek(self, position):
        self.require_available()
        self.player.seek(position)

    def switch_output(self, mode):
        with self.player.lock:
            self.require_available()
            self.player.switch(mode)

    def mute(self, ident, muted):
        self.require_available()
        self.player.mute(ident,muted)

    def audio_error(self, session, epoch, message='wyjście niedostępne'):
        self.require_available()
        if self.virtual.owner==session and self.router.mode=='VIRTUAL' and epoch==self.player.epoch:
            self.player.stop()
            self.player.error='Web Audio: '+str(message)[:250]

    def enter_laboratory(self, session):
        self.require_available()
        self.lab.enter(session)

    def leave_laboratory(self, session):
        self.require_available()
        self.lab.leave(session)
        self.orchestra()

    def test_laboratory(self, session, ident, hz=200, duration=1, modulation=None, *, update=False):
        self.require_available()
        self.lab.require_session(session)
        if self.router.mode=='VIRTUAL': self.virtual.claim_owner(session)
        self.lab.test(session,ident,hz,duration,modulation,update=update)

    def stop_laboratory(self, session, ident):
        self.require_available()
        self.lab.stop_device(session,ident)

    def run_service(self, operation, *, confirmed=False):
        self.require_available()
        return self.service.run(operation,confirmed=confirmed)

    def acknowledge_audio(self, session, token):
        # Must remain independent of Player's lock: STOP is waiting for this ACK.
        self.virtual.acknowledge(session,token)

    def heartbeat(self, session):
        self.lab.touch(session)

    def expire_laboratory(self):
        self.lab.expire()

    def refresh_connection(self, connect_on_start=True):
        self.service.refresh()
        if connect_on_start and self.router.mode=='REAL' and not self.real.link:
            self.service.connect()

    def start(self):
        self.player.start()

    def disconnect(self, session):
        if self.virtual.owner==session:
            # Preserve owner through STOP timeout, then allow the browser lease
            # to expire. No acknowledgement is inferred from a disconnected peer.
            with contextlib.suppress(Exception): self.player.stop()
            time.sleep(.6)
            self.virtual.release_owner(session)
        if self.lab.session==session:
            with contextlib.suppress(Exception): self.lab.leave(session)

    def close(self):
        with contextlib.suppress(Exception): self.player.close()
        self.service.shutdown()
        self.real.detach()

    def load(self, path):
        source=MidiSource(path)
        plan=arrange(source,self.registry)
        timeline=compile_plan(plan)
        with self.player.lock:
            self.player.load(timeline)
            self.lab.session=None
            self.source=source; self.plan=plan; self.timeline=timeline; self.revision+=1
    def set_preset(self, preset):
        if not is_preset(preset): raise ValueError('Unknown arrangement preset')
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
                'audioOwner':self.virtual.owner,'laboratory':self.lab.snapshot()}
