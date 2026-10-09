"""Exclusive controller maintenance. No invented reset or BLE flash command."""
import threading
import time
from ble_link import BleOrchestraLink
from firmware import platformio, run_firmware
from floppy_link import scan_ports
from .outputs import OutputError

class DeviceService:
    def __init__(self, player, connect=BleOrchestraLink):
        self.player=player; self.real=player.router.real
        self.connect_fn=connect; self.busy=False; self.lock=threading.Lock()
        self.error=None; self.connecting=False
        self.upload_port=None
        self.refresh()
    def refresh(self):
        self.upload_port=None
        try:
            ports=[p for p in scan_ports() if getattr(p,"vid",None)==0x10C4]
            if len(ports)==1:
                platformio(); self.upload_port=ports[0].device
        except Exception: pass
    def status(self):
        return {'busy':self.busy,'connecting':self.connecting,'error':self.error,
            'reset':{'available':False,'reason':'Firmware ESP32 nie udostępnia komendy resetu przez BLE.'},
            'home':{'available':self.real.link is not None,'reason':None if self.real.link else 'Brak połączenia z ESP32'},
            'firmware':{'available':self.upload_port is not None,'reason':'Upload wymaga ESP32 przez USB i PlatformIO; protokół BLE nie obsługuje OTA.'}}
    def connect(self):
        if not self.lock.acquire(blocking=False): return
        self.connecting=True; link=None
        try:
            if self.player.router.mode!='REAL' or self.real.link: return
            link=self.connect_fn()
            if not link.wait_boot(echo=lambda _:None): raise OutputError('Brak odpowiedzi ESP32 BLE')
            link.status(); deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                if 'STATUS END' in link.poll_lines(): break
                time.sleep(.005)
            else: raise OutputError('Brak STATUS ESP32')
            with self.player.lock:
                if self.player.router.mode!='REAL': link.close(); return
                self.real.attach(link); link=None
                self.error=None
        except Exception as exc:
            if link:
                try: link.close()
                except Exception: pass
            self.real.link=None; self.error=str(exc)
        finally:
            self.connecting=False; self.lock.release()
    def run(self, operation):
        if operation=='reset': raise OutputError(self.status()['reset']['reason'])
        if operation not in ('home','firmware'): raise ValueError('Unknown maintenance operation')
        if not self.lock.acquire(blocking=False): raise OutputError('DeviceService jest zajęty')
        self.busy=True
        try:
            with self.player.lock:
                self.player.select_owner('service')
            # Even in debug mode a maintenance action must establish REAL STOP.
            self.real.stop()
            if operation=='home':
                if not self.real.link: raise OutputError('Brak połączenia z ESP32')
                self.real.configure()
                self.real.active=True
                self.real.write(['FDD ALL HOME'])
                if not self.real.link.wait_homed(echo=lambda _:None):
                    raise OutputError('Homing TRACK0 nie został potwierdzony')
                self.real.stop()
                return {'ok':True}
            candidates=[p for p in scan_ports() if getattr(p,'vid',None)==0x10C4]
            if len(candidates)!=1: raise OutputError('Podłącz jedno ESP32 przez USB (CP2102), aby wgrać firmware')
            tool=platformio()
            log=run_firmware(tool,target='esp32')
            if self.real.link: self.real.link.close(); self.real.link=None
            self.real.configured=False
            log+='\n'+run_firmware(tool,candidates[0].device,target='esp32')
            return {'ok':True,'log':log[-16000:]}
        except Exception as exc:
            self.error=str(exc)
            try: self.real.stop()
            except Exception: pass
            raise
        finally:
            with self.player.lock: self.player.owner='orchestra'
            self.busy=False; self.lock.release()
