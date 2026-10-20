"""Serial v2 transport; Uno retains its original protocol and handshake."""
import time
from floppy_link import FloppyLink


class StopConfirmationError(Exception):
    """Live transport did not confirm that the controller executed STOP."""


def parse_status(lines):
    """Parse a complete, bounded multi-line status transaction atomically."""
    result = {'controller': {}, 'devices': {}}
    if not lines or lines[0] != 'STATUS BEGIN' or lines[-1] != 'STATUS END':
        raise ValueError('incomplete STATUS transaction')
    for line in lines[1:-1]:
        parts = line.split()
        if len(parts) < 3 or parts[0] != 'STATUS':
            raise ValueError('invalid STATUS record')
        kind = parts[1]
        start = 2 if kind in ('CTRL', 'VHS', 'VHS2') else 3
        if kind not in ('CTRL', 'VHS', 'VHS2', 'FDD', 'HDD', 'SLED'):
            raise ValueError('unknown device kind')
        if start == 3 and (len(parts) < 4 or not parts[2].isdigit()):
            raise ValueError('invalid device ID')
        key = kind if start == 2 else f'{kind}:{int(parts[2])}'
        values = dict(token.split('=', 1) for token in parts[start:] if '=' in token)
        if kind == 'CTRL': result['controller'] = values
        else: result['devices'][key] = values
    return result


def parse_fdd_diagnostics(lines):
    """Parse the opt-in FDD5-8 status transaction without weakening STATUS."""
    if (not lines or lines[0] != 'DIAG FDD BEGIN' or lines[-1] != 'DIAG FDD END'
            or len(lines) != 6):
        raise ValueError('incomplete DIAG FDD transaction')
    result = {}
    for line in lines[1:-1]:
        parts = line.split()
        if len(parts) < 5 or parts[:2] != ['DIAG', 'FDD'] or not parts[2].isdigit():
            raise ValueError('invalid DIAG FDD record')
        ordinal = int(parts[2])
        if ordinal not in range(5, 9) or f'FDD:{ordinal}' in result:
            raise ValueError('invalid extended FDD ID')
        result[f'FDD:{ordinal}'] = dict(
            token.split('=', 1) for token in parts[3:] if '=' in token)
    if set(result) != {f'FDD:{ordinal}' for ordinal in range(5, 9)}:
        raise ValueError('incomplete extended FDD inventory')
    return result


class OrchestraLink(FloppyLink):
    protocol_version = 1
    board = 'uno'

    def send_batch(self, commands):
        """Serial keeps its existing per-line writes and ordering."""
        for command in commands:
            self.send(command)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device_status = {}
        self.status_generation = 0
        self.status_observed_at = None
        self.controller_status = {}
        self._status_lines = None
        self.extended_status_generation = 0
        self._fdd_diagnostic_lines = None

    def poll_lines(self):
        lines = super().poll_lines()
        for line in lines:
            if line.startswith('READY protocol=2'):
                self.protocol_version = 2
                self.board = 'esp32'
            if line == 'STATUS BEGIN': self._status_lines = [line]
            elif self._status_lines is not None:
                self._status_lines.append(line)
                if len(self._status_lines) > 20:
                    self._status_lines = None
                elif line == 'STATUS END':
                    try:
                        status = parse_status(self._status_lines)
                    except ValueError:
                        status = None  # Malformed protocol data is not a Serial disconnect.
                    if status is not None:
                        self.status_generation = getattr(self, "status_generation", 0) + 1
                        self.status_observed_at = time.time()
                        extended = {key: value for key, value in self.device_status.items()
                                    if key.startswith('FDD:') and int(key.split(':')[1]) > 4}
                        self.device_status = {**status['devices'], **extended}
                        self.controller_status = status['controller']
                    self._status_lines = None
            if line == 'DIAG FDD BEGIN':
                self._fdd_diagnostic_lines = [line]
            elif getattr(self, '_fdd_diagnostic_lines', None) is not None:
                self._fdd_diagnostic_lines.append(line)
                if len(self._fdd_diagnostic_lines) > 6:
                    self._fdd_diagnostic_lines = None
                elif line == 'DIAG FDD END':
                    try:
                        devices = parse_fdd_diagnostics(self._fdd_diagnostic_lines)
                    except ValueError:
                        devices = None
                    if devices is not None:
                        self.device_status.update(devices)
                        self.extended_status_generation = getattr(
                            self, 'extended_status_generation', 0) + 1
                        self.status_observed_at = time.time()
                    self._fdd_diagnostic_lines = None
        return lines

    @staticmethod
    def _id(id, maximum):
        if not isinstance(id, int) or isinstance(id, bool) or not 1 <= id <= maximum:
            raise ValueError('invalid device ID')
        return id

    def _device(self, kind, id, action):
        maximum = {'FDD': 8, 'SLED': 6, 'HDD': 4}[kind]
        self.send(f'{kind} {self._id(id, maximum)} {action}')

    def fdd_play(self, id, hz): self._device('FDD', id, f'PLAY {hz:.2f}')
    def fdd_stop(self, id): self._device('FDD', id, 'STOP')
    def fdd_home(self, id): self._device('FDD', id, 'HOME')
    def fdd_status(self): self.send('DIAG FDD')
    def hdd_hit(self, id): self._device('HDD', id, 'HIT')
    def hdd_stop(self, id): self._device('HDD', id, 'STOP')
    def sled_play(self, id, hz): self._device('SLED', id, f'PLAY {hz:.2f}')
    def sled_stop(self, id): self._device('SLED', id, 'STOP')
    def vhs_amp(self, value): self.send(f'VHS AMP {value}')
    def vhs_freq(self, hz): self.send(f'VHS FREQ {hz:.2f}')
    def vhs_stop(self): self.send('VHS STOP')
    def all_stop(self):
        if self.protocol_version == 2:
            self.send('ALL STOP')
        else:
            for text in ('STOP', 'DRUM 0', 'HDD 0'):
                self.send(text)

    def all_stop_confirmed(self, timeout=2.0):
        token = str(time.monotonic_ns() & 0xffffffff)
        self.send('ALL STOP ' + token)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if 'STOPPED ' + token in self.poll_lines():
                return True
            time.sleep(.005)
        raise StopConfirmationError('STOP niepotwierdzony przez ESP32 — stan sprzętu jest nieznany')

    def power(self, action, timeout=2.0):
        """Confirm a GPIO command/query, never a measured ATX rail voltage."""
        if action not in ('ON', 'OFF', 'STATUS'): raise ValueError('Invalid POWER action')
        if self.controller_status.get('atx') not in ('ON','OFF','UNKNOWN'):
            raise RuntimeError('Firmware bez POWER; wymagane pierwsze wdrożenie z ręcznie wyłączonym ATX')
        token = str(time.monotonic_ns() & 0xffffffff)
        self.controller_status['atx'] = 'UNKNOWN'
        self.send(f'POWER {action} {token}')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for line in self.poll_lines():
                if line.startswith('ERR'): raise RuntimeError(line)
                for state, level in [('ON','1'),('OFF','0')]:
                    prefix = f'POWER STATUS {state}' if action=='STATUS' else f'POWER {state}'
                    if (action=='STATUS' or state==action) and line==f'{prefix} gpio19={level} token={token}':
                        self.controller_status['atx'] = state
                        return state
            time.sleep(.005)
        self.controller_status['atx'] = 'UNKNOWN'
        raise RuntimeError('Brak potwierdzenia POWER '+action+'; logiczny stan ATX nieznany')

    def wait_homed(self, timeout=10.0, echo=print):
        if self.protocol_version != 2:
            return super().wait_homed(timeout, echo)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            base_generation = self.status_generation
            extended_generation = getattr(self, 'extended_status_generation', 0)
            self.status()
            self.fdd_status()
            until = min(deadline, time.monotonic() + .1)
            while time.monotonic() < until:
                for line in self.poll_lines():
                    echo(line)
                    if line.startswith('ERR'): return False
                complete = (self.status_generation > base_generation and
                            getattr(self, 'extended_status_generation', 0) > extended_generation)
                if complete: break
                time.sleep(.005)
            fdds = [v for k,v in self.device_status.items() if k.startswith('FDD:') and v.get('enabled') == '1']
            if (complete and any(k.startswith('FDD:') for k in self.device_status)
                    and all(v.get('homed') == '1' and v.get('homing') == '0' for v in fdds)):
                return True
        return False
