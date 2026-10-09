"""Exclusive outputs. BLE bytes/protocol stay in the existing transport."""
import threading
import time
import uuid
from playback.hardware_profiles import execution_command

class OutputError(RuntimeError): pass

class RealOutput:
    lookahead = 0.
    def __init__(self, registry):
        self.registry = registry
        self.link = None
        self.unknown = False
        self.active = False
        self.error = None
        self.configured = False
        self.last_ping = 0.
        self.sent = []

    def status(self):
        return {'connected':self.link is not None, 'unknown':self.unknown,
                'message':self.error or ('ESP32 BLE connected' if self.link else 'Brak połączenia z ESP32')}

    def write(self, lines):
        if not self.link: raise OutputError('Brak połączenia z ESP32')
        try:
            self.link.send_batch(lines)
            self.sent.extend(lines)
            self.sent[:] = self.sent[-200:]
        except Exception as exc:
            self.lost(str(exc)); raise OutputError(self.error) from exc

    def lost(self, reason):
        self.unknown = self.unknown or self.active
        self.error = ('Nieznany stan sprzętu. ' if self.unknown else '') + reason
        if self.link:
            if self.active:
                try: self.link.all_stop()
                except Exception: pass
            try: self.link.close()
            except Exception: pass
        self.link = None
        self.configured = False

    def attach(self, link):
        self.link = link
        self.configured = False
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
        self.active = self.unknown = False
        self.error = None

    def configure(self):
        if not self.link: raise OutputError('Brak połączenia z ESP32')
        if self.configured: return
        if self.link.controller_status.get('hardware_profiles') != '1':
            raise OutputError('Firmware nie obsługuje wymaganych profili sprzętowych')
        routing = self.registry.document.get('routing', {'mode':'AUTO'})
        strict = routing['mode']=='STRICT_TRACKS'
        lines = ['TRACKS OFF']
        for d in self.registry.devices:
            p = self.registry.profile(d['id'])
            prefix = self.prefix(d['id'])
            on = d['enabled'] and p is not None and (not strict or d['type']=='FDD')
            profile = execution_command(p,d['lane']) if p else None
            if on and d['type'] in ('FDD','DVD_SLED','HDD_VCM') and not profile: on=False
            if on and profile: lines.append(profile)
            lines.append(f'{prefix} ENABLE {int(on)}')
        if strict:
            if self.link.controller_status.get('strict_tracks')!='1': raise OutputError('Firmware bez STRICT TRACKS')
            lines.append('TRACKS SET '+' '.join(str(t if t is not None else -1) for t in routing['tracks']))
        self.write(lines)
        self.link.status()
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            response=self.link.poll_lines()
            if any(s.startswith('ERR') for s in response): raise OutputError('; '.join(response))
            if 'STATUS END' in response:
                self.configured=True
                return
            time.sleep(.005)
        raise OutputError('Brak potwierdzenia konfiguracji ESP32')

    def ready(self, commands=()):
        if not self.link: raise OutputError('Brak połączenia z ESP32')
        if self.unknown: raise OutputError('Nieznany stan sprzętu; wymagane potwierdzenie STOP')
        self.configure()
        for c in commands:
            if c.kind=='stop': continue
            d=self.registry.by_id[c.device_id]
            key='VHS' if d['type']=='VHS' else d['lane'].upper()
            status=self.link.device_status.get(key,{})
            if status.get('enabled')!='1': raise OutputError(d['name']+': firmware nie potwierdził ENABLE')
            if d['type']=='FDD' and (status.get('homed')!='1' or status.get('homing')=='1'):
                raise OutputError(d['name']+': wymagany homing TRACK0')

    def prefix(self, ident):
        lane=self.registry.by_id[ident]['lane']
        return 'VHS' if lane=='drum:1' else lane.upper().replace(':',' ')

    def dispatch(self, commands, **_):
        lines=[]
        for c in commands:
            prefix=self.prefix(c.device_id)
            d=self.registry.by_id[c.device_id]
            if c.kind=='stop': lines.append(prefix+' STOP')
            elif c.kind=='hit': lines.append(prefix+' HIT')
            elif c.kind=='pulse': lines.append(f'{prefix} PULSE {c.direction} {round(c.duration*1000)}')
            elif d['type']=='VHS': lines.extend(['VHS AMP 38',f'VHS FREQ {c.hz:.2f}'])
            else:
                text=f'{prefix} PLAY {c.hz:.2f}'
                if self.registry.document.get('routing',{}).get('mode')=='STRICT_TRACKS' and d['type']=='FDD':
                    if c.track is None: raise OutputError('STRICT TRACKS: brak pochodzenia nuty')
                    text+=f' TRACK {c.track}'
                lines.append(text)
        if any(c.kind!='stop' for c in commands): self.active=True
        self.write(lines)

    def stop_device(self, ident):
        if self.link: self.write([self.prefix(ident)+' STOP'])
        elif self.active or self.unknown: raise OutputError('Nieznany stan sprzętu; STOP urządzenia niepotwierdzony')

    def poll(self):
        if not self.link: return
        try:
            lines=self.link.poll_lines()
            if any(s.startswith(('ERR','READY protocol=')) for s in lines):
                raise OutputError('; '.join(lines))
            if time.monotonic()-self.last_ping>.3:
                self.link.ping(); self.last_ping=time.monotonic()
        except Exception as exc:
            self.lost(str(exc)); raise OutputError(self.error) from exc

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

    def ready(self, commands=()):
        if self.owner is None: raise OutputError('Brak przeglądarki z aktywnym Web Audio')

    def status(self): return {'connected':self.owner is not None,'message':'Web Audio · debug','unknown':False}

    def dispatch(self, commands, **clock):
        self.active=True
        self.epoch=clock['epoch']
        self.emit({'type':'audio','owner':self.owner,'commands':[c.as_dict() for c in commands],**clock})

    def acknowledge(self, owner, token):
        with self.lock:
            item=self.pending.get(token)
            if item and item[0]==owner: item[1].set()

    def cancel(self, device=None):
        if not self.active: return
        if self.owner is None: raise OutputError('Brak potwierdzenia wyciszenia Web Audio')
        token=uuid.uuid4().hex; done=threading.Event()
        with self.lock: self.pending[token]=(self.owner,done)
        self.emit({'type':'audio_cancel','owner':self.owner,'token':token,'deviceId':device,'epoch':self.epoch+1 if device is None else None})
        try:
            if not done.wait(1.5): raise OutputError('Przeglądarka nie potwierdziła wyciszenia Web Audio')
        finally:
            with self.lock: self.pending.pop(token,None)
        if device is None: self.active=False

    def stop(self): self.cancel()
    def stop_device(self, ident): self.cancel(ident)
