"""Exclusive maintenance, shared STOP/OFF barrier and generation-bound BLE recovery.

Short state sections use service.lock. Nested locks are always player -> service;
no ACK, scan, build, transfer or callback may wait while holding service.lock.
"""
import collections
from contextlib import contextmanager
import re
import threading
import time
from ble_link import BleOrchestraLink
from firmware import platformio, run_firmware, PROJECT
from firmware_ota import key_path, read_key, image_path
from floppy_link import esp32_upload_ports, scan_ports
from .outputs import OutputError
from .service_models import FirmwareSession, FirmwareStatus, ServiceOperation, ServiceTicket

_PROGRESS = re.compile(r'(?:\(|\b)(\d{1,3})\s*%\)')


class DeviceService:
    def __init__(self, player, connect=BleOrchestraLink):
        self.player = player
        self.real = player.router.real
        self.connect_fn = connect
        self.lock = threading.Lock()
        self.busy = False
        self.connecting = False
        self.operation = None
        self.error = None
        self.power_error = None
        self._connect_done = threading.Event()
        self._connect_done.set()
        self._closed = threading.Event()
        self._generation = 0
        self._recovery = None
        self.upload_port = None
        self.ports = []
        self.firmware_reason = None
        self.emit = lambda message: None
        self.events = collections.deque(maxlen=3000)
        self.sequence = 0
        self.firmware_state: FirmwareStatus = {
            'stage': 'idle', 'flash': 'idle', 'ble': 'idle', 'progress': None, 'error': None,
        }
        self.restart_delay = 3
        self.retry_delay = 3
        self.power_off_delay = 1.0
        self.refresh()

    def _append_event(self, fields):
        """Caller holds service.lock; callbacks always run after releasing it."""
        self.sequence += 1
        event = {'type': 'firmware_event', 'seq': self.sequence, **fields}
        self.events.append(event)
        return event

    def _event(self, **fields):
        with self.lock:
            event = self._append_event(fields)
        self.emit(event)

    def _state(self, *, generation=None, **fields):
        with self.lock:
            if generation is not None and not self._connection_current(generation):
                return False
            self.firmware_state = {**self.firmware_state, **fields}
            event = self._append_event({'kind': 'status', **self.firmware_state})
        self.emit(event)
        return True

    def refresh(self):
        try:
            ports = esp32_upload_ports(scan_ports())
            paths = [port.device for port in ports]
            if not paths:
                reason = 'Podłącz ESP32 przez USB (CP2102), aby wgrać firmware'
            elif len(paths) > 1:
                reason = 'Wykryto kilka portów CP2102; pozostaw podłączony jeden lub wybierz właściwy port'
            else:
                try:
                    platformio()
                    reason = None
                except Exception as exc:
                    reason = str(exc)
        except Exception as exc:
            paths = []
            reason = f'Wykrywanie USB: {exc}'
        with self.lock:
            self.ports = paths
            self.upload_port = paths[0] if len(paths) == 1 and reason is None else None
            self.firmware_reason = reason

    def status(self):
        with self.lock:
            power = self.real.power_state()
            occupied = self.busy or self.connecting
            power_available = self.real.link is not None and power != 'UNAVAILABLE' and not occupied
            if occupied:
                power_reason = 'DeviceService jest zajęty'
            elif not power_available:
                power_reason = 'Brak BLE lub firmware bez POWER'
            else:
                power_reason = None
            firmware_reason = self.firmware_reason or (power_reason if not power_available else None)
            ota_capable = bool(self.real.link and getattr(self.real.link, 'supports_ota', False))
            if not power_available:
                ble_reason = power_reason
            elif not ota_capable:
                ble_reason = 'Pierwsze wgranie obsługi BLE OTA wymaga USB'
            elif not key_path().is_file():
                ble_reason = 'Brak prywatnego klucza tej instalacji OTA; wymagane USB'
            else:
                ble_reason = None
            return {
                'power': {'state': power, 'available': power_available, 'operation': self.operation,
                          'error': self.power_error, 'reason': power_reason, 'measured': False},
                'busy': self.busy, 'connecting': self.connecting, 'error': self.error,
                'reset': {'available': False, 'reason': 'Firmware ESP32 nie udostępnia komendy resetu przez BLE.'},
                'home': {'available': self.real.link is not None and power == 'ON' and not self.busy,
                         'reason': None if power == 'ON' else 'ATX '+power},
                'firmware': {'available': self.upload_port is not None and power_available,
                             'reason': firmware_reason, 'bleAvailable': ble_reason is None,
                             'bleReason': ble_reason, 'port': self.upload_port,
                             'ports': self.ports.copy(), **self.firmware_state},
            }

    def _connection_current(self, generation):
        """Caller holds service.lock; connected/connecting are checked at entry."""
        return not self.busy and not self._closed.is_set() and generation == self._generation

    def _connection_allowed(self, generation):
        return (self._connection_current(generation)
                and self.player.router.mode == 'REAL' and self.real.link is None)

    def connect(self, expected_generation=None):
        with self.lock:
            generation = self._generation if expected_generation is None else expected_generation
            if self.connecting or not self._connection_allowed(generation):
                return False
            self.connecting = True
            self._connect_done.clear()
        link = None
        try:
            link = self.connect_fn()
            with self.lock:
                if not self._connection_current(generation):
                    return False
            self._verify_link(link, generation)
            # Do not hold service.lock while waiting for Player or live ACKs.
            with self.player.lock:
                with self.lock:
                    if not self._connection_allowed(generation):
                        return False
                    flashed = self.firmware_state['flash'] == 'success'
                    recovering = flashed and self.firmware_state['ble'] != 'verified'
                self._verify_recovery_power(link, flashed, recovering)
                with self.lock:
                    if not self._connection_allowed(generation):
                        return False
                self.real.attach(link)
                # attach itself confirms STOP. Shutdown can arrive during that ACK.
                with self.lock:
                    accepted = self._connection_current(generation)
                    if accepted:
                        self.error = None
                if not accepted:
                    self.real.detach(close=False)
                    return False
                link = None  # RealOutput now owns the session, including its close.
            if flashed:
                self._state(generation=generation, stage='ready', ble='verified', error=None)
            return True
        except Exception as exc:
            with self.lock:
                current = self._connection_current(generation)
                if current:
                    self.error = str(exc)
                flash = self.firmware_state['flash']
            if link is not None and self.real.link is link:
                with self.player.lock:
                    self.real.detach(close=False)
            if current and flash == 'success':
                self._state(generation=generation, stage='ble_retry', ble='retrying', error=str(exc))
            elif current and flash == 'failed':
                self._state(generation=generation, stage='failed', ble='retrying')
            return False
        finally:
            if link is not None:
                try:
                    link.close()
                except Exception:
                    pass
            with self.lock:
                self.connecting = False
                self._connect_done.set()

    def _verify_link(self, link, generation):
        if not link.wait_boot(echo=lambda _: None):
            raise OutputError('Brak odpowiedzi ESP32 BLE')
        before = getattr(link, 'status_generation', 0)
        link.status()
        deadline = time.monotonic()+4
        while time.monotonic() < deadline:
            with self.lock:
                if not self._connection_current(generation):
                    # The caller rechecks before attach; no stale state is published.
                    return
            lines = link.poll_lines()
            if any(line.startswith('ERR') for line in lines):
                raise OutputError('; '.join(lines))
            if getattr(link, 'status_generation', 0) > before:
                break
            time.sleep(.01)
        else:
            raise OutputError('Brak poprawnej odpowiedzi STATUS ESP32')
        required = {'board': 'esp32', 'protocol': '2', 'ready': '1',
                    'stop_ack': '1', 'hardware_profiles': '1'}
        status = link.controller_status
        if any(status.get(key) != value for key, value in required.items()):
            raise OutputError('BLE: niezgodny protokół lub brak wymaganych możliwości firmware')
        strict = self.real.registry.document.get('routing', {}).get('mode') == 'STRICT_TRACKS'
        if strict and status.get('strict_tracks') != '1':
            raise OutputError('BLE: firmware bez STRICT TRACKS')

    @staticmethod
    def _verify_recovery_power(link, flashed, recovering):
        status = link.controller_status
        if flashed and status.get('atx') not in ('ON', 'OFF'):
            raise OutputError('Firmware po uploadzie nie potwierdza obsługi POWER OFF')
        if status.get('atx') in ('ON', 'OFF'):
            link.power('STATUS')
            if recovering and link.power('OFF') != 'OFF':
                raise OutputError('Nie potwierdzono ATX OFF po flashowaniu')

    def _recover(self, generation):
        # Recovery reconnects only. It never repeats an unconfirmed transfer.
        if self._closed.wait(self.restart_delay):
            return
        while not self._closed.is_set():
            with self.lock:
                if self._closed.is_set() or generation != self._generation:
                    return
                occupied = self.busy
                linked = self.real.link is not None
                verified = self.firmware_state['ble'] == 'verified'
                flashed = self.firmware_state['flash'] == 'success'
                real_mode = self.player.router.mode == 'REAL'
            if occupied:
                # A non-firmware operation keeps this generation. Resume recovery
                # after it finishes instead of abandoning the pending reconnect.
                if self._closed.wait(self.retry_delay):
                    return
                continue
            if linked:
                if not verified:
                    self._state(generation=generation, stage='ready' if flashed else 'failed',
                                ble='verified', error=None)
                return
            if real_mode:
                self._state(generation=generation, stage='ble_connect' if flashed else 'failed',
                            ble='connecting')
                if self.connect(expected_generation=generation):
                    with self.lock:
                        failed = self.firmware_state['flash'] == 'failed'
                    if failed:
                        self._state(generation=generation, stage='failed', ble='verified')
                    return
            if self._closed.wait(self.retry_delay):
                return

    def shutdown(self):
        with self.lock:
            self._closed.set()

    def _power(self, action):
        if not self.real.link:
            raise OutputError('Brak BLE: nie można potwierdzić POWER '+action)
        try:
            result = self.real.power(action)
            with self.lock:
                self.power_error = None
            return result
        except Exception as exc:
            with self.lock:
                self.power_error = str(exc)
            raise OutputError(str(exc)) from exc

    @contextmanager
    def _exclusive_operation(self, operation):
        with self.lock:
            if self.busy or self.connecting:
                raise OutputError('DeviceService jest zajęty')
            if self._closed.is_set():
                raise OutputError('DeviceService jest zamknięty')
            self.busy = True
            self.operation = operation.value
            self.error = None
            self.power_error = None
            if operation.is_firmware:
                self._generation += 1
            ticket = ServiceTicket(operation, self._generation)
        try:
            yield ticket
        finally:
            if operation is not ServiceOperation.POWER_STATUS:
                with self.player.lock:
                    self.player.owner = 'orchestra'
            with self.lock:
                self.busy = False
                self.operation = None
                recover = (operation.is_firmware and self.real.link is None
                           and not self._closed.is_set())
                if recover:
                    self._recovery = threading.Thread(
                        target=self._recover, args=(ticket.generation,),
                        daemon=True, name='firmware-ble-recovery')
                    recovery = self._recovery
            if recover:
                recovery.start()

    def prepare_safe_upload(self, *, release=True):
        """Under service exclusivity and player.lock, after confirmed STOP."""
        self._state(stage='power_off')
        self._power('OFF')
        self._event(kind='log', line='Potwierdzono GPIO19 LOW; to nie jest pomiar napięcia ATX. Odczekiwanie 1 s.')
        time.sleep(self.power_off_delay)
        if release:
            self.real.detach()

    def _prepare_firmware(self, session):
        """One shared STOP/OFF barrier; USB releases BLE, OTA takes exclusive ownership."""
        if session.is_ble:
            if not self.real.link or not getattr(self.real.link, 'supports_ota', False):
                raise OutputError('Firmware bez BLE OTA; pierwszą instalację wykonaj przez USB')
            try:
                read_key()
            except OSError as exc:
                raise OutputError('Brak klucza tej instalacji BLE OTA; wymagane USB') from exc
        self.prepare_safe_upload(release=not session.is_ble)
        if session.is_ble:
            session.link = self.real.link
            self.real.detach(close=False)

    def _firmware_line(self, text):
        self._event(kind='log', line=text)
        with self.lock:
            uploading = self.firmware_state['stage'] == 'upload'
        if uploading:
            match = _PROGRESS.search(text)
            if match:
                self._state(progress=min(100, int(match.group(1))))

    def _flash(self, session):
        """Build and transfer after the barrier; no power or owner decisions here."""
        if session.is_ble:
            tool = None
            on_line = lambda text: self._event(kind='log', line=text)
        else:
            candidates = esp32_upload_ports(scan_ports())
            if len(candidates) != 1:
                raise OutputError('Podłącz dokładnie jeden port USB CP2102 przed uploadem')
            port = candidates[0].device
            tool = platformio()
            on_line = self._firmware_line
        self._state(stage='build')
        if session.is_ble:
            tool = platformio()
        run_firmware(tool, target='esp32', on_line=on_line)
        if session.is_ble:
            image = image_path(PROJECT).read_bytes()
            key = read_key()
            self._state(stage='upload_ble', progress=0)
            session.link.upload_firmware(image, key, on_progress=lambda value: self._state(progress=value))
            confirmation = 'ESP32 potwierdziło SHA-256 obrazu i wybór partycji OTA; oczekiwanie na restart.'
        else:
            fresh = esp32_upload_ports(scan_ports())
            if len(fresh) != 1 or fresh[0].device != port:
                raise OutputError('Port USB został odłączony lub zmieniony przed uploadem')
            self.real.detach()
            self._state(stage='upload')
            run_firmware(tool, port, target='esp32', on_line=on_line)
            confirmation = 'PlatformIO potwierdziło zakończenie flashowania'
        self._state(stage='flash_confirmed', flash='success', progress=100)
        self._event(kind='log', line=confirmation)
        self._state(stage='reboot_wait', ble='waiting', progress=None)
        result = {'ok': True, 'flash': 'success'}
        if session.is_ble:
            result['transport'] = 'BLE'
        return result

    def _run_operation(self, operation, session):
        if not self._connect_done.wait(25):
            raise OutputError('Trwa próba BLE; nie można bezpiecznie rozpocząć uploadu')
        with self.player.lock:
            if operation is ServiceOperation.POWER_STATUS:
                return {'ok': True, 'power': self._power('STATUS')}
            if operation is ServiceOperation.POWER_OFF:
                try:
                    self.player.select_owner('service')
                    self.real.stop()
                except OutputError:
                    # Emergency OFF has a separate contract. Firmware never takes this path.
                    self.player.invalidate()
                    self.player.owner = 'service'
                return {'ok': True, 'power': self._power('OFF')}
            self.player.select_owner('service')
            self.real.stop()
            if operation is ServiceOperation.POWER_ON:
                return {'ok': True, 'power': self._power('ON')}
            if operation.is_firmware:
                self._prepare_firmware(session)
        if operation is ServiceOperation.HOME:
            self.real.home_all()
            return {'ok': True}
        return self._flash(session)

    def run(self, operation, *, confirmed=False):
        if operation == 'reset':
            raise OutputError(self.status()['reset']['reason'])
        try:
            operation = ServiceOperation(operation)
        except ValueError:
            raise ValueError('Unknown maintenance operation') from None
        if operation is ServiceOperation.POWER_ON and confirmed is not True:
            raise OutputError('Włączenie fizycznego ATX wymaga potwierdzenia użytkownika')
        session = FirmwareSession(operation) if operation.is_firmware else None
        with self._exclusive_operation(operation):
            try:
                if operation.is_firmware:
                    self._state(stage='prepare', flash='running', ble='idle', progress=None,
                                error=None, transport=operation.transport)
                    self._event(kind='log', line='Przygotowanie: zatrzymanie odtwarzania i połączenia BLE')
                return self._run_operation(operation, session)
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                try:
                    if operation.is_firmware:
                        self._state(stage='failed', flash='failed', ble='idle', progress=None, error=str(exc))
                finally:
                    try:
                        self.real.stop()
                    except Exception:
                        pass
                raise
            finally:
                if session is not None:
                    session.close()
