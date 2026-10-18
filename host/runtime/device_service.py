"""Exclusive USB firmware maintenance and verified BLE recovery."""
import collections
import re
import threading
import time
from ble_link import BleOrchestraLink
from firmware import platformio, run_firmware
from floppy_link import esp32_upload_ports, scan_ports
from .outputs import OutputError

_PROGRESS = re.compile(r'(?:\(|\b)(\d{1,3})\s*%\)')

class DeviceService:
    def __init__(self, player, connect=BleOrchestraLink):
        self.player=player; self.real=player.router.real
        self.connect_fn=connect; self.busy=False; self.lock=threading.Lock()
        self.error=None; self.connecting=False; self._connect_done=threading.Event(); self._connect_done.set()
        self.upload_port=None; self.ports=[]; self.firmware_reason=None
        self.emit=lambda message:None
        self.events=collections.deque(maxlen=3000); self.sequence=0
        self.firmware_state={'stage':'idle','flash':'idle','ble':'idle','progress':None,'error':None}
        self._recovery=None; self._closed=threading.Event(); self._generation=0
        self.restart_delay=3; self.retry_delay=3
        self.power_off_delay=1.0; self.operation=None; self.power_error=None
        self.refresh()

    def _event(self, **fields):
        with self.lock:
            self.sequence+=1
            event={'type':'firmware_event','seq':self.sequence,**fields}
            self.events.append(event)
        self.emit(event)

    def _state(self, **fields):
        with self.lock:
            self.firmware_state={**self.firmware_state,**fields}
            state=self.firmware_state.copy()
        self._event(kind='status',**state)

    def refresh(self):
        try:
            ports=esp32_upload_ports(scan_ports())
            paths=[p.device for p in ports]
            if not paths: reason='Podłącz ESP32 przez USB (CP2102), aby wgrać firmware'
            elif len(paths)>1: reason='Wykryto kilka portów CP2102; pozostaw podłączony jeden lub wybierz właściwy port'
            else:
                try: platformio(); reason=None
                except Exception as exc: reason=str(exc)
        except Exception as exc:
            paths=[]; reason=f'Wykrywanie USB: {exc}'
        with self.lock:
            self.ports=paths; self.upload_port=paths[0] if len(paths)==1 and reason is None else None
            self.firmware_reason=reason

    def status(self):
        with self.lock:
            power=self.real.power_state()
            power_available=self.real.link is not None and power!='UNAVAILABLE' and not self.busy and not self.connecting
            power_reason=('DeviceService jest zajęty' if self.busy or self.connecting else 'Brak BLE lub firmware bez POWER' if not power_available else None)
            firmware_reason=self.firmware_reason or (power_reason if not power_available else None)
            return {'power':{'state':power,'available':power_available,'operation':self.operation,'error':self.power_error,'reason':power_reason,'measured':False},'busy':self.busy,'connecting':self.connecting,'error':self.error,
                'reset':{'available':False,'reason':'Firmware ESP32 nie udostępnia komendy resetu przez BLE.'},
                'home':{'available':self.real.link is not None and power=='ON' and not self.busy,'reason':None if power=='ON' else 'ATX '+power},
                'firmware':{'available':self.upload_port is not None and power_available,'reason':firmware_reason,
                            'port':self.upload_port,'ports':self.ports.copy(),**self.firmware_state}}

    def connect(self, expected_generation=None):
        with self.lock:
            if self.busy or self.connecting or self.player.router.mode!='REAL' or self.real.link or self._closed.is_set() or (expected_generation is not None and expected_generation!=self._generation): return False
            self.connecting=True; self._connect_done.clear()
        link=None
        try:
            link=self.connect_fn()
            with self.lock:
                if self.busy or self._closed.is_set() or (expected_generation is not None and expected_generation!=self._generation): return False
            if not link.wait_boot(echo=lambda _:None): raise OutputError('Brak odpowiedzi ESP32 BLE')
            before=getattr(link,'status_generation',0)
            link.status(); deadline=time.monotonic()+4
            while time.monotonic()<deadline:
                with self.lock:
                    if self.busy or self._closed.is_set() or (expected_generation is not None and expected_generation!=self._generation): return False
                lines=link.poll_lines()
                if any(line.startswith('ERR') for line in lines): raise OutputError('; '.join(lines))
                if getattr(link,'status_generation',0)>before: break
                time.sleep(.01)
            else: raise OutputError('Brak poprawnej odpowiedzi STATUS ESP32')
            status=link.controller_status
            required={'board':'esp32','protocol':'2','ready':'1','stop_ack':'1','hardware_profiles':'1'}
            if any(status.get(key)!=value for key,value in required.items()):
                raise OutputError('BLE: niezgodny protokół lub brak wymaganych możliwości firmware')
            if self.real.registry.document.get('routing',{}).get('mode')=='STRICT_TRACKS' and status.get('strict_tracks')!='1':
                raise OutputError('BLE: firmware bez STRICT TRACKS')
            with self.lock:
                if self.busy or self._closed.is_set() or self.player.router.mode!='REAL' or self.real.link or (expected_generation is not None and expected_generation!=self._generation): return False
                with self.player.lock:
                    if self.firmware_state['flash']=='success' and status.get('atx') not in ('ON','OFF'):
                        raise OutputError('Firmware po uploadzie nie potwierdza obsługi POWER OFF')
                    if status.get('atx') in ('ON','OFF'):
                        link.power('STATUS')
                        if self.firmware_state['flash']=='success' and self.firmware_state['ble']!='verified':
                            if link.power('OFF')!='OFF': raise OutputError('Nie potwierdzono ATX OFF po flashowaniu')
                    self.real.attach(link); link=None
                    self.error=None
            if self.firmware_state['flash']=='success': self._state(stage='ready',ble='verified',error=None)
            return True
        except Exception as exc:
            with self.lock: self.error=str(exc)
            if link is not None and self.real.link is link:
                with self.player.lock:
                    self.real.link=None; self.real.configured=False
            if self.firmware_state['flash']=='success': self._state(stage='ble_retry',ble='retrying',error=str(exc))
            elif self.firmware_state['flash']=='failed': self._state(stage='failed',ble='retrying')
            return False
        finally:
            if link:
                try: link.close()
                except Exception: pass
            with self.lock:
                self.connecting=False; self._connect_done.set()

    def _recover(self, generation):
        # ESP32 reboot and BLE advertising take time after the UART uploader exits.
        if self._closed.wait(self.restart_delay): return
        while not self._closed.is_set():
            with self.lock:
                if generation!=self._generation: return
            if self.real.link:
                if self.firmware_state['ble']!='verified': self._state(stage='ready' if self.firmware_state['flash']=='success' else 'failed',ble='verified',error=None)
                return
            if self.player.router.mode=='REAL':
                self._state(stage='ble_connect' if self.firmware_state['flash']=='success' else 'failed',ble='connecting')
                if self.connect(expected_generation=generation):
                    if self.firmware_state['flash']=='failed': self._state(stage='failed',ble='verified')
                    return
            if self._closed.wait(self.retry_delay): return

    def shutdown(self):
        self._closed.set()

    def _power(self, action):
        if not self.real.link: raise OutputError('Brak BLE: nie można potwierdzić POWER '+action)
        try:
            result=self.real.link.power(action)
            self.real.power_state()
            if action!='STATUS' and result!=action: raise OutputError('Niepoprawne potwierdzenie POWER '+action)
            if action=='OFF':
                self.real.active=False; self.real.unknown=False; self.real.error=None
                self.real.active_speakers.clear()
                self.real.speaker_frequencies.clear()
                for key,state in getattr(self.real.link,'device_status',{}).items():
                    if key.startswith('FDD:'): state.update(homed='0',homing='0',playing='0')
            self.power_error=None
            return result
        except Exception as exc:
            if self.real.link.controller_status.get('atx') is not None:
                self.real.link.controller_status['atx']='UNKNOWN'
            self.power_error=str(exc)
            raise OutputError(str(exc)) from exc

    def prepare_safe_upload(self):
        """Only called under service exclusivity and player lock, after confirmed STOP."""
        self._state(stage='power_off')
        self._power('OFF')
        self._event(kind='log',line='Potwierdzono GPIO19 LOW; to nie jest pomiar napięcia ATX. Odczekiwanie 1 s.')
        time.sleep(self.power_off_delay)
        self.real.link.close(); self.real.link=None; self.real.configured=False

    def run(self, operation, *, confirmed=False):
        if operation=='reset': raise OutputError(self.status()['reset']['reason'])
        if operation not in ('home','firmware','power_on','power_off','power_status'): raise ValueError('Unknown maintenance operation')
        if operation=='power_on' and confirmed is not True: raise OutputError('Włączenie fizycznego ATX wymaga potwierdzenia użytkownika')
        with self.lock:
            if self.busy or self.connecting: raise OutputError('DeviceService jest zajęty')
            self.busy=True; self.operation=operation; self.error=None; self.power_error=None
            if operation=='firmware': self._generation+=1
            generation=self._generation
        if operation=='firmware':
            self._state(stage='prepare',flash='running',ble='idle',progress=None,error=None)
            self._event(kind='log',line='Przygotowanie: zatrzymanie odtwarzania i połączenia BLE')
        try:
            # Wait for a previously started BLE scan/handshake to release its link.
            if not self._connect_done.wait(25): raise OutputError('Trwa próba BLE; nie można bezpiecznie rozpocząć uploadu')
            with self.player.lock:
                if operation=='power_status': return {'ok':True,'power':self._power('STATUS')}
                if operation=='power_off':
                    try: self.player.select_owner('service'); self.real.stop()
                    except OutputError:
                        self.player.invalidate(); self.player.owner='service'
                    return {'ok':True,'power':self._power('OFF')}
                self.player.select_owner('service')
                self.real.stop()
                if operation.startswith('power_'):
                    return {'ok':True,'power':self._power('ON' if operation=='power_on' else 'OFF')}
                if operation=='firmware': self.prepare_safe_upload()
            if operation=='home':
                if not self.real.link: raise OutputError('Brak połączenia z ESP32')
                self.real.require_power(); self.real.configure(); self.real.active=True; self.real.write(['FDD ALL HOME'])
                if not self.real.link.wait_homed(echo=lambda _:None): raise OutputError('Homing TRACK0 nie został potwierdzony')
                self.real.stop(); return {'ok':True}
            candidates=esp32_upload_ports(scan_ports())
            if len(candidates)!=1: raise OutputError('Podłącz dokładnie jeden port USB CP2102 przed uploadem')
            port=candidates[0].device; tool=platformio()
            def line(text):
                self._event(kind='log',line=text)
                if self.firmware_state['stage']=='upload':
                    match=_PROGRESS.search(text)
                    if match: self._state(progress=min(100,int(match.group(1))))
            self._state(stage='build')
            run_firmware(tool,target='esp32',on_line=line)
            fresh=esp32_upload_ports(scan_ports())
            if len(fresh)!=1 or fresh[0].device!=port:
                raise OutputError('Port USB został odłączony lub zmieniony przed uploadem')
            if self.real.link:
                self.real.link.close(); self.real.link=None
            self.real.configured=False
            self._state(stage='upload',progress=None)
            run_firmware(tool,port,target='esp32',on_line=line)
            self._state(stage='flash_confirmed',flash='success',progress=100)
            self._event(kind='log',line='PlatformIO potwierdziło zakończenie flashowania')
            self._state(stage='reboot_wait',ble='waiting',progress=None)
            return {'ok':True,'flash':'success'}
        except Exception as exc:
            self.error=str(exc)
            if operation=='firmware': self._state(stage='failed',flash='failed',ble='idle',progress=None,error=str(exc))
            try: self.real.stop()
            except Exception: pass
            raise
        finally:
            if operation!='power_status':
                with self.player.lock: self.player.owner='orchestra'
            with self.lock: self.busy=False; self.operation=None
            if operation=='firmware' and self.real.link is None and not self._closed.is_set():
                self._recovery=threading.Thread(target=self._recover,args=(generation,),daemon=True,name='firmware-ble-recovery')
                self._recovery.start()
