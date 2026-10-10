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
            return {'busy':self.busy,'connecting':self.connecting,'error':self.error,
                'reset':{'available':False,'reason':'Firmware ESP32 nie udostępnia komendy resetu przez BLE.'},
                'home':{'available':self.real.link is not None,'reason':None if self.real.link else 'Brak połączenia z ESP32'},
                'firmware':{'available':self.upload_port is not None and not self.busy,'reason':self.firmware_reason,
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

    def run(self, operation):
        if operation=='reset': raise OutputError(self.status()['reset']['reason'])
        if operation not in ('home','firmware'): raise ValueError('Unknown maintenance operation')
        with self.lock:
            if self.busy: raise OutputError('DeviceService jest zajęty')
            self.busy=True
            if operation=='firmware': self._generation+=1
            generation=self._generation
        if operation=='firmware':
            self._state(stage='prepare',flash='running',ble='idle',progress=None,error=None)
            self._event(kind='log',line='Przygotowanie: zatrzymanie odtwarzania i połączenia BLE')
        try:
            # Wait for a previously started BLE scan/handshake to release its link.
            if not self._connect_done.wait(25): raise OutputError('Trwa próba BLE; nie można bezpiecznie rozpocząć uploadu')
            with self.player.lock: self.player.select_owner('service')
            self.real.stop()
            if operation=='home':
                if not self.real.link: raise OutputError('Brak połączenia z ESP32')
                self.real.configure(); self.real.active=True; self.real.write(['FDD ALL HOME'])
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
            with self.player.lock: self.player.owner='orchestra'
            with self.lock: self.busy=False
            if operation=='firmware' and self.real.link is None and not self._closed.is_set():
                self._recovery=threading.Thread(target=self._recover,args=(generation,),daemon=True,name='firmware-ble-recovery')
                self._recovery.start()
