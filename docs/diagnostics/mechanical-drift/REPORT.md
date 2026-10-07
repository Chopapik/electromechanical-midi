# Mechanical playback drift — audit BEFORE the fix

Branch: `fix/mechanical-playback-drift`, baseline `b9a9a7e`.
No ESP32 flash, wiring, motor-range, routing or UI changes. Physical BLE tests
use PING only; no motor playback is claimed. Creep file: `0002-02-radiohead_1993-creep-[k] (2).mid`.

## Root cause and evidence

**Classification E: B (BLE blocking/backlog), plus A under scheduler overload.**
There is no demonstrated accumulated hardware-first delay (C) in this MIDI.
Firmware timing (D) is not measured electrically and is not ruled out for
individual STEP edges; it is unnecessary to explain the common slowdown.

1. Direct `BleBytes.write` waits on `future.result(timeout=2)` while `_write`
   performs acknowledged 20-byte GATT writes sequentially. Measured 100-PING
   mean: **38.590 ms**, p95 **55.992 ms**, p99 **56.430 ms**, max **56.459 ms**.
   That is approximately 25.9 writes/s. PING includes notification traffic;
   these are host GATT timings, not motor-execution measurements.
2. Docker `GatewayBytes.write` only calls TCP `sendall`: mean **0.00815 ms**.
   100 sends completed in **0.913 ms**, but 100 PONG replies arrived after
   **3.886 s**. The detached gateway FIFO hides real delivery time from the
   engine and accepts up to 4096 lines. The real gateway log records a STOP
   discarding **2787 queued commands**. FIFO delays affect VHS/PC speaker as
   well as all other devices, explaining the common symptom without mechanics.
3. `_plan_locked` recomputes `monotonic() - origin` after each send. It implements
   catch-up A, not origin-reset B. However, its unbounded while loop sends every
   overdue event and only stops after **all** commands are drained. A 60 s
   timeline with 3750 note commands and 20 ms/write ends at **75.040 s** in the
   actual engine under a simulated monotonic clock. The UI clock is correct;
   delivery and the completion condition are not bounded to that clock.
4. Creep at 20 ms/write: maximum actual-engine simulated dispatch lag **8.702 s**,
   despite mean planned delay **20.956 ms**, maximum **86.957 ms**. The
   detached FIFO model using measured 38.590 ms/write reaches **61.567 s**
   maximum delivery delay. This model is labelled as a simulation in the CSV,
   not a physical measurement. Final modeled FIFO delivery: **270.420 s**.
   Actual runtime STOP priority can discard the unfinished FIFO at song end.
5. Older `bf75d47` uses the same detached gateway and scheduler loop. The same
   offline inventory/MIDI produces **6434 writes** versus **5505** after
   hardware-first. This song does not establish increased command count from
   hardware-first; do not assume the newest commit created the original bug.

## Physical BLE send samples before the fix

| Commands / samples | Mean ms | p95 ms | p99 ms | Max ms |
|---:|---:|---:|---:|---:|
| 1 | 35.213 | 35.213 | 35.213 | 35.213 |
| 10 | 37.392 | 40.912 | 40.912 | 40.912 |
| 100 | 38.590 | 55.992 | 56.430 | 56.459 |

Times are per blocking send, not full burst totals. The one-sample row cannot
establish a percentile distribution. Raw samples are in `ble-before.json`.

## Durations (seconds)

| Stage | Duration |
|---|---:|
| Original MIDI including meta/end-of-track | 237.377021 |
| Normalized source | 237.377021 |
| PerformancePlan | 233.667576 |
| Physical command timeline | 233.667576 |
| Merged runtime command timeline | 233.720026 |
| Production engine, simulated monotonic clock, 20 ms/write | 233.740026 |

The plan excludes trailing source silence / clipped note tails. The merged
virtual renderer has a 52.45 ms tail. Neither is progressive time stretching.
The real worker-thread / monotonic run with an in-memory 20 ms-write transport
ended at **233.776490 s**, with maximum dispatch lag **19.045923 s**, p95
**17.781921 s**, p99 **18.933611 s** (`wall-clock-before.json`). It is not physical
audio playback. This confirms that an almost correct finish time alone does not
prove that notes during the song are on time.

## Timestamp map

- `MidiSource._extract`: absolute MIDI ticks converted with original tempo
  map, independent of motor readiness. `duration` uses `mido.MidiFile.length`.
- Duplicate normalization retains source duration; logical tracks retain the
  representative timestamps and provenance, not cumulative playback waits.
- Legacy allocator: `_place` stores source `start` separately from
  `actual_start`; delays are bounded relative to each source timestamp.
- Physical allocator: `max(span.start, ev.ready_at, slot.busy_until)` is checked
  against that event's micro/arpeggio window. Over-budget notes drop, so a
  motor's readiness cannot shift all future source events indefinitely.
- `advance_state`: ready-at is per device. FDD reversal and DVD acceleration /
  braking remain local model costs. They are not an engine origin offset.
- Articulation changes ends/sustain in free slots; it does not advance the MIDI
  origin. Final physical validation can drop overlaps.
- `PerformancePlan.duration` is max event end; `build_plan_commands` uses
  `actual_start` directly. No sequential sum of event durations.
- `VirtualOrchestra.render_plan` generates the preview/virtual timeline; engine
  merges it with physical commands. No replacement of physical timestamps by
  an acoustic model on the hardware-first path.
- `PlaybackEngine`: absolute origin; elapsed send time causes catch-up, not an
  origin update. Under sustained overload its drain-all rule violates deadline.
- TCP/native BLE: FIFO detached from the playback clock; no expiry/deadline.
- ESP32: command parser has no song timeline. It starts local oscillator / ramp
  on command receipt. Firmware motor timers do not synchronize upstream MIDI.
  GPIO25 LEDC for VHS shares command delivery with FDD/SLED, not their mechanics.

## Event table and progression

`creep-events-before.csv` contains **3199 played events**, with originalTime,
plannedTime, commandTime, dispatchTime, deltaFromOriginal, device, command,
and modeled gateway deliveryTime/deliveryDelta. `dispatchTime` is production
engine execution with a virtual clock and 20 ms/write; no measured physical
event execution is implied. `plan-before.json` contains 30 s timing buckets.
Planned delay stays within 0–86.957 ms; FIFO mean grows from **30.5 ms** (0–30 s)
to **56.721 s** (180–210 s). It falls during sparse passages: not strictly
monotonic, but unequivocally accumulating queue latency.

Six same-timestamp writes at measured average cost consume about **231.5 ms**;
VHS note-on is TWO writes (AMP + FREQ), making seven writes about 270.1 ms.
A local group offset clears during gaps; sustained command load greater than
link throughput propagates it into later music. No global origin shift needed.

## Minimal fix proposed before editing production code

1. Use negotiated ordinary ATT payload size and batch already-due complete
   lines in the native gateway. Retain acknowledged writes, framing, ordering
   and priority ALL STOP. Do not wait for future notes or alter the MIDI tempo.
2. Bound gateway latency and stop/notify the runtime on congestion instead of
   replaying seconds-old notes. Send a best-effort emergency STOP; do not claim
   delivery when radio is unavailable. Preserve firmware watchdog as fallback.
3. Bound engine catch-up: discard expired note-on / impulse commands locally,
   retain STOP, and stop at timeline end without draining overdue history.
   Limit one catch-up pass to a short wall-clock budget to keep UI/STOP responsive.
4. Add deterministic 60 s / 20 ms-write regression plus queue, simultaneous
   group, STOP and fragment tests. Keep classification/routing/profiles unchanged.

Risks: overload now causes explicitly counted lost notes or a transport pause
instead of hidden tempo stretching. A GATT write already in flight cannot be
retracted; STOP waits behind that one write. GATT ACK confirms receipt, not the
exact motor execution edge. No sample-accurate hardware synchronization is
claimed. Physical audio verification remains a separate test.


## Code references (current checkout; baseline compared before editing)

| Stage | Source |
|---|---|
| MIDI tempo / absolute note times | `host/midi_source.py:473` (`_extract`) |
| Source versus actual allocation | `host/playback/allocator.py:287` (`_place`) |
| Physical arrival bounded to source window | `host/playback/hardware_arranger.py:109` |
| Per-device readiness | `host/playback/hardware_profiles.py:389` |
| Direct plan-to-command timestamps | `host/playback/hardware.py:209` |
| Absolute origin, deadline, bounded catch-up | `host/playback/engine.py:2166` |
| Blocking acknowledged GATT / MTU | `host/ble_link.py:98` |
| Detached FIFO, batching, latency watchdog | `host/ble_gateway.py:17` and `:49` |
| ESP32 parser in loop, local motor clocks | `firmware/controller/src/esp32/main.cpp:163` |
| VHS LEDC updates on receipt | `firmware/controller/src/esp32/main.cpp:25` |

## Implemented fix and verification

- No firmware, mechanical profiles/limits, classification, MIDI routing, or UI
  source changed. `write_gatt_char(response=True)` remains acknowledged: direct
  transport still blocks the caller. Native TCP gateway batches already received
  complete lines using negotiated ATT capacity (252 bytes observed on ESP32).
- Native FIFO budget is 250 ms / 512 lines. On overrun it reports BLE ERROR,
  discards stale traffic, attempts ALL STOP and closes the session. The runtime
  recognizes fragmented gateway errors and pauses rather than ignoring them.
  In-flight writes cannot be recalled; STOP follows that write. A stalled write
  can still take the existing 2 s transport timeout, and radio failure may prevent
  STOP delivery. The firmware safety watchdog remains unchanged.
- Engine keeps original origin. It skips note-on/impulse commands over 100 ms
  late, retains normal note-offs, releases its lock after a 50 ms catch-up budget
  (plus the last write), and stops at the original command-timeline deadline
  instead of draining history. Final ALL STOP replaces unfinished tail commands.
  Offline rendering and pure virtual audio scheduling are unaffected.
- API `hardware.timingDiagnostics` exposes lifetime late-command and end-discard
  counts plus max observed scheduler lag. This is host lag, not physical delivery
  or motor-edge timing. The frontend was not changed.

| Check | Before | After |
|---|---:|---:|
| 60 s / 3750 note-ons / 20 ms-write engine, deterministic clock | 75.040 s | **60.021 s** |
| Creep max dispatch lag, deterministic 20 ms-write engine | 8.702 s | **117.610 ms** |
| Creep p95 dispatch lag, same model | see plan-before.json | **91.594 ms** |
| 10 separate physical BLE PING writes, summed send time | about 374 ms | **35.556 ms for one batched write** |

The physical batched test returned all **10 PONGs in 233.006 ms**; it tested
command framing/transport, not motor execution. JSON: `ble-batch-after.json`.
Creep's deliberately slow direct-link simulation discards **461** late note-on /
impulse commands; normal allocation is not modified. The 60 s stress case skips
744 late commands and replaces 7 unfinished tail commands with ALL STOP. These
are explicit runtime degradations, not a claim of unchanged played counts.
`plan-after.json` / `creep-events-after.csv` describe direct simulated dispatch.
Their FIFO fields deliberately model the **old unbounded FIFO**, for comparison;
they are NOT a simulation or measurement of the corrected batching gateway.

Final verification: **642 host tests passed**, **131 frontend tests passed**,
frontend production build passed, Docker application rebuilt/restarted. Physical
BLE connected, FDD1 homed/ready at idle. ESP32 was **not flashed**. Physical
multi-instrument song synchronization still requires a listening/edge test; no
physical song or sample-accurate synchronization is claimed here.

Reproduce the offline audit (no hardware):

```sh
PYTHONPATH=host:. .venv/bin/python scripts/audit_mechanical_drift.py --label after
PYTHONPATH=host:. .venv/bin/python -m unittest host.tests.test_playback_drift -v
```

`--wall-clock --label after` runs the real engine worker with an in-memory slow
transport. Before evidence was captured before production edits and is retained
in the `*-before` files. No commit or push was performed.
