# Production mechanical playback drift fix

Branch: `fix/mechanical-playback-drift`. Baseline: `b9a9a7e`.
Classification **E: BLE backlog (B), plus scheduler deadline failure under overload (A)**.
Firmware, wiring, mechanical calibration, arranger and frontend source are unchanged.
No flash, commit or push was performed.

## 1. Root cause

The MIDI clock was absolute, but delivery was not bounded to it. A confirmed BLE
write cost 38.590 ms mean, 55.992 ms p95, 56.430 ms p99 (100 physical PINGs).
The detached TCP-to-BLE gateway accepted thousands of lines, masking real delivery
latency from the runtime. Its log recorded a STOP discarding 2787 queued commands.
The engine additionally drained every overdue command before declaring completion.
A 60 s schedule with 20 ms per write therefore ended at 75.040 s.

Hardware-first delayed Creep notes locally by at most 86.957 ms, without cumulative
plan drift. A real worker-thread test with a slow **in-memory** link reached
19.046 s dispatch lag. This was not a physical song test. See `REPORT.md` and
`*-before.json` for the completed audit and the 3199-row original/planned/dispatch
CSV. Firmware motor-edge timing remains electrically unmeasured.

## 2. Previous flow

```text
absolute timeline -> overdue loop -> one command / write
                  -> fast TCP acceptance -> unbounded stale BLE FIFO
                  -> acknowledged 20-byte GATT writes -> firmware line parser
```

Neither scheduler origin nor source timestamps shifted. Slow delivery and draining
history caused the audible slowdown, including VHS/PC speaker.

## 3. New flow

```text
absolute timeline
 -> expiration / supersession check against immutable per-lane timeline
 -> identical already-due timestamps grouped, original order retained
 -> v2 send_batch(lines), AMP before FREQ / STOP before PLAY retained
 -> one ordered newline byte stream
 -> negotiated ATT fragments under one write lock, response=True
 -> existing firmware line parser
```

`OrchestraLink.send_batch` is the v2 API; Serial retains ordered individual writes.
`BleOrchestraLink.send_batch` writes the complete newline-delimited batch once.
The engine opts into batching only for BLE v2, without changing Serial/Uno behavior.
The batch window is **exact equality of command.time (0 ms)**: no waiting for
future events, early delivery or quantization. Separate timestamps remain separate
logical engine operations. The gateway can also coalesce complete lines that have
already arrived. All were already due when sent by the engine.

After every blocking batch the engine recomputes `monotonic() - origin`. It never
adds transport duration to source timestamps or changes `origin` to dispatch time.
One catch-up pass releases the engine lock after 50 ms plus its last in-flight
operation, allowing STOP and transport-error polling to interrupt congestion.

## 4. Before / after benchmark

The dense fixture is 10 groups, six tonal lanes per group, separated by one second.
The same immutable timeline runs through the production scheduler with a virtual
monotonic clock. Each single write or batch costs 20 ms. No physical song implied.

| Metric | Individual dispatch | Batch dispatch |
|---|---:|---:|
| Musical note commands | 60 | 60 |
| Logical note transactions | 60 | **10** |
| Commands per group / transaction | 1 | **6** |
| Transport cost for one six-command group | 120 ms | **20 ms** |
| Max observed scheduler lag | 100.001 ms | **0 ms** |
| Dropped / collapsed | 0 / 0 | **0 / 0** |
| Schedule / completion | 10 s / 10.020 s | 10 s / **10.020 s** |

The final fail-safe ALL STOP is an additional transaction in both cases (total
61 versus 11). These are logical transactions; a larger batch may need multiple
ATT fragments. Six commands fit the 252-byte payload observed on this ESP32.
Zero scheduler lag means group dispatch began on time, not zero radio/firmware
latency. All command and timeline timestamps remain unchanged.

Raw results: `production-scheduler.json`.

## 5. 60 s scheduler regression

3750 PLAY events on a single lane plus final STOP, 20 ms per operation:

| Metric | Result |
|---|---:|
| Original baseline completion | 75.040 s |
| Production fix completion | **60.021 s** |
| Logical final position | **60.000 s** |
| Max observed scheduler lag | **16.998 ms** |
| Dropped late note events | **750** |
| Of those, superseded / collapsed | **749** |
| Expired | **1** |
| Unfinished tail commands replaced by ALL STOP | **2** |
| Final wire command | **ALL STOP** |

Collapsed events are a subset of dropped events, not an additional 749 drops.
Reason counters include both LATE_SUPERSEDED and BACKLOG_COLLAPSED for those events,
so summing all reason counters also double-counts that diagnostic annotation.
The fixture intentionally demands 62.5 events/s from a 50 operations/s link; losing
intermediate states is unavoidable. The current required note is retained, without
playing intermediate obsolete frequencies or stretching tempo.

## 6. Physical BLE batching benchmark

Existing audit: ten separate PING writes took about 374 ms of blocked sending.
Previous raw batching validation: 35.556 ms for ten PINGs.

**New production `BleOrchestraLink.send_batch` on the real ESP32:**

- 10 PING commands, one logical batch, 252-byte negotiated payload;
- **37.123 ms** blocked send time;
- all **10 PONG** replies received in **238.009 ms**;
- confirmed writes (`response=True`), no actuator commands.

Reply completion includes firmware notification pacing; it is not ten commands'
execution latency. Raw result: `production-ble-batch.json`. This verifies the new
API and framing on actual BLE. No response=False deployment or claim of real-song
synchronization is made.

## 7. Drop / collapse / stop policy

- **Still-current tonal PLAY / VHS note-on:** execute immediately even if late,
  provided its timeline interval has not ended and no later state supersedes it.
- **LATE_SUPERSEDED:** a later same-lane state already became due; skip the old
  PLAY. Annotate it BACKLOG_COLLAPSED as well. The latest still-current state runs.
- **LATE_EXPIRED:** the note interval ended (its following same-lane STOP is due),
  or a one-shot HIT/TRAY pulse is over 100 ms old. Do not emit historical bursts.
- **STOP:** retained during catch-up. An overdue PLAY...STOP sequence sends STOP,
  not the obsolete notes. STOP before a fresh same-timestamp PLAY remains ordered.
- **End:** at `position >= timeline.duration`, replace unfinished history with
  fail-safe ALL STOP and store the logical final position as timeline.duration.
  Never drain stale PLAYs after the deadline.
- **Critical native gateway backlog:** 250 ms maximum age / 512 queued lines,
  transport error + best-effort ALL STOP + session close. Fragmented BLE ERROR
  messages are recognized by the runtime, which pauses rather than silently
  replaying stale notes. Reconnect never replays an old connection's queue.

The next same-lane command index is cached once per immutable Timeline; it is an
execution lookup, not a modification to allocation, routing or note timestamps.

## 8. Telemetry

`/api/state -> hardware.timingDiagnostics` exposes:

`schedulerLagMs`, `maxSchedulerLagMs`, `lateEvents`, `droppedLateEvents`,
`backlogCollapsedEvents`, `dropReasons`, `bleBatches`, `bleCommands`,
`maxCommandsPerBatch`, `lastBatchDurationMs`, `meanBatchDurationMs`.

Counters cover the engine lifetime, explicitly labelled `scope`. Lag includes
observed overdue events even when discarded. Duration measures the caller's
blocking operation: for Docker's TCP gateway this is acceptance time, not GATT
completion. `bleBatches` counts logical engine batches, not ATT fragments or native
gateway coalescing. Legacy `lateCommands`, `discardedAtEnd`, `maxObservedLagMs`
remain available. No new UI is added.

## 9. Changed files

Production code:

- `host/playback/engine.py`: immutable-state backlog policy, exact-time batches,
  deadline, bounded catch-up, diagnostic counters, shared v2 line generation.
- `host/orchestra_link.py`: batch API with existing Serial behavior.
- `host/ble_link.py`: BLE batch framing, acknowledged MTU fragmentation, ordered
  TCP writes and gateway error propagation.
- `host/ble_gateway.py`: already-due batching, bounded queue age, priority STOP.

Tests / reproducible artifacts:

- `host/tests/test_playback_drift.py`
- `host/tests/test_ble_link.py`
- `host/tests/test_ble_gateway.py`
- `scripts/audit_mechanical_drift.py` (prior audit, before artifacts preserved)
- `scripts/benchmark_playback_scheduler.py` (production no-hardware benchmark)
- `docs/diagnostics/mechanical-drift/`: audit report, FIX_REPORT, JSON measurements,
  CSV event traces and production benchmark outputs.

No firmware, arranger, calibration, routing, normalization or frontend source
files changed. Firmware does **not** need flashing for this host-side fix.

## 10. Tests and verification

Regression tests cover:

- 60 s / 20 ms slow transport, both per-command and batch paths;
- six simultaneous devices -> one batch, AMP before FREQ;
- exact timestamp grouping, no early future command;
- two-second backlog -> current note only;
- expired note -> STOP, stale one-shots -> no burst;
- timeline already ended -> ALL STOP, no PLAY;
- STOP before PLAY in a batch;
- send_batch failure -> pause and fail-safe STOP;
- fragmented concurrent batches cannot interleave and preserve newline framing;
- negotiated MTU, batch API, gateway congestion/error framing/STOP priority.

Final results:

- **652 host tests passed**, including slow-transport and native gateway tests.
- **131 frontend tests passed** (14 suites); frontend source was unchanged.
- `pio run -e esp32`: **SUCCESS**, RAM 38,916 / 327,680 bytes (11.9%),
  flash 615,977 / 1,310,720 bytes (47.0%). Build only, no upload.
- `git diff --check`: clean.
- Docker application rebuilt/restarted; API confirmed stopped, BLE connected,
  FDD homed/ready, no hardware error, new timing diagnostics available.
- No physical multi-instrument song was played for these benchmarks.

The prior frontend production build passed in the audit step; Docker's production
frontend build also passed while rebuilding this final application.

Reproduce without hardware:

```sh
PYTHONPATH=host:. .venv/bin/python -m unittest discover -s host/tests
PYTHONPATH=host:. .venv/bin/python scripts/benchmark_playback_scheduler.py
cd web && npm test
cd ../firmware/controller && pio run -e esp32
```

## 11. Known risks / limits

An acknowledged GATT write confirms receipt, not the precise motor edge. Batching
cannot increase radio capacity infinitely. Physical playback can still degrade
or pause if capacity is exceeded, but must not stretch its source clock.
An in-flight packet cannot be recalled. STOP waits behind it; a hung write can
reach the existing 2 s transport timeout. Broken radio can prevent STOP delivery;
the unchanged firmware watchdog remains the fallback. Synchronous final STOP
confirmation can delay return to the caller; stored logical position remains the
original end, without replaying history.

A latest still-active tonal event may start late, intentionally shortened to its
original remaining interval. Historical STOPs remain rather than aggressively
optimizing safety commands. Exact-time batches leave adjacent different timestamps
unquantized; native batching only uses already-received data.

Multi-instrument physical song synchronization is not claimed from PING tests.
Electrical/aural validation remains possible without changing firmware or limits.
