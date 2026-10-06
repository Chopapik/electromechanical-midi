# ESP32 offline verification — 2026-10-06

**SOFTWARE VERIFIED**, no ESP32 connected and no physical ESP32 calibration performed.

| Check | Result |
| --- | --- |
| PlatformIO env:esp32, espressif32 6.9.0 / Arduino 2.0.17 | SUCCESS |
| PlatformIO env:uno, retained rollback | SUCCESS |
| Host unittest discovery | 483 passed |
| Included production C++ ESP32 core tests | 14 passed |
| Included v2 transport/integration tests | 11 passed |
| Frontend Vitest | 125 passed / 14 files |
| Frontend production build | SUCCESS; existing large-chunk warning |
| git diff --check | PASS |

ESP32 image: RAM 24,160 / 327,680 bytes, flash 293,045 / 1,310,720 bytes.
Uno image: RAM 344 / 2,048 bytes, flash 8,758 / 32,256 bytes.

Backend restarted; browser settings verified for firmware target selection and
ESP32 bring-up preset. Existing user configuration/MIDI restored, playback
left stopped. Uno USB port was absent at restart; no physical test is claimed.
The earlier Uno HDD 2 ms upload had already succeeded before ESP32 preparation.
No ESP32 upload, commit or push performed.

## Changed files

Firmware:
- `firmware/floppy/platformio.ini`
- `firmware/floppy/include/orchestra_core.h` (new production device core and central GPIO/Q map)
- `firmware/floppy/src/esp32/main.cpp` (new ESP32 SPI/LEDC/Serial adapter)
- `firmware/floppy/src/main.cpp` (previously requested Uno HDD 2 ms change only)

Host:
- `host/orchestra_link.py` (new)
- `host/firmware.py`
- `host/playback/engine.py`
- `host/playback/hardware.py`
- `host/playback/timeline.py`
- `host/playback/orchestra.py`
- `host/playback/virtual.py`
- `host/web/server.py`

UI:
- `web/src/components/FirmwarePanel.tsx`
- `web/src/components/VirtualOrchestra.tsx`

Tests:
- `host/tests/test_esp32_firmware.py` (new)
- `host/tests/test_orchestra_link.py` (new)
- `host/tests/test_tray.py`
- `host/tests/test_virtual.py` (previous HDD 2 ms expectation)
- `host/tests/test_web.py`
- `web/src/components/FirmwarePanel.test.tsx`

Documentation:
- `README.md`
- `docs/esp32-orchestra.md` (new full wiring and bring-up)
- `docs/esp32-verification.md` (this report)
