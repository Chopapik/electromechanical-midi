"""Build and flash the repository's Uno or ESP32 orchestra firmware."""
import shutil
import subprocess
import threading
import collections
import os
import signal
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1] / 'firmware' / 'controller'


def platformio() -> str:
    executable = shutil.which('pio')
    bundled = Path.home() / '.platformio' / 'penv' / 'bin' / 'pio'
    if executable:
        return executable
    if bundled.is_file():
        return str(bundled)
    raise RuntimeError('Brak PlatformIO. Zainstaluj PlatformIO, aby wgrywać firmware.')


def run_firmware(tool: str, port: str | None = None, target: str = 'uno', on_line=None) -> str:
    if target not in ('uno', 'esp32'):
        raise ValueError('unknown firmware target')
    command = [tool, 'run', '-d', str(PROJECT), '-e', target]
    if port is not None:
        command += ['--target', 'upload', '--upload-port', port]
    if on_line is not None:
        tail = collections.deque(maxlen=1000)
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1, errors='replace', start_new_session=True)
        except OSError as exc:
            raise RuntimeError(str(exc)) from exc
        expired = threading.Event()
        def timeout():
            expired.set()
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        timer = threading.Timer(180, timeout)
        timer.start()
        try:
            # esptool uses carriage returns for progress; preserve each update.
            assert process.stdout is not None
            pending = ''
            while True:
                char = process.stdout.read(1)
                if not char:
                    if pending:
                        tail.append(pending); on_line(pending)
                    break
                if char in '\r\n':
                    if pending:
                        tail.append(pending); on_line(pending)
                        pending = ''
                else:
                    pending += char
                    if len(pending) >= 4096:
                        tail.append(pending); on_line(pending); pending = ''
            code = process.wait()
        finally:
            timer.cancel()
            process.stdout.close()
        log = '\n'.join(tail)[-16000:]
        if expired.is_set():
            raise RuntimeError('Przekroczono czas kompilacji/wgrywania firmware (180 s).')
        if code:
            raise RuntimeError(log or 'PlatformIO nie zakończyło operacji poprawnie.')
        return log
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
