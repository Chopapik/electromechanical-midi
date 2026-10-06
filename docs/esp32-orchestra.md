# ESP32 orchestra bring-up

Target: ESP32-WROOM-32, 38-pin Micro-USB/CP2102. Firmware lives in
`firmware/controller/src/esp32/main.cpp`; device logic and the **single source of
truth for GPIO/Q mapping** live in `firmware/controller/include/orchestra_core.h`
(`orchestra::map`). Uno remains separately compiled from `src/main.cpp`.

## Software and physical verification

**SOFTWARE VERIFIED** means compilation and native/host tests, not bench tests.
The offline tests run the production core with fake clock, sensor and latch
edges: safe boot, all 40 bits and byte order, four independent FDDs, simultaneous
STEP frames, minimum pulse spacing, DIR settle, STOP→PLAY, TRACK0 reversal,
initial HOME and timeout, watchdog/all-stop, HDD phases, sled phases/reverse,
tray timeout, disabled devices and ASCII command parsing. Serial status is
parsed only when a complete BEGIN/END transaction arrives.

**REQUIRES PHYSICAL CALIBRATION:** STEP/DIR input compatibility at 3.3 V for each
FDD; TRACK0 voltage and active-low behavior; DVD coil order, direction and travel;
HDD VM and impulse durations; tray VM/pulse duration; printer motor parameters.
No ESP32 hardware test has been performed. Software sled interval validation is
an implementation guard, **not** a measured safe motor Hz limit.

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
| 25 | VHS ICTL | Existing VHS driver/control input | LEDC PWM / tone; common GND |

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
stops VHS and deasserts nSLEEP. A 3-second host watchdog uses the same path.

FDD uses only TRACK0 and `awaySteps`. Away commands count up to 72, then
reverse; toward commands never count down and have no distance budget.
Physical TRACK0 resets awaySteps and reverses to AWAY. HOME alone has a
2-second emergency timeout. STEP low width is 30 µs; DIR changes settle for
5 ms (more than 30 µs minimum setup). The latch edge timestamp is recorded
after the physical pulse edge; subsequent pulses wait a full current period.
SPI work, status serialization and TX backpressure can make pulses late,
never compress them. No blocking Serial print is used in the pulse path.
FDD comfort stays 130–410 Hz; host folding is unchanged.

HDD start profile for ESP32 is **40 ms Park / 40 ms Settle / 4 ms Strike**,
then coast; this needs DRV8833 calibration. Uno's current physical profile is
40/40/**2** ms and remains separate (`WD_CAVIAR_CURRENT`). ESP32 uses
`DRV8833_HDD_START` in the bring-up preset so allocation sees its 84 ms cycle.
Busy hits return `ERR BUSY`; no hidden queue changes the plan.

SLED and tray are disabled by default. Sled uses four full-step two-coil
phases; `DIR FWD|REV` selects direction. STOP coasts, with no guessed travel
or homing model. Tray pulses are timed; STOP coasts immediately.
VHS uses ESP32 LEDC channel 0 on GPIO25. AMP is PWM duty 0–255;
FREQ selects tonal PWM frequency, FREQ=0 selects DC-mode carrier 20 kHz.
STOP sets duty 0. No AVR register/ISR code is shared with this target.

## Serial v2 and host

115200, 8N1, ASCII, newline. Boot: `READY protocol=2 board=esp32` confirms
controller startup, **not FDD homing**. `STATUS` emits BEGIN, CTRL, individual
FDD/HDD/SLED/TRAY/VHS records, END. `track0=1` means normalized ACTIVE;
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
VHS AMP 200
VHS FREQ 164.81
VHS STOP
```

Each device also accepts `ENABLE 0|1`, e.g. `SLED 1 ENABLE 1` or
`VHS ENABLE 0`. FDD/HDD IDs are 1–4, SLED 1–4, tray 1–2.
Legacy PLAY/STOP/HOME address FDD1; HIT addresses HDD1;
DRUM/DRUMF alias VHS AMP/FREQ. Legacy HDD 0 invokes all-stop.

`host/orchestra_link.py` subclasses the original FloppyLink: nonblocking
reads, protocol negotiation, individual ID methods, and atomic status parsing.
Uno still uses original command generation and handshake. For v2, the
playback engine binds lanes `fdd:1`…`fdd:4`, `sled:1`…`sled:4`, etc.
ID = device's order within its family in configuration (including disabled
and virtual entries); disabling device 1 never renumbers device 2. Keep that
order aligned with wiring. Extra unsupported instances appear as unmapped.
Disabled devices have no allocation, accepted render events, Serial commands
or active telemetry. Changing a disabled flag stops that actuator; newly enabled
FDD needs confirmed HOME before Play. After reconnect/upload/reset, the host
synchronizes configured enabled flags, executes FDD ALL HOME and polls complete
status until every enabled FDD is homed. Device errors never disconnect USB.

In **Orchestra → Load preset → ESP32 bring-up**, load the target inventory:
4 FDD, 4 HDD, 1 VHS enabled in real mode; 4 sled and 2 tray disabled.
For first single-FDD tests disable FDD2–4 and all other actuators first.
Firmware upload UI has an explicit Uno / ESP32 target selector; it keeps
Uno selected by default. Known Uno USB IDs are rejected for ESP32 upload.
The CP2102 VID is rejected for Uno upload; it does not prove any particular
ESP32 module identity, so verify the board physically.

## Build and offline checks

```sh
~/.platformio/penv/bin/pio run -d firmware/controller -e esp32
~/.platformio/penv/bin/pio run -d firmware/controller -e uno
.venv/bin/python -m unittest discover -s host/tests
npm --prefix web test -- --run
npm --prefix web run build
```

Platform `espressif32@6.9.0` pins Arduino-ESP32 2.0.17, whose LEDC API differs
from core 3.x. Do not change core major version without porting LEDC calls.
To upload, select target explicitly, or:

```sh
~/.platformio/penv/bin/pio run -d firmware/controller -e esp32 -t upload --upload-port /dev/cu.YOUR_CP2102
```

## Tomorrow: connect and test

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
   travel before sustained sled PLAY. Calibrate VHS GPIO25 input response.
8. Connect via app, load target preset, verify enabled devices and physical
   IDs, upload ESP32 firmware if needed, wait for confirmed HOME and Play.

Primary references for electrical pin naming/API versions:
[TI SN74HC595 datasheet](https://www.ti.com/lit/ds/symlink/sn74hc595.pdf),
[Espressif Arduino core migration guide](https://docs.espressif.com/projects/arduino-esp32/en/latest/migration_guides/2.x_to_3.0.html).
