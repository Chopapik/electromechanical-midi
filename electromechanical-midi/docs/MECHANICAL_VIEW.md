# Mechanical View — MVP

## Use

Open http://127.0.0.1:5173/ and choose **MECHANICAL VIEW** next to Arrangement.
Load MIDI in Player. Use the existing transport to play, pause, restart or seek.
Click a device for its event inspector; hover gives a short summary. “Show debug
labels” toggles pitch, role, track and device labels.

The view groups the configured instances into FDD, DVD sled, HDD VCM, VHS and DVD
tray grids. It follows the current inventory, including extra instances. Unknown
supported device kinds get a generic housing instead of crashing.

## Data and clock

`GET /api/mechanical` is a read-only projection of the engine's existing
PerformancePlan under its lock. It returns played primary events, acoustic
reinforcement, tray movements, inventory and effective device parameters.
It neither initializes nor reallocates a plan. Missing plans and empty plans
have explicit messages and idle widgets.

Primary intervals use **actualStart + performedDuration**, not MIDI source timing.
Reinforcement uses the pass's actual start/duration; tray movements include their
actual duration, cooldown and direction. Dropped events are excluded. Extra event
metadata is linked to the primary source event for pitch and source track.

The transport's existing interpolation was extracted into `usePlaybackClock`.
ProgressBar and Mechanical View both use this hook, anchored to the same backend
`position` and playback state on every update. requestAnimationFrame only fills
between backend updates, never schedules audio. Pause cancels interpolation and
freezes geometry. Seek reanchors immediately after the backend confirms the new
position. Stop shows idle; restart and backward seek resolve the new timestamp
without replaying historical events.

Device event lists are sorted and cached when a plan/file revision changes.
Each frame uses binary search and local overlap checks against a prefix end index.
No full plan analysis, allocation or audio work runs per animation frame.

## Meaning and simplifications

- Blue/cyan + **PRIMARY**: a normal planned event.
- Orange + **REINFORCEMENT**: an acoustic extra or tray accent.
- Gray + **IDLE**: no event at the current time.
- **COOLDOWN**: tray recovery, or the final configured HDD cycle phase.
- Paused active widgets retain their event badges, but stop moving.

FDD and DVD use bounded event-relative oscillation at a rate derived from played
frequency, not physical track position or exact motor pulse frequency. VHS uses a
frequency-dependent schematic drum rotation. HDD uses park/settle/strike timings
from its effective profile for a schematic swing and return. Tray movement is
linear in event progress; direction selects extension/retraction and the final
position remains until the next movement. Idle tonal mechanisms return to neutral.

This is a view of **planned mechanical activity**, not measured hardware telemetry
or an assertion that a muted device is audible. There is no acceleration, inertia,
GPIO, serial streaming, WebGL or physical calibration model. Audio rendering,
classification, allocation and articulation are unchanged.

## Files

- `host/playback/engine.py`: read-only mechanical projection.
- `host/web/server.py`: GET endpoint.
- `host/tests/test_web.py`: projection equality, empty plan and no mutation.
- `web/src/App.tsx`: new full-width tab.
- `web/src/components/MechanicalView.tsx`: grids, five SVG mechanisms, inspector.
- `web/src/components/MechanicalView.css`: layout, colors and schematic styling.
- `web/src/mechanical.ts`: typed event projection, cached index and state resolver.
- `web/src/usePlaybackClock.ts`: extracted transport interpolation.
- `web/src/components/ProgressBar.tsx`: uses the extracted clock.
- `web/src/components/MechanicalView.test.tsx`: eight UI/state tests.
- `web/src/fixtures/mechanical-demo.json`: small unmodified sample of the real
  allocator output for benchmark MIDI Creep with idle reinforcement enabled.
- `docs/MECHANICAL_VIEW.md`: this report.

## Verification

- Backend: `python -m unittest discover -s host/tests` — **357 tests passed**.
- Frontend: `npm --prefix web test` — **76 tests passed**, including eight new tests.
- TypeScript and production: `npm --prefix web run build` — **passed** (includes
  `tsc --noEmit`); separate typecheck also passed before adding tests.
- `git diff --check` — passed.
- No lint script is configured. Existing Orchestra tests still emit React act
  warnings; the backend suite emits its existing Starlette deprecation warning.

Tests cover current inventory, idle/active boundaries, performed timing, drops,
primary versus reinforcement, backward seek/restart/stop, pause interpolation,
tray recovery/rest position, HDD cycle, distinct mechanisms, empty plans, retry,
no refetch on clock ticks, and actual benchmark-generated event samples.

The standard dev script was restarted with `--no-hardware`. Browser checks on a
real Creep plan confirmed the tab, primary/reinforcement labels, playback, seek,
pause and device inspector. The debugger is preserved on the experimental branch
`codex/mechanical-debug-view`. The preceding global reinforcement work was
committed as `da30772` on `migrate`.
