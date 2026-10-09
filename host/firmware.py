"""Build and flash the repository's Uno or ESP32 orchestra firmware."""
import shutil
import subprocess
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1] / 'firmware' / 'controller'


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
