"""Session-owned manual tests over the engine's existing controller transport.

All methods run under PlaybackEngine._lock. Only tick() owns the deadline;
no browser timer is entrusted with stopping physical outputs.
"""
import math
import time
from .hardware import bind_devices
from .hardware_profiles import HardwareNote, HardwareDeviceState, evaluate
from .virtual import effective_profile


class InstrumentLab:
    def __init__(self, engine):
        self.engine = engine
        self.owner = None
        self.lease = 0.
        self.deadline = 0.
        self.last_ping = 0.
        self.state = 'idle'
        self.device = None
        self.hz = None
        self.error = None
        self.duration = 0.
        self.confirmed = False
        self.started = 0.
        self.start_generation = 0
        self.needs_stop = False
        self.hit_states = {}
        self.tray_ready = {}

    @property
    def active(self):
        return self.state in ('starting', 'playing')

    def catalog(self):
        engine = self.engine
        context = engine._physical_context_locked()
        bound, _ = bind_devices(engine._orchestra.instances(), 2)
        result = []
        for family, count in (('fdd',4), ('sled',4), ('hdd',4), ('drum',1), ('tray',2)):
            for ident in range(1,count+1):
                lane = f'{family}:{ident}'
                device = bound.get(lane)
                profile = (effective_profile(device) if family=='tray' else context.profile_for(device,lane)) if context and device else None
                available = bool(device and device.enabled and device.mode in ('real','hybrid') and context and context.present(lane) and profile)
                ratio = (profile.get('pitchRatio') or 1) if profile else 1
                bands = profile.get('allowedBandsHz') if profile else None
                interval = profile.get('musicalStepRate' if family=='sled' else 'musicalHz') if profile else None
                allowed = [[lo*ratio,hi*ratio] for lo,hi in bands] if bands else ([[lo*ratio, hi*ratio] for lo,hi in [interval]] if interval and family=="sled" else [list(interval)] if interval else [])
                if bands and interval:
                    allowed=[[max(lo,interval[0])*ratio,min(hi,interval[1])*ratio] for lo,hi in bands if max(lo,interval[0])<=min(hi,interval[1])]
                pulse_max=min(60000,profile.get('strongMaxMs') or 0) if family=='tray' and profile else 0
                if family=='tray' and not pulse_max: available=False
                result.append({'pulseMaxMs':pulse_max, 'id':lane, 'name':f'{"DVD" if family=="sled" else "VHS" if family=="drum" else family.upper()} {ident}',
                               'available':available, 'bands':allowed, 'kind':family,
                               'reason':None if available else 'Brak aktywnego, fizycznego urządzenia z profilem',
                               'ampMin':0, 'ampMax':255})
        return result

    def enter(self, owner):
        if self.engine._state.value == 'playing':
            raise ValueError('Najpierw zatrzymaj MIDI')
        if self.owner is not None and self.owner != owner:
            raise ValueError('Instrument Lab jest używany przez inną sesję')
        self.owner = owner
        self.touch(owner)

    def touch(self, owner):
        if self.owner == owner:
            self.lease = time.monotonic()+6

    def leave(self, owner):
        if self.owner == owner:
            self.stop()
            self.owner = None

    @staticmethod
    def number(payload, key, default, low, high):
        value = payload.get(key, default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError(f'{key}: wymagany zakres {low}–{high}')
        return float(value)

    def start(self, owner, payload):
        e = self.engine
        if self.owner != owner:
            raise ValueError('Wejdź do Instrument Lab przed testem')
        if self.active or self.needs_stop or e._state.value=='playing':
            raise ValueError('MIDI lub inny test już trwa')
        if e._controller_target!='esp32' or not e._hardware.connected or e._transport is None or e._handshake:
            raise ValueError('ESP32 nie jest połączone i gotowe')
        lane = payload.get('device')
        item = next((d for d in self.catalog() if d['id']==lane),None)
        if not item or not item['available']:
            raise ValueError('Urządzenie niedostępne')
        duration = self.number(payload,'duration',3,.1,30)
        bound,_ = bind_devices(e._orchestra.instances(),2)
        profile = effective_profile(bound[lane]) if item['kind']=='tray' else e._physical_context_locked().profile_for(bound[lane],lane)
        family, ident = lane.split(':')
        prefix = 'VHS' if family=='drum' else f'{family.upper()} {ident}'
        hz = None
        commands = []
        status = getattr(e._transport,'device_status',{}).get('VHS' if family=='drum' else lane.upper(),{})
        if status.get('enabled')!='1':
            raise ValueError('Firmware nie potwierdził ENABLE urządzenia')
        if family in ('fdd','sled','drum'):
            hz = self.number(payload,'hz',392,.01,20000)
            evaluation = evaluate(profile,HardwareNote(hz,duration,0))
            if not evaluation.authorized:
                raise ValueError('Częstotliwość/profile niedopuszczone: '+', '.join(evaluation.reasons))
            if family=='fdd' and (status.get('homed')!='1' or status.get('homing')=='1'):
                raise ValueError('FDD wymaga HOME — użyj istniejącego Home w ustawieniach')
            if family=='drum':
                from .engine import DRUM_MIN_HZ, DRUM_MAX_HZ
                if not DRUM_MIN_HZ<=hz<=DRUM_MAX_HZ: raise ValueError(f'VHS: {DRUM_MIN_HZ}–{DRUM_MAX_HZ} Hz')
                amp=self.number(payload,'amp',64,0,255)
                if not amp.is_integer(): raise ValueError('AMP musi być liczbą całkowitą')
                commands=[f'VHS AMP {int(amp)}',f'VHS FREQ {hz:.6f}']
            else:
                commands=[f'{prefix} PLAY {hz:.6f}']
        elif family=='hdd':
            if status.get('busy')!='0': raise ValueError('HDD regeneruje się')
            now=time.monotonic()
            history=self.hit_states.setdefault(lane,HardwareDeviceState())
            evaluation=evaluate(profile,HardwareNote(None,duration,now),history)
            if evaluation.ready_at>now:raise ValueError('HDD: trwa regeneracja / limit gęstości uderzeń')
            if not evaluation.authorized: raise ValueError('Niepełny profil HDD')
            duration=max(.1,evaluation.transition_time)
            commands=[f'{prefix} HIT']
            history.hit_times.append(now)
            history.hit_times[:]=[t for t in history.hit_times if now-t<=profile.get('burstWindowMs')/1000.]
            history.ready_at=now+max(evaluation.transition_time,profile.get('nominalStartToStartMs')/1000.)
        else:
            # Tray is offered only with explicitly declared physical inventory/profile.
            direction=payload.get('direction','FWD')
            if direction not in ('FWD','REV'): raise ValueError('Nieprawidłowy kierunek')
            now=time.monotonic()
            if now<self.tray_ready.get(lane,0):raise ValueError('TRAY: trwa cooldown')
            ms=self.number(payload,'pulseMs',100,1,item['pulseMaxMs'])
            if not ms.is_integer():raise ValueError('PULSE wymaga całych ms')
            duration=ms/1000
            commands=[f'{prefix} PULSE {direction} {int(ms)}']
            self.tray_ready[lane]=now+duration+(profile.get('cooldownMs') or 0)/1000.
        self.start_generation = getattr(e._transport, 'status_generation', 0)
        self.device=lane
        self.hz=hz
        self.duration=duration
        self.state='starting'
        self.needs_stop=True
        self.error=None
        self.confirmed=False
        self.started=time.monotonic()
        # Finite HIT/PULSE deadlines live in firmware. Allow their STATUS barrier
        # to return over BLE; do not interrupt a strike during PARK/SETTLE.
        self.deadline=self.started+(max(3.,duration) if family in ('hdd','tray') else duration)
        self.last_ping=self.started
        self.touch(owner)
        try:
            e._transport.send_batch(commands+['STATUS'])
        except Exception as exc:
            self.stop(str(exc))
            e._fail_locked(str(exc))
            raise ValueError('Nie udało się wysłać testu') from exc
        e._wake.set()

    def on_lines(self, lines):
        if not self.active and not (self.state=='stopped' and time.monotonic()-self.started<5):return
        error=next((line for line in lines if line.startswith('ERR ')),None)
        if error and self.active:
            self.stop(error)
            return
        if 'READY protocol=2 board=esp32' in lines:
            self.stop('Kontroler uruchomił się ponownie')
            return
        if 'STATUS END' not in lines:return
        if getattr(self.engine._transport,'status_generation', self.start_generation+1)<=self.start_generation:return
        key='VHS' if self.device=='drum:1' else self.device.upper()
        status=getattr(self.engine._transport,'device_status',{}).get(key,{})
        family=self.device.split(':')[0]
        try:
            reported_hz=float(status.get('hz',0))
            reported_amp=int(status.get('amp',0))
        except (ValueError,TypeError):
            return  # Malformed protocol data is not a transport disconnect.
        if family=='drum':
            running=reported_hz>0 and reported_amp>0
        else:running=status.get('playing' if family in ('fdd','sled') else 'busy')=='1'
        if family in ('hdd','tray') and (running or time.monotonic()>=self.started+self.duration):
            # STATUS is parsed after the finite command on this same ordered
            # transport. An ERR would have aborted the test above. An already
            # finished pulse is success, not a failed sustained PLAY.
            self.confirmed=True
            if self.active:self.stop()
            return
        if running and (self.hz is None or abs(reported_hz-self.hz)<.02):
            self.confirmed=True
            if self.active: self.state='playing'


    def stop(self, error=None, force=False):
        was_active=self.active
        # Clear first: transport failure must not recursively re-enter STOP.
        self.state='error' if error else ('stopped' if self.device else 'idle')
        self.error=error
        if (was_active or self.needs_stop or force) and self.engine._transport is not None:
            # Exclusive lab ownership permits ALL STOP, which also purges BLE backlog.
            if not self.engine._safe_send_stop_locked():
                self.state='error';self.error='Brak potwierdzenia transportu STOP; sprawdź kontroler'
            else:
                self.needs_stop=False
                # all_stop_confirmed may consume the preceding STATUS transaction.
                self.on_lines(['STATUS END'])
                key='VHS' if self.device=='drum:1' else self.device.upper() if self.device else ''
                status=getattr(self.engine._transport,'device_status',{}).get(key,{})
                status.update(playing='0',busy='0',amp='0',hz='0')

    def tick(self):
        now=time.monotonic()
        if self.owner and now>=self.lease:
            self.leave(self.owner)
        if not self.active:return
        if not self.engine._hardware.connected:
            self.stop('Utrata połączenia z kontrolerem')
        elif now>=self.deadline:
            self.stop(None if self.confirmed else 'Test zatrzymany; firmware nie potwierdził startu')
        elif now-self.last_ping>=.5:
            self.last_ping=now
            self.engine._send_raw_locked('PING')

    def snapshot(self):
        return {'enabled':self.owner is not None,'state':self.state,'device':self.device,'hz':self.hz,
                'duration':self.duration,'remaining':max(0.,self.deadline-time.monotonic()) if self.active else 0,
                'error':self.error,'confirmed':self.confirmed,'catalog':self.catalog()}
