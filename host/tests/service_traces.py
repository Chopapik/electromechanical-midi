"""Frozen service behavior probe: fake ports, link, keys and build only."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from runtime.application import Application
from test_runtime import Link


def capture_service_traces():
    rows = []
    ports = [SimpleNamespace(device='/dev/cu.usbserial-fake', vid=0x10c4)]
    for operation in ('firmware', 'firmware_ble'):
        for failure in (None, 'stop', 'off', 'build', 'upload', 'port'):
            if operation == 'firmware_ble' and failure == 'port':
                continue
            effects = []
            with patch('runtime.device_service.scan_ports', return_value=ports), \
                 patch('runtime.device_service.platformio', return_value='pio'):
                app = Application()
                service = app.service
                service.power_off_delay = 0
                service.restart_delay = 60
                link = Link()
                link.supports_ota = True
                app.real.attach(link)
                original_power = link.power

                def power(action):
                    effects.append('POWER '+action)
                    if failure == 'off':
                        raise RuntimeError('off failed')
                    return original_power(action)

                link.power = power
                if failure == 'stop':
                    link.fail_stop = True

                def build(_tool, port=None, *, on_line, **_):
                    stage = 'upload' if port else 'build'
                    effects.append(stage)
                    on_line('Writing at 0x00001000... (37 %)' if port else 'BUILD SUCCESSFUL')
                    if failure == stage:
                        raise RuntimeError(stage+' failed')

                def upload(_image, _key, on_progress):
                    effects.append('upload')
                    if failure == 'upload':
                        raise RuntimeError('upload failed')
                    on_progress(50)
                    on_progress(100)

                link.upload_firmware = upload
                original_close = link.close

                def close():
                    effects.append('close')
                    original_close()

                link.close = close
                with tempfile.TemporaryDirectory() as directory:
                    image = Path(directory)/'firmware.bin'
                    image.write_bytes(b'image')
                    with patch('runtime.device_service.run_firmware', side_effect=build), \
                         patch('runtime.device_service.read_key', return_value=b'k'*32), \
                         patch('runtime.device_service.image_path', return_value=image), \
                         patch('runtime.device_service.time.sleep', side_effect=lambda _: effects.append('wait')):
                        try:
                            if failure == 'port':
                                with patch('runtime.device_service.scan_ports', side_effect=[ports, []]):
                                    outcome = service.run(operation)
                            else:
                                outcome = service.run(operation)
                        except Exception as exc:
                            outcome = type(exc).__name__+': '+str(exc)
                        finally:
                            service.shutdown()
                rows.append({
                    'operation': operation, 'failure': failure, 'outcome': outcome,
                    'effects': effects, 'commands': link.sent, 'events': list(service.events),
                    'busy': service.busy, 'owner': app.player.owner, 'state': app.player.state,
                })
    return rows
