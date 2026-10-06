"""Build and flash the repository's Uno or ESP32 orchestra firmware."""
import shutil
import subprocess
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1] / 'firmware' / 'floppy'


def platformio() -> str:
    executable = shutil.which('pio')
    bundled = Path.home() / '.platformio' / 'penv' / 'bin' / 'pio'
    if executable:
        return executable
    if bundled.is_file():
        return str(bundled)
    raise RuntimeError('Brak PlatformIO. Zainstaluj PlatformIO, aby wgrywać firmware Uno.')


def run_firmware(tool: str, port: str | None = None, target: str = 'uno') -> str:
    if target not in ('uno', 'esp32'):
        raise ValueError('unknown firmware target')
    command = [tool, 'run', '-d', str(PROJECT), '-e', target]
    if port is not None:
        command += ['--target', 'upload', '--upload-port', port]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=180, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Przekroczono czas kompilacji/wgrywania firmware (180 s).') from exc
    except OSError as exc:
        raise RuntimeError(str(exc)) from exc
    log = result.stdout[-16000:]
    if result.returncode:
        raise RuntimeError(log or 'PlatformIO nie zakończyło operacji poprawnie.')
    return log


def wait_upload_port(port: str, timeout: float = 10.0) -> str:
    """Wait for USB re-enumeration; never select an unrelated serial device."""
    from floppy_link import scan_ports
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = scan_ports()
        if any(candidate.device == port for candidate in candidates):
            return port
        arduinos = [candidate for candidate in candidates if candidate.score >= 90]
        if len(arduinos) == 1:
            return arduinos[0].device
        time.sleep(.1)
    raise RuntimeError('Arduino nie pojawiło się po uploadzie. Sprawdź USB.')


def flash_engine(engine, tool: str, port: str, target: str = 'uno') -> dict:
    # Build failures leave the existing serial connection untouched.
    kwargs = {'target': target} if target != 'uno' else {}
    log = run_firmware(tool, **kwargs)
    engine.stop()
    engine.disconnect()
    try:
        log += '\n' + run_firmware(tool, port, **kwargs)
    finally:
        port = wait_upload_port(port)
        ready = engine.connect(port)
    return {'uploaded': True, 'ready': ready, 'port': port, 'log': log[-16000:]}
