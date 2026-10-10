"""Exclusive controller maintenance. No invented reset or BLE flash command."""
import threading
import time
from ble_link import BleOrchestraLink
from firmware import platformio, run_firmware
from floppy_link import esp32_upload_ports, scan_ports
from .outputs import OutputError

class DeviceService:
    def __init__(self, player, connect=BleOrchestraLink):
        self.player=player; self.real=player.router.real
        self.connect_fn=connect; self.busy=False; self.lock=threading.Lock()
        self.error=None; self.connecting=False
        self.upload_port=None
        self.firmware_reason='Upload wymaga ESP32 przez USB (CP2102); protokół BLE nie obsługuje OTA.'
        self.refresh()
    def refresh(self):
        self.upload_port=None
        self.firmware_reason='Upload wymaga ESP32 przez USB (CP2102); protokół BLE nie obsługuje OTA.'
        try:
            ports=esp32_upload_ports(scan_ports())
            if not ports:
                self.firmware_reason='Podłącz ESP32 przez USB (CP2102), aby wgrać firmware'
                return
            if len(ports)>1:
                self.firmware_reason='Podłącz dokładnie jedno ESP32 przez USB (CP2102)'
                return
            platformio(); self.upload_port=ports[0].device
            self.firmware_reason=None
        except Exception as exc:
            self.firmware_reason=str(exc)
    def status(self):
        return {'busy':self.busy,'connecting':self.connecting,'error':self.error,
            'reset':{'available':False,'reason':'Firmware ESP32 nie udostępnia komendy resetu przez BLE.'},
            'home':{'available':self.real.link is not None,'reason':None if self.real.link else 'Brak połączenia z ESP32'},
            'firmware':{'available':self.upload_port is not None,'reason':self.firmware_reason}}
    def connect(self):
        # Hold the maintenance lock only around flag/attach mutations. BLE scan
        # and gateway handshake can take many seconds and must not block USB flash.
        if not self.lock.acquire(blocking=False): return
        if self.busy or self.connecting or self.player.router.mode!='REAL' or self.real.link:
            self.lock.release(); return
        self.connecting=True
        self.lock.release()
        link=None
        try:
            if self.busy: return
            link=self.connect_fn()
            if self.busy:
                link.close(); link=None; return
            if not link.wait_boot(echo=lambda _:None): raise OutputError('Brak odpowiedzi ESP32 BLE')
            link.status(); deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                if self.busy:
                    link.close(); link=None; return
                if 'STATUS END' in link.poll_lines(): break
                time.sleep(.005)
            else: raise OutputError('Brak STATUS ESP32')
            if not self.lock.acquire(blocking=False):
                link.close(); link=None; return
            try:
                if self.busy or self.player.router.mode!='REAL' or self.real.link:
                    link.close(); link=None; return
                with self.player.lock:
                    if self.player.router.mode!='REAL':
                        link.close(); link=None; return
                    self.real.attach(link); link=None
                    self.error=None
            finally:
                self.lock.release()
        except Exception as exc:
            if link:
                try: link.close()
                except Exception: pass
            self.real.link=None; self.error=str(exc)
        finally:
            self.connecting=False
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
            candidates=esp32_upload_ports(scan_ports())
            if len(candidates)!=1: raise OutputError('Podłącz jedno ESP32 przez USB (CP2102), aby wgrać firmware')
            tool=platformio()
            log=run_firmware(tool,target='esp32')
            # Flash is USB-only; drop BLE before upload and re-handshake afterwards.
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
            if operation=='firmware' and self.real.link is None:
                self.connect()
