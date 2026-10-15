# ESP32 orchestra bring-up

Target: ESP32-WROOM-32, 38-pin Micro-USB/CP2102. Firmware lives in
`firmware/controller/src/esp32/main.cpp`; device logic and the **single source of
truth for GPIO/Q mapping** live in `firmware/controller/include/orchestra_core.h`
(`orchestra::map`). Uno remains separately compiled from `src/main.cpp`.

Current application/UI entry points: [project README](../README.md),
[documentation index](README.md). Firmware symbols and profile JSON are the
source of truth; historical verification reports are explicitly scoped.

## Software and physical verification

**SOFTWARE VERIFIED** means compilation and native/host tests, not bench tests.
The offline tests run the production core with fake clock, sensor and latch
edges: safe boot, all 40 bits and byte order, four independent FDDs, simultaneous
STEP frames, minimum pulse spacing, DIR settle, STOP→PLAY, TRACK0 reversal,
initial HOME and timeout, watchdog/all-stop, HDD phases, sled phases/reverse,
tray timeout, disabled devices and ASCII command parsing. Serial status is
parsed only when a complete BEGIN/END transaction arrives.

**REQUIRES PHYSICAL CALIBRATION:** STEP/DIR input compatibility at 3.3 V for each
FDD; TRACK0 voltage and active-low behavior; DVD motor VM, current, temperature,
coil order, direction and travel; HDD VM and impulse durations; tray VM/pulse duration; printer motor parameters.
The software verification above does not establish physical calibration.
Software sled interval validation is an implementation guard, **not** a measured
safe motor Hz limit.

## Power supplies and evidence

| Load / circuit | Supply / connection | Evidence and limits |
| --- | --- | --- |
| FDD | Separate 5 V drive supply; STEP/DIR logic from the 3.3 V register chain | Current wiring choice; check the particular drive connector and logic compatibility. Not power from ESP32 GPIO. |
| DVD stepper via DRV8833 | Proposed **3.3 V at VM**, separate from logic power | Excessive motor heating was observed at 5 V in this setup. 3.3 V is provisional, requiring temperature and current measurements under the intended duty; not a verified safe limit. |
| HDD VCM | Historically tested at **5 V**, coil about **23.3 Ω** | Recorded in [the HDD hit sketch](../firmware/hdd_hit/hdd_hit.ino). A historical coil/bridge test, not a measured rating for all four VCMs or validation of the present DRV8833 drive. |
| 74HC595 and ESP32 signals | 3.3 V logic; common GND | Register VCC and input pull-ups are logic supplies, distinct from motor VM. ESP32 inputs must not be pulled to 5 V. |
| PC Speaker / PC Speaker FX | GPIO25/26 signal into separate S8050 speaker drivers | User reports passive speakers, probably 8 Ω; supply, base circuit, current and acoustic response remain uncharacterized. No direct low-impedance load on GPIO. |
| Tray motors | VM must be established for the actual motor/driver | Disabled and without an approved runtime hardware profile; no supply recommendation inferred from DVD or HDD. |

Common ground does not mean a single supply voltage for every load. No table
entry establishes a continuous-duty rating, current limit or thermal protection
for the motors. Keep the [theoretical reference data](research/orkiestra-model-teoretyczny.md)
separate from measurements of these instances.

## GPIO wiring

| ESP32 GPIO | Signal | Destination | Direction / notes |
| --- | --- | --- | --- |
| 34 | TRACK0 FDD1 | FDD 34-pin connector pin 26 | Input, active LOW, external pull-up to 3.3 V |
| 35 | TRACK0 FDD2 | FDD2 pin 26 | Input, external pull-up |
| 36 | TRACK0 FDD3 | FDD3 pin 26 | Input, external pull-up |
| 39 | TRACK0 FDD4 | FDD4 pin 26 | Input, external pull-up |
| 23 | SER/DATA | 595 #1 pin 14 | SPI MOSI |
| 18 | SRCLK/CLOCK | All five 595 pin 11 | SPI clock |
| 22 | RCLK/LATCH | All five 595 pin 12 | Frame latch |
| 21 | /OE | All five 595 pin 13 | Active LOW; **10 kΩ pull-up to 3.3 V** |
| 25 | PC Speaker (`VHS`) | Main S8050 driver signal input | LEDC channel 0; common GND |
| 26 | PC Speaker FX (`VHS2`) | Second S8050 driver signal input | LEDC channel 2, independent pitch timer; common GND |
| 27 | TEST LED | 330 Ω → external LED anode; cathode → GND | Output, LOW at startup; independent of 595 Q27 |

GPIO34/35/36/39 have no internal pull-ups. GPIO1/3 remain UART0/CP2102.
The firmware does not allocate strapping pins.

595 power: pin 16 = 3.3 V, pin 8 = GND, pin 10 `/SRCLR` held HIGH at 3.3 V.
Chain #1 pin 9 QH′ → #2 pin 14 SER, then #2→#3→#4→#5.
Parallel clock/latch/OE on all chips; decoupling at each chip.
Byte 4 is shifted first, byte 0 last: **chip #1 nearest ESP32 holds Q0–Q7**.
Local QA..QH correspond to DIP pins 15,1,2,3,4,5,6,7.

Bring-up SPI clock is explicitly **1 MHz**, MSB-first, mode 0:
`SPISettings(1000000, MSBFIRST, SPI_MODE0)` in `src/esp32/main.cpp`.
The 40 clock bits take 40 µs, plus software and latch overhead. This does not
depend on an SPI default. Raise the clock only after verifying the physical chain.

DRV8833 VM is a separate motor supply; logic/supply/FDD/ESP32 share GND.
For DVD, the provisional **3.3 V is at VM**, not just logic power; see the
[power/evidence table](#power-supplies-and-evidence) for the 5 V heating
observation and required temperature/current measurements. Calibrate HDD/tray
VM separately.
VCM coil goes between OUT1/OUT2 of its assigned bridge; never to a GPIO.
Sled coil A goes across AOUT1/AOUT2, coil B across BOUT1/BOUT2.
Tray motor goes across its assigned bridge's two outputs.
Q36 can drive all available nSLEEP inputs; keep asleep during bring-up.
Add appropriate input pull-downs where tri-state 595 outputs could otherwise
float during reset; FDD /STEP must remain inactive HIGH while /OE is HIGH.
Check the actual DRV8833 module's nSLEEP pull-up/availability before wiring.

FDD outputs connect STEP to connector pin 20, DIR to pin 18. DRIVE SELECT
is **not** on the ESP32 Q map: hold the correct `/DS` LOW separately for each
drive (typically connector pin 12 on a PC drive, verify drive/cable selection).
FDD power remains its own 5 V supply. Never pull an ESP32 input up to 5 V;
measure TRACK0 first and level-shift if needed. Connector GND pins and motor
supply GND join ESP32 GND.

## All 40 outputs

| Logical Q | Chip | Destination |
| --- | --- | --- |
| Q0 | 1 | FDD1 /STEP |
| Q1 | 1 | FDD1 DIR |
| Q2 | 1 | FDD2 /STEP |
| Q3 | 1 | FDD2 DIR |
| Q4 | 1 | FDD3 /STEP |
| Q5 | 1 | FDD3 DIR |
| Q6 | 1 | FDD4 /STEP |
| Q7 | 1 | FDD4 DIR |
| Q8 | 2 | DRV1 AIN1 — SLED1 |
| Q9 | 2 | DRV1 AIN2 |
| Q10 | 2 | DRV1 BIN1 |
| Q11 | 2 | DRV1 BIN2 |
| Q12 | 2 | DRV2 AIN1 — SLED2 |
| Q13 | 2 | DRV2 AIN2 |
| Q14 | 2 | DRV2 BIN1 |
| Q15 | 2 | DRV2 BIN2 |
| Q16 | 3 | DRV3 AIN1 — SLED3 |
| Q17 | 3 | DRV3 AIN2 |
| Q18 | 3 | DRV3 BIN1 |
| Q19 | 3 | DRV3 BIN2 |
| Q20 | 3 | DRV4 AIN1 — SLED4 |
| Q21 | 3 | DRV4 AIN2 |
| Q22 | 3 | DRV4 BIN1 |
| Q23 | 3 | DRV4 BIN2 |
| Q24 | 4 | DRV5 AIN1 — HDD1 |
| Q25 | 4 | DRV5 AIN2 |
| Q26 | 4 | DRV5 BIN1 — HDD2 |
| Q27 | 4 | DRV5 BIN2 |
| Q28 | 4 | DRV6 AIN1 — HDD3 |
| Q29 | 4 | DRV6 AIN2 |
| Q30 | 4 | DRV6 BIN1 — HDD4 |
| Q31 | 4 | DRV6 BIN2 |
| Q32 | 5 | DRV7 AIN1 — tray1 |
| Q33 | 5 | DRV7 AIN2 |
| Q34 | 5 | DRV7 BIN1 — tray2 |
| Q35 | 5 | DRV7 BIN2 |
| Q36 | 5 | Global DRV8833 nSLEEP, if exposed |
| Q37 | 5 | Spare |
| Q38 | 5 | Spare |
| Q39 | 5 | Spare |

DRV8 is spare. Both halves of DRV1–4 serve the bipolar sled motors.

## Startup and device behavior

Boot keeps /OE HIGH, initializes SPI, latches STEP=HIGH, DRV inputs=LOW,
nSLEEP=LOW, then enables /OE. **Boot never homes or starts motors.**
Only explicit commands or the host's configured homing start movement.
`ALL STOP` coasts all bridges, stops HOME and playback, sets all STEP HIGH,
stops both PC Speakers and deasserts nSLEEP. A 3-second host watchdog uses the same path.

FDD uses only TRACK0 and `awaySteps`. Away commands count up to 72, then
reverse; toward commands never count down and have no distance budget.
Physical TRACK0 resets awaySteps and reverses to AWAY. HOME alone has a
2-second emergency timeout. STEP low width is 30 µs; DIR changes settle for
5 ms (more than 30 µs minimum setup). The latch edge timestamp is recorded
after the physical pulse edge; subsequent pulses wait a full current period.
SPI work, status serialization and TX backpressure can make pulses late,
never compress them. No blocking Serial print is used in the pulse path.
All four FDD share the configured 2439 µs execution floor; the prior 410 Hz
upper endpoint does not individually qualify every drive. Arrangement folding
uses the active musical/preferred profile; see [current profile notes](hardware-first.md#fdd).
The common runtime attack interval is 120 ms, a separate musical control from STEP Hz.

ESP32 HDD defaults are **40 ms Park / 40 ms Settle / 4 ms Strike**, then
coast. The generated header and per-instance profile are the execution source;
this 84 ms cycle requires current, impact and thermal verification with DRV8833.
Uno's separate `WD_CAVIAR_CURRENT` path retains 40/40/2 ms. Busy hits return
`ERR BUSY`; there is no hidden hit queue. Runtime uses percussion, not HDD tones.

The current application enables four continuous-rotation DVD steppers and
leaves both trays disabled. Sled uses full-step, two-coil phases and the existing
acceleration ramp. `Sled::play()` can change target Hz without STOP. Firmware boot
and runtime inventory are distinct: host configuration sends profiles and ENABLE
before playback. Tray pulses are timed and STOP coasts immediately.

PC Speaker and PC Speaker FX use GPIO25/26, LEDC channels 0/2. Pulse mode uses
PWM at the note frequency, AMP 0–255 in the wire protocol (UI limits 0–128).
AMP 50 means 50/256 duty, not 50% loudness. FREQ=0 selects a 20 kHz carrier;
STOP sets duty 0. Sine/triangle/sawtooth use a 40 kHz PWM carrier with 20 kHz
sample updates, rather than an analog DAC output. Both channels share the same
STOP/watchdog path. [Waveform, gain, capability and wiring details](pc-speaker-fx.md).
No AVR register/ISR code is shared with this target.

## Serial v2 and host

115200, 8N1, ASCII, newline. Boot: `READY protocol=2 board=esp32` confirms
controller startup, **not FDD homing**. `STATUS` emits BEGIN, CTRL, individual
FDD/HDD/SLED/TRAY/VHS/VHS2 records, END. `track0=1` means normalized ACTIVE;
`raw=0` is the corresponding active-low GPIO read. Homing and playing are
separate from USB connected status.

Commands:

```text
PING
STATUS
ALL STOP
FDD 1 HOME
FDD ALL HOME
FDD 1 PLAY 220.00
FDD 1 STOP
HDD 1 HIT
HDD 1 STOP
SLED 1 PLAY 220.00
SLED 1 DIR FWD
SLED 1 DIR REV
SLED 1 STOP
TRAY 1 PULSE FWD 80
TRAY 1 PULSE REV 80
TRAY 1 STOP
VHS AMP 50
VHS FREQ 164.81
VHS STOP
VHS2 AMP 50
VHS2 WAVE pulse
VHS2 FREQ 830.61
VHS2 STOP
```

Each device also accepts `ENABLE 0|1`, e.g. `SLED 1 ENABLE 1` or
`VHS ENABLE 0`. FDD/HDD IDs are 1–4, SLED 1–4, tray 1–2.
Legacy PLAY/STOP/HOME address FDD1; HIT addresses HDD1;
DRUM/DRUMF alias VHS AMP/FREQ. Legacy HDD 0 invokes all-stop.

`host/orchestra_link.py` retains the shared protocol parser and atomic STATUS
transactions. Current playback uses `host/runtime/outputs.py` and stable lanes
from `config/devices.json`: `fdd:1`…`fdd:4`, `sled:1`…`sled:4`, `hdd:1`…`hdd:4`,
`drum:1`/`drum:2` and `tray:1`/`tray:2`. Disabled entries keep their ordinals;
removing or reordering entries must not silently renumber physical wiring.

**Settings → Mute** gates execution without changing allocation, timeline,
playhead or available voices; STOP still passes. Inventory `enabled` is a JSON
planning/configuration setting, not the former UI Enabled switch. There is no
current Add/Remove device panel or ESP32 bring-up inventory selector. See the
[registry and profile guide](hardware-first.md).

**Settings → Serwis → Wgraj firmware ESP32** always targets ESP32 through USB.
There is no current Uno/ESP32 UI selector. PlatformIO defaults to Uno if no env
is given, so command-line ESP32 builds/uploads must explicitly use `-e esp32`.
CP2102 detection is an upload candidate, not proof of board identity or wiring.
Homing is a separate explicit service action; boot/reconnection does not home.

## BLE UART bring-up (same controller, second command transport)

BLE starts automatically in the **existing ESP32 firmware**, alongside USB
Serial. There is no separate Bluetooth controller or test firmware. Both
transports feed the same `CommandProtocol` dispatcher and existing
`Controller::command`. SPI uses GPIO23/18/22/21, speakers use GPIO25/26 and
TRACK0 uses GPIO34/35/36/39. The current application uses ESP32 BLE for runtime;
Uno Serial belongs to the retained legacy tools, not an alternate UI output.
There is no automatic Serial/BLE fallback. Firmware flashing still uses USB.

Device name: **Electromechanical-MIDI**. Nordic UART Service-compatible GATT:

| Endpoint | UUID | Properties / direction |
| --- | --- | --- |
| Service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` | Nordic UART Service |
| RX | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` | Write / Write Without Response, phone → ESP32 |
| TX | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` | Notify, ESP32 → phone |

Commands and responses are ASCII text, each terminated by LF (`0A`). CRLF is
also accepted. A command may span BLE writes; one write may contain multiple
commands. USB and BLE have independent 95-byte line buffers. An overlong line
returns `ERR LINE_TOO_LONG` and is discarded until LF. Invalid/NUL text is
rejected instead of executing a truncated command.

### Phone: connection → PING → TEST ON → TEST OFF

1. Upload this main firmware to the **ESP32**, using the application's ESP32
   target or the upload command below. This change has **not** been flashed
   or physically tested over Bluetooth by the coding agent.
2. Connect **GPIO27 → 330 Ω → LED anode → LED cathode → GND**. The LED is
   external; no onboard LED is assumed. Firmware loads LOW before enabling
   the output, before SPI or BLE initialization. For a guaranteed LOW also
   during ROM boot/reset (before firmware executes), add a 10 kΩ pull-down
   from GPIO27 to GND. Keep motors disconnected for this first LED test.
3. Open a BLE GATT client such as **nRF Connect for Mobile**, scan, select
   `Electromechanical-MIDI` and **Connect**. Enable notifications on **TX**
   (`…0003…`, CCCD `0x2902` = `01 00`) **before writing any commands**.
   Name may appear in scan-response data. There is no required bonding/PIN
   in this bring-up interface. Only one BLE client is supported at a time.
4. Write `PING` plus an actual newline to **RX** (`…0002…`). If the phone's
   text input cannot append LF, use the hexadecimal values in the table.
   Typing the literal characters `\n` is **not** an actual newline.

| RX write, HEX bytes including LF | Command | Expected TX text / effect |
| --- | --- | --- |
| `50 49 4E 47 0A` | `PING` | `PONG` |
| `54 45 53 54 20 4F 4E 0A` | `TEST ON` | `TEST ON`; external LED lights |
| `54 45 53 54 20 4F 46 46 0A` | `TEST OFF` | `TEST OFF`; LED goes dark |
| `54 45 53 54 20 54 4F 47 47 4C 45 0A` | `TEST TOGGLE` | `TEST ON` or `TEST OFF`; flips LED |
| `54 45 53 54 20 53 54 41 54 55 53 0A` | `TEST STATUS` | `TEST ON` or `TEST OFF`; no GPIO change |
| `53 54 41 54 55 53 0A` | `STATUS` | Existing `STATUS BEGIN` … `STATUS END` transaction |

Responses may span multiple notifications (20 bytes each, also valid at MTU
23); concatenate payloads and split on LF. STATUS takes longer than PING
because notifications are paced. Successful motor commands remain silent,
as with USB. Errors, PONG, TEST replies and STATUS return **only through the
originating transport**; delayed HOME failures also remember the original
transport/session. USB boot READY remains on USB. Connecting/disconnecting
BLE does not issue STOP, HOME or any actuator commands. Advertising resumes
after disconnect, and partial input/old replies never carry into a new session.

BLE callbacks only copy received writes into a bounded FreeRTOS queue and
update transport flags. `loop()` consumes at most 16 USB bytes and 16 BLE
bytes per iteration, through the shared dispatcher. BLE notifications run in
a separate core-0 task, not the core-1 motor loop. RX overflow reports
`ERR RX_OVERFLOW`, discards pending BLE input and seeks the next LF boundary;
TX overflow reports `ERR TX_OVERFLOW` after the output queue drains. Neither
queue waits in the motor loop. The existing motor watchdog still stops
actuators after 3 seconds without controller commands: send PING at least
once per second while testing motor playback. TEST only controls the LED.

**SOFTWARE VERIFIED ONLY:** native tests exercise the actual dispatcher and
ESP32 callbacks/queue adapter with fake Arduino/NimBLE/FreeRTOS. Real radio
connectivity, notification delivery, LED wiring and STEP jitter under radio
load still require the phone/hardware test. USB and BLE address the same
actuators; the latest executed command from either transport wins.

## Build and offline checks

```sh
~/.platformio/penv/bin/pio run -d firmware/controller -e esp32
~/.platformio/penv/bin/pio run -d firmware/controller -e uno
.venv/bin/python -m unittest discover -s host/tests
npm --prefix web test -- --run
npm --prefix web run build
```

Platform `espressif32@7.1.3` pins Arduino-ESP32 2.0.17, whose LEDC API differs
from core 3.x. Do not change core major version without porting LEDC calls.
This is the stable [PlatformIO release v7.1.3](https://github.com/platformio/platform-espressif32/releases/tag/v7.1.3),
compatible with the classic ESP32-WROOM-32 (`board = esp32dev`).
The controller does not use SPIFFS/LittleFS or build/upload a filesystem image.
In this platform version, filesystem tools are optional for a normal build.
However, PlatformIO Core enables all packages classified as `uploader` for
upload targets, including `tool-mkspiffs`, `tool-mklittlefs` and `tool-mkfatfs`.
They may therefore be installed by `-t upload` even though firmware flashing
uses only `tool-esptoolpy` and this project does not use a filesystem.
No filesystem dependency or macOS
quarantine/security bypass is needed or configured by this project.
If an existing native PlatformIO environment reports
`ModuleNotFoundError: No module named 'intelhex'`, install the esptool Python
dependency in that same environment (not a filesystem tool):

```sh
~/.platformio/penv/bin/python -m pip install intelhex==2.3.0
```

That command repairs only the `~/.platformio/penv/bin/pio` installation.
For Homebrew `pio`, use the **Python Executable** reported by `pio system info`
with `-m pip install intelhex==2.3.0`; these are separate Python environments.

The ESP32 environment alone pins `h2zero/NimBLE-Arduino@1.4.3`; one BLE
connection, with the NimBLE host task on core 0. Uno does not link Bluetooth.
To upload from the current Settings service or explicitly from the CLI:

```sh
~/.platformio/penv/bin/pio run -d firmware/controller -e esp32 -t upload --upload-port /dev/cu.YOUR_CP2102
```

For Serial monitoring, the ESP32 environment sets `monitor_dtr = 0` and
`monitor_rts = 0` so the monitor does not assert the USB-UART auto-reset lines.
From `firmware/controller`, use:

```sh
pio device monitor -e esp32 -p /dev/cu.YOUR_CP2102 -b 115200 --dtr 0 --rts 0
```

`READY protocol=2 board=esp32` is emitted once per firmware boot, not per
PING, STATUS, HOME or BLE connection. Opening a monitor on an already running
board may show no READY; PING still returns PONG. Repeated READY must not be
filtered out: capture the raw boot/reset log to diagnose it.

## Physical bring-up sequence

1. Before motor power, verify GPIO/Q wiring, /OE pull-up, /SRCLR and grounds.
2. Boot ESP32 with actuators **disconnected**; check READY and PING→PONG.
3. STATUS: manually toggle each TRACK0 input; verify raw=0/track0=1.
4. Isolated register mapping: run `DIAG BIT 0`, then 1…39 manually and
   measure the matching Q output. **All actuators disconnected**: this command
   intentionally overrides STEP safe levels and can raise nSLEEP. No automatic
   walking-bit runs at boot. Restore with `ALL STOP` before connecting motors.
5. Connect only FDD1; confirm 3.3 V logic levels. `FDD 1 HOME`, STATUS until
   homed=1, then `FDD 1 PLAY 220.00`. Send PING at least once per second;
   stop with `ALL STOP`. Otherwise watchdog stops after 3 seconds.
6. Repeat for FDD2–4; then FDD ALL HOME. Never use a position estimate to
   compensate drift: TRACK0 alone reverses the return travel.
7. Add one DRV8833 bridge at a time with correct VM. Check HDD impulses,
   then explicitly enable and calibrate each sled/tray. Check coil order and
   travel, motor current and temperature before sustained sled PLAY; the proposed
   DVD VM of 3.3 V still requires these measurements. Verify both speaker drivers
   on GPIO25/26 and measure their response.
8. Connect via app, load target preset, verify enabled devices and physical
   IDs, upload ESP32 firmware if needed, wait for confirmed HOME and Play.

Primary references for electrical pin naming/API versions:
[TI SN74HC595 datasheet](https://www.ti.com/lit/ds/symlink/sn74hc595.pdf),
[Espressif Arduino core migration guide](https://docs.espressif.com/projects/arduino-esp32/en/latest/migration_guides/2.x_to_3.0.html).


## Normal runtime over BLE

The current application starts with REAL output and ESP32 BLE transport.
`Settings → Output` changes REAL/VIRTUAL, not the controller target. No current
controller selection is read from `midi/.controller.json`. ESP32 is discovered
by name/NUS service, TX notifications are subscribed before RX commands, and
PING/PONG plus a complete STATUS establish the session; BLE does not receive
USB boot READY. STATUS transactions are serialized.

Discovery/connection failures are retried with a two-second pause. Reconnection
establishes a confirmed STOP baseline and never replays a song or homes FDD.
An active transport loss stops scheduling and exposes the hardware uncertainty;
it is distinct from an actuator error such as HOME_FAILED. Missing STOP
acknowledgement also does not by itself mean BLE disconnected. Readiness for
PLAY requires configuration capabilities, ENABLE and FDD HOME confirmation.

### macOS + Docker

The Linux Docker VM cannot use macOS CoreBluetooth directly. The native
`host/ble_gateway.py` bridges command bytes from the container to BLE using
Bleak; it never opens Serial and never parses motor commands. Its TCP endpoint
is loopback-only (`127.0.0.1:8766`), accessible to OrbStack containers through
`host.docker.internal`. It opens BLE only while a runtime client is connected.

Install dependencies into the native environment and run it in a terminal:

```sh
.venv/bin/python -m pip install -r host/requirements.txt
.venv/bin/python host/ble_gateway.py
```

For automatic startup after login, explicitly install the per-user service:

```sh
.venv/bin/python host/ble_gateway.py --install-macos-service
```

This registers `~/Library/LaunchAgents/com.chopapik.electromechanical-midi.ble.plist`.
Logs are in `.runtime/ble-gateway.log`; launchd restarts the helper if it exits.
To remove the service:

```sh
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.chopapik.electromechanical-midi.ble.plist
rm ~/Library/LaunchAgents/com.chopapik.electromechanical-midi.ble.plist
```

Allow Bluetooth access in macOS if prompted. A denial or unavailable adapter
is surfaced as a connection error; the runtime keeps retrying without switching
to Serial. Disconnect other BLE clients (including a phone test app): firmware
supports one client. Compose supplies `ORCHESTRA_BLE_GATEWAY=host.docker.internal:8766`.
A backend running natively with that variable unset uses Bleak directly.

Bring-up verification covers real discovery and Docker → gateway → ESP32
PING/STATUS. Offline tests cover packet fragmentation, command order, common
STATUS parsing, transport loss, retry, legacy Uno isolation and UI status.
BLE playback timing and all physically wired devices require separate hardware
validation; the gateway does not alter MIDI routing or firmware.

## Confirmed runtime STOP over BLE

The native gateway reads incoming commands independently of GATT writes.
`ALL STOP` takes priority: it discards previously queued commands, finishes
one in-flight command line and sends STOP next. Old PLAY commands cannot
restart an actuator after that STOP. No ordinary MIDI allocation is changed.

Firmware advertises `stop_ack=1` in STATUS CTRL. The host sends
`ALL STOP <numeric-token>`; the shared dispatcher first executes the existing
ALL STOP and then replies `STOPPED <same-token>` on the originating transport.
Its BLE acknowledgement takes priority over queued telemetry. A stale STOPPED
reply with another token is not confirmation. Untagged ALL STOP stays compatible.

The runtime waits up to 2 seconds for execution acknowledgement before reporting
a successful explicit Stop. Missing acknowledgement produces an explicit error
and leaves playback paused, without declaring USB/BLE disconnected solely
because of that missing acknowledgement. A broken connection still relies on
the existing 3-second firmware watchdog.


## Articulation and physical FDD

Physical STEP/DIR supplies a continuous STEP train at requested pitch; there is
no amplitude control in this FDD wiring. Virtual tonal envelopes are acoustic
approximations, not physical burst gating. Former RAW/EXTREME mode selectors
are absent from the current UI; the retained articulation modules supply the
runtime's execution sidecars. Source Continuity and preset gates affect the
common plan. All presets and STRICT_TRACKS additionally apply the final
[FDD attack-rate reduction](fdd-attack-rate.md). Skipping individual STEP pulses
to mimic volume changes pitch and is not the articulation mechanism.

## DVD Stepper continuous rotation

All four DVD steppers default to `continuousRotation=true`. Host configuration
sends `SLED n PROFILE 0 5000 <pitchRatio>` and `SLED n DIR FWD`
(ratio 0.5 for DVD1–3, 1.0 for DVD4): travel 0 explicitly means
continuous rotation without automatic endpoint reversal. Positive travel values
still select bounded motion; -1 remains unknown travel and rejects PLAY.

Measured DVD1 bands remain in the calibration metadata, but continuous mode
does not block them or fold notes into those bands. Finite positive frequencies
are accepted within the controller's timer representation: the 100 us minimum
step period permits at most 10,000 steps/s at pitchRatio=1. Acceleration ramps,
STOP, disable and the communication watchdog still apply. This timer bound is
not the arrangement range: the hardware allocator folds DVD pitches above
**600 acoustic Hz** down by octaves before converting through pitchRatio.
Manual protocol/Laboratory tests do not run that musical folding policy and
must still obey the effective hardware profile. Neither bound proves thermal safety.

The relative `position` counter is telemetry, not a physical position sensor.
It now saturates at signed 32-bit limits without stopping rotation or wrapping.
Manual `DIR REV` remains available. STOP and subsequent PLAY preserve position.
The Q8–Q23 mapping and coil phase sequence are unchanged.

This requires the new ESP32 firmware advertising `dvd_continuous=1` in controller
STATUS. Rebuilding Docker updates the host and UI; use Settings → Wgraj firmware
ESP32 to apply the controller change through USB.

Example status:

```text
STATUS SLED 1 enabled=1 playing=1 hz=250.00 position=173 dir=fwd soft_min=0 soft_max=0
```


### Restored full physical inventory

`config/hardware-profiles/instances.json` declares 4 FDD, 4 DVD sled,
4 HDD VCM and the main legacy-named VHS/PC Speaker present. The application
registry additionally declares PC Speaker FX on `drum:2`. All four FDD retain the shared controller execution
settings: 72 away steps, 5 ms direction setup and 2439 us minimum step interval.
This is a shared software configuration, not an individual calibration claim.
DVD1–4 use continuous rotation by default. Their previous 140-step travel
settings and DVD1 frequency measurements remain historical calibration data;
continuous mode does not enforce them. Tray configuration is unchanged.
