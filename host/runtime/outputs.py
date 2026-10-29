"""Exclusive outputs. BLE bytes/protocol stay in the existing transport."""
import threading
import time
import uuid
from playback.hardware_profiles import execution_command

class OutputError(RuntimeError):
    pass

class RealOutput:
    lookahead = 0.
    def __init__(self, registry):
        self.registry = registry
        self.link = None
        self.unknown = False
        self.active = False
        self.error = None
        self.configured = False
        self.active_speakers = set()
        self.speaker_frequencies = {}
        self.homing_devices = ()
        self.homing_deadline = 0.
        self.homing_status_pending = False
        self.homing_status_requirements = (False, False)
        self.last_ping = 0.
        self.power_seen = False
        self.sent = []

    def power_state(self):
        if self.link:
            state = self.link.controller_status.get('atx')
            if state in ('ON','OFF','UNKNOWN'):
                self.power_seen = True
                return state
            return 'UNAVAILABLE'
        return 'UNKNOWN' if self.power_seen else 'UNAVAILABLE'

    def require_power(self):
        state = self.power_state()
        if state != 'ON':
            raise OutputError('ATX '+state+': włącz zasilanie w Settings przed ruchem REAL')

    def invalidate_configuration(self):
        self.configured=False

    def detach(self, *, close=True):
        """Release a session without claiming STOP or clearing unknown motion."""
        if self.link and close:
            self.link.close()
        self.power_state()
        self.link=None
        self.invalidate_configuration()

    def power(self, action):
        """Apply only acknowledged logical GPIO power state, never rail voltage."""
        if not self.link:
            raise OutputError('Brak BLE: nie można potwierdzić POWER '+action)
        try:
            result=self.link.power(action)
            self.power_state()
            if action!='STATUS' and result!=action:
                raise OutputError('Niepoprawne potwierdzenie POWER '+action)
            if action=='OFF':
                self.active=False
                self.unknown=False
                self.error=None
                self.active_speakers.clear()
                self.speaker_frequencies.clear()
                self.link.invalidate_fdd_reference()
            return result
        except Exception as exc:
            self.link.invalidate_power_state()
            raise OutputError(str(exc)) from exc

    def home_all(self):
        if not self.link:
            raise OutputError('Brak połączenia z ESP32')
        self.require_power()
        self.configure()
        self.active=True
        self.write(['FDD ALL HOME'])
        if not self.link.wait_homed(echo=lambda _:None):
            raise OutputError('Homing TRACK0 nie został potwierdzony')
        self.stop()

    def status(self):
        return {'connected':self.link is not None, 'unknown':self.unknown,
                'message':self.error or ('ESP32 BLE connected' if self.link else 'Brak połączenia z ESP32')}

    def write(self, lines, *, configuration=False):
        if not self.link:
            raise OutputError('Brak połączenia z ESP32')
        try:
            send = getattr(self.link, 'send_configuration', self.link.send_batch) if configuration else self.link.send_batch
            send(lines)
            self.sent.extend(lines)
            self.sent[:] = self.sent[-200:]
        except Exception as exc:
            self.lost(str(exc))
            raise OutputError(self.error) from exc

    def lost(self, reason):
        self.unknown = self.unknown or self.active
        self.error = ('Nieznany stan sprzętu. ' if self.unknown else '') + reason
        if self.link:
            if self.active:
                try:
                    self.link.all_stop()
                except Exception:
                    pass
            try:
                self.link.close()
            except Exception:
                pass
        self.detach(close=False)
        self.homing_devices = ()
        self.homing_status_pending = False
        self.homing_status_requirements = (False, False)
        self.active_speakers.clear()
        self.speaker_frequencies.clear()

    def attach(self, link):
        self.link = link
        self.power_state()
        self.invalidate_configuration()
        # Establish a stopped baseline on reconnect; never resume playback.
        self.stop()
        self.error = None

    def stop(self):
        if not self.link:
            if self.unknown or self.active:
                raise OutputError('Nieznany stan sprzętu: brak potwierdzenia STOP z ESP32')
            return
        try:
            if self.link.controller_status.get('stop_ack') != '1':
                self.link.all_stop()  # Actual legacy safety STOP, but not confirmation.
                raise OutputError('Firmware nie potwierdza STOP; stan sprzętu jest nieznany')
            if self.link.all_stop_confirmed() is not True:
                raise OutputError('Brak potwierdzenia STOP')
        except Exception as exc:
            self.unknown = True
            self.error = 'Nieznany stan sprzętu: '+str(exc)
            raise OutputError(self.error) from exc
        self.homing_devices = ()
        self.homing_status_pending = False
        self.homing_status_requirements = (False, False)
        self.active_speakers.clear()
        self.speaker_frequencies.clear()
        self.active = self.unknown = False
        self.error = None

    def configure(self):
        if not self.link:
            raise OutputError('Brak połączenia z ESP32')
        if self.configured:
            return
        if self.link.controller_status.get('hardware_profiles') != '1':
            raise OutputError('Firmware nie obsługuje wymaganych profili sprzętowych')
        routing = self.registry.document.get('routing', {'mode':'AUTO'})
        strict = routing['mode']=='STRICT_TRACKS'
        lines = ['TRACKS OFF']
        for d in self.registry.devices:
            p = self.registry.profile(d['id'])
            prefix = self.prefix(d['id'])
            if d['lane'] == 'drum:2' and self.link.controller_status.get('speaker_fx') != '1':
                continue
            strict_fdd = d['type']=='FDD' and int(d['lane'].split(':')[1]) <= 4
            on = (d['enabled'] and d.get('realEnabled', d['enabled'])
                  and p is not None and (not strict or strict_fdd))
            profile = execution_command(p,d['lane']) if p else None
            if on and d['type'] in ('FDD','DVD_SLED','HDD_VCM') and not profile:
                on=False
            if on and p.get('continuousRotation') and self.link.controller_status.get('dvd_continuous')!='1':
                raise OutputError('Wgraj nowe firmware ESP32: wymagany ciągły ruch DVD Stepper')
            if on and d['type']=='VHS' and self.link.controller_status.get('speaker_waves')=='1':
                lines.append(f"{prefix} WAVE {d.get('waveform','pulse')}")
            if on and profile:
                lines.append(profile)
            lines.append(f'{prefix} ENABLE {int(on)}')
            if on and p.get('continuousRotation'):
                lines.append(f'{prefix} DIR FWD')
        if strict:
            if self.link.controller_status.get('strict_tracks')!='1':
                raise OutputError('Firmware bez STRICT TRACKS')
            lines.append('TRACKS SET '+' '.join(str(t if t is not None else -1) for t in routing['tracks']))
        self.write(lines, configuration=True)
        base_generation = self.link.status_generation
        extended_generation = getattr(self.link, 'extended_status_generation', 0)
        extended = any(d['enabled'] and d.get('realEnabled', d['enabled'])
                       and d['type']=='FDD'
                       and int(d['lane'].split(':')[1]) > 4 for d in self.registry.devices)
        self.link.status()
        if extended:
            self.link.fdd_status()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            response=self.link.poll_lines()
            if any(s.startswith('ERR') for s in response):
                raise OutputError('; '.join(response))
            if (self.link.status_generation > base_generation
                    and (not extended or getattr(self.link, 'extended_status_generation', 0) > extended_generation)):
                self.configured=True
                return
            time.sleep(.005)
        raise OutputError('Brak potwierdzenia konfiguracji ESP32')

    def ready(self, commands=(), *, auto_home=False, require_homed=True):
        if not self.link:
            raise OutputError('Brak połączenia z ESP32')
        if self.unknown:
            raise OutputError('Nieznany stan sprzętu; wymagane potwierdzenie STOP')
        blocked = sorted({self.registry.by_id[c.device_id]['name'] for c in commands
                          if c.kind!='stop' and not self.registry.by_id[c.device_id].get(
                              'realEnabled', self.registry.by_id[c.device_id]['enabled'])})
        if blocked:
            raise OutputError('Urządzenia dostępne tylko w VIRTUAL; przed REAL wymagają '
                              'kwalifikacji i realEnabled=true: '+', '.join(blocked))
        self.require_power()
        if any(self.registry.by_id[c.device_id]['lane']=='drum:2' and c.kind!='stop' for c in commands) and self.link.controller_status.get('speaker_fx')!='1':
            raise OutputError('Wgraj nowe firmware ESP32: wymagany PC Speaker FX na GPIO 26')
        for c in commands:
            if c.kind!='stop' and self.registry.by_id[c.device_id]['type']=='VHS':
                self.require_waveform(self.registry.by_id[c.device_id].get('waveform','pulse'))
        self.configure()
        missing_home=[]
        for c in commands:
            if c.kind=='stop':
                continue
            d=self.registry.by_id[c.device_id]
            key=('VHS2' if d['lane']=='drum:2' else 'VHS') if d['type']=='VHS' else d['lane'].upper()
            status=self.link.device_status.get(key,{})
            if status.get('enabled')!='1':
                raise OutputError(d['name']+': firmware nie potwierdził ENABLE')
            if require_homed and d['type']=='FDD' and (status.get('homed')!='1' or status.get('homing')=='1'):
                if not auto_home:
                    raise OutputError(d['name']+': wymagany homing TRACK0')
                if d['id'] not in missing_home:
                    missing_home.append(d['id'])
        if missing_home:
            self.stop() # Confirm a stopped baseline before mechanical preparation.
            self.homing_devices=tuple(missing_home)
            self.homing_deadline=time.monotonic()+10 # Existing homing wait limit.
            self.homing_status_pending=False
            self.homing_status_requirements=(False, False)
            self.homing_query_after=0.
            self.active=True
            self.write([self.prefix(ident)+' HOME' for ident in missing_home])
            return False
        return True

    def homing_ready(self):
        if not self.link or self.unknown:
            raise OutputError('Homing: utracono połączenie lub nieznany stan sprzętu')
        self.require_power()
        if not self.homing_devices:
            return True
        now=time.monotonic()
        if now>=self.homing_deadline:
            raise OutputError('Homing TRACK0 nie został potwierdzony: '+', '.join(self.registry.by_id[ident]['name'] for ident in self.homing_devices))
        generations=(self.link.status_generation,
                     getattr(self.link, 'extended_status_generation', 0))
        require_base,require_extended=self.homing_status_requirements
        complete=(not require_base or generations[0]>self.homing_status_generation[0]) and (
                  not require_extended or generations[1]>self.homing_status_generation[1])
        if self.homing_status_pending and complete:
            self.homing_status_pending=False
            states=[self.link.device_status.get(self.registry.by_id[ident]['lane'].upper(),{}) for ident in self.homing_devices]
            self.homing_devices=tuple(ident for ident,state in zip(self.homing_devices,states)
                if not (state.get('enabled')=='1' and state.get('homed')=='1' and state.get('homing')=='0'))
            if not self.homing_devices:
                return True
        # Never overlap fragmented BLE STATUS transactions. Player ticks keep
        # STOP responsive and retain watchdog PING while waiting for TRACK0.
        if not self.homing_status_pending and now>=self.homing_query_after:
            ordinals=[int(self.registry.by_id[ident]['lane'].split(':')[1])
                      for ident in self.homing_devices]
            require_base=any(ordinal<=4 for ordinal in ordinals)
            require_extended=any(ordinal>4 for ordinal in ordinals)
            self.homing_status_generation=generations
            self.homing_status_requirements=(require_base,require_extended)
            if require_base:
                self.link.status()
            if require_extended:
                self.link.fdd_status()
            self.homing_status_pending=True
            self.homing_query_after=now+.2
        return False

    def prefix(self, ident):
        lane=self.registry.by_id[ident]['lane']
        return 'VHS' if lane=='drum:1' else 'VHS2' if lane=='drum:2' else lane.upper().replace(':',' ')

    def dispatch(self, commands, **_):
        # An offline attempt cannot have started physical motion. Keep genuine
        # write failures conservative: a connected batch may be partially sent.
        if not self.link:
            raise OutputError('Brak połączenia z ESP32')
        blocked = sorted({self.registry.by_id[c.device_id]['name'] for c in commands
                          if c.kind!='stop' and not self.registry.by_id[c.device_id].get(
                              'realEnabled', self.registry.by_id[c.device_id]['enabled'])})
        if blocked:
            raise OutputError('Urządzenia dostępne tylko w VIRTUAL; REAL zablokowany: '
                              +', '.join(blocked))
        if any(c.kind!='stop' for c in commands):
            self.require_power()
        lines=[]
        for c in commands:
            prefix=self.prefix(c.device_id)
            d=self.registry.by_id[c.device_id]
            if c.kind=='stop':
                lines.append(prefix+' STOP')
            elif c.kind=='hit':
                lines.append(prefix+' HIT')
            elif d['type']=='VHS':
                if d.get('realAmplitude',50)==0:
                    lines.append(prefix+' STOP')
                    continue
                if self.link.controller_status.get('speaker_waves')=='1':
                    lines.append(f"{prefix} WAVE {d.get('waveform','pulse')}")
                lines.extend([f"{prefix} AMP {d.get('realAmplitude',50)}",f'{prefix} FREQ {c.hz:.2f}'])
            else:
                text=f'{prefix} PLAY {c.hz:.2f}'
                if self.registry.document.get('routing',{}).get('mode')=='STRICT_TRACKS' and d['type']=='FDD':
                    if c.track is None:
                        raise OutputError('STRICT TRACKS: brak pochodzenia nuty')
                    text+=f' TRACK {c.track}'
                lines.append(text)
        if any(c.kind!='stop' for c in commands):
            self.active=True
        self.write(lines)
        for c in commands:
            if self.registry.by_id[c.device_id]['type']=='VHS':
                if c.kind=='stop':
                    self.active_speakers.discard(c.device_id)
                    self.speaker_frequencies.pop(c.device_id,None)
                else:
                    self.active_speakers.add(c.device_id)
                    self.speaker_frequencies[c.device_id]=c.hz

    def require_waveform(self,waveform):
        if waveform!='pulse' and (not self.link or self.link.controller_status.get('speaker_waves')!='1'):
            raise OutputError('Wgraj nowe firmware ESP32: wymagany generator sinus/trójkąt/piła')

    def set_speaker_waveform(self,ident):
        waveform=self.registry.by_id[ident].get('waveform','pulse')
        if self.link and self.configured and self.link.controller_status.get('speaker_waves')=='1':
            self.write([f'{self.prefix(ident)} WAVE {waveform}'])

    def set_speaker_amplitude(self, ident):
        if not self.link:
            return
        prefix=self.prefix(ident)
        amplitude=self.registry.by_id[ident].get('realAmplitude',50)
        if amplitude==0:
            # A zero level is an explicit device STOP, including an idle/stale tone.
            self.write([prefix+' STOP'])
        elif ident in self.active_speakers:
            self.require_power()
            self.write([f'{prefix} AMP {amplitude}',f'{prefix} FREQ {self.speaker_frequencies[ident]:.2f}'])

    def stop_device(self, ident):
        if self.link:
            self.write([self.prefix(ident)+' STOP'])
            self.active_speakers.discard(ident)
            self.speaker_frequencies.pop(ident,None)
        elif self.active or self.unknown:
            raise OutputError('Nieznany stan sprzętu; STOP urządzenia niepotwierdzony')

    def poll(self):
        if not self.link:
            return
        try:
            lines=self.link.poll_lines()
            faults = [s for s in lines if s.startswith(('ERR','READY protocol='))]
            if faults:
                raise OutputError('; '.join(faults))
            if time.monotonic()-self.last_ping>.3:
                self.link.ping()
                self.last_ping=time.monotonic()
        except Exception as exc:
            self.lost(str(exc))
            raise OutputError(self.error) from exc

class VirtualOutput:
    """Browser scheduling packets; STOP acknowledgement is a cancellation barrier."""
    lookahead=.15
    def __init__(self, emit=lambda message:None):
        self.emit=emit
        self.owner=None
        self.epoch=0
        self.active=False
        self.pending={}
        self.lock=threading.Lock()

    def claim_owner(self, owner, *, exclusive=False):
        with self.lock:
            if exclusive and self.active and self.owner!=owner:
                raise ValueError('Web Audio jest używane przez inną przeglądarkę')
            self.owner=owner

    def release_owner(self, owner):
        """An expired browser lease cannot release a newer audio session."""
        with self.lock:
            if self.owner!=owner:
                return False
            self.active=False
            self.owner=None
            return True

    def ready(self, commands=()):
        if self.owner is None:
            raise OutputError('Brak przeglądarki z aktywnym Web Audio')

    def status(self):
        return {'connected':self.owner is not None,'message':'Web Audio · debug','unknown':False}

    def dispatch(self, commands, **clock):
        self.active=True
        self.epoch=clock['epoch']
        self.emit({'type':'audio','owner':self.owner,'commands':[c.as_dict() for c in commands],**clock})

    def acknowledge(self, owner, token):
        with self.lock:
            item=self.pending.get(token)
            if item and item[0]==owner:
                item[1].set()

    def cancel(self, device=None):
        if not self.active:
            return
        if self.owner is None:
            raise OutputError('Brak potwierdzenia wyciszenia Web Audio')
        token=uuid.uuid4().hex
        done=threading.Event()
        with self.lock:
            self.pending[token]=(self.owner,done)
        self.emit({'type':'audio_cancel','owner':self.owner,'token':token,'deviceId':device,'epoch':self.epoch+1 if device is None else None})
        try:
            if not done.wait(1.5):
                raise OutputError('Przeglądarka nie potwierdziła wyciszenia Web Audio')
        finally:
            with self.lock:
                self.pending.pop(token,None)
        if device is None:
            self.active=False

    def stop(self):
        self.cancel()
    def stop_device(self, ident):
        self.cancel(ident)
