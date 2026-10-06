"""Serial v2 transport; Uno retains its original protocol and handshake."""
import time
from floppy_link import FloppyLink


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
        start = 2 if kind in ('CTRL', 'VHS') else 3
        if kind not in ('CTRL', 'VHS', 'FDD', 'HDD', 'SLED', 'TRAY'):
            raise ValueError('unknown device kind')
        if start == 3 and (len(parts) < 4 or not parts[2].isdigit()):
            raise ValueError('invalid device ID')
        key = kind if start == 2 else f'{kind}:{int(parts[2])}'
        values = dict(token.split('=', 1) for token in parts[start:] if '=' in token)
        if kind == 'CTRL': result['controller'] = values
        else: result['devices'][key] = values
    return result


class OrchestraLink(FloppyLink):
    protocol_version = 1
    board = 'uno'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device_status = {}
        self.controller_status = {}
        self._status_lines = None

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
                        self.device_status = status['devices']
                        self.controller_status = status['controller']
                    self._status_lines = None
        return lines

    @staticmethod
    def _id(id, maximum=4):
        if not isinstance(id, int) or isinstance(id, bool) or not 1 <= id <= maximum:
            raise ValueError('invalid device ID')
        return id

    def _device(self, kind, id, action, maximum=4):
        self.send(f'{kind} {self._id(id, maximum)} {action}')

    def fdd_play(self, id, hz): self._device('FDD', id, f'PLAY {hz:.2f}')
    def fdd_stop(self, id): self._device('FDD', id, 'STOP')
    def fdd_home(self, id): self._device('FDD', id, 'HOME')
    def hdd_hit(self, id): self._device('HDD', id, 'HIT')
    def hdd_stop(self, id): self._device('HDD', id, 'STOP')
    def sled_play(self, id, hz): self._device('SLED', id, f'PLAY {hz:.2f}')
    def sled_stop(self, id): self._device('SLED', id, 'STOP')
    def tray_pulse(self, id, direction, ms):
        if direction not in ('FWD', 'REV') or not isinstance(ms, int) or not 1 <= ms <= 60000:
            raise ValueError('invalid tray pulse')
        self._device('TRAY', id, f'PULSE {direction} {ms}', 2)
    def tray_stop(self, id): self._device('TRAY', id, 'STOP', 2)
    def vhs_amp(self, value): self.send(f'VHS AMP {value}')
    def vhs_freq(self, hz): self.send(f'VHS FREQ {hz:.2f}')
    def vhs_stop(self): self.send('VHS STOP')
    def all_stop(self):
        if self.protocol_version == 2:
            self.send('ALL STOP')
        else:
            for text in ('STOP', 'DRUM 0', 'HDD 0'):
                self.send(text)

    def wait_homed(self, timeout=10.0, echo=print):
        if self.protocol_version != 2:
            return super().wait_homed(timeout, echo)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.status()
            complete = False
            until = min(deadline, time.monotonic() + .1)
            while time.monotonic() < until:
                for line in self.poll_lines():
                    echo(line)
                    if line.startswith('ERR'): return False
                    complete |= line == 'STATUS END'
                if complete: break
                time.sleep(.005)
            fdds = [v for k,v in self.device_status.items() if k.startswith('FDD:') and v.get('enabled') == '1']
            if complete and any(k.startswith('FDD:') for k in self.device_status) and all(v.get('homed') == '1' and v.get('homing') == '0' for v in fdds):
                return True
        return False
