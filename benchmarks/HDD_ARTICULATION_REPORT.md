# Vanilla HDD articulation — implementation and benchmark

## Scope and prerequisite

The active `main` checkout did not contain the global Idle Reinforcement feature
or the earlier four-HDD/tray inventory. Their existing implementation was ported
from `migrate` into the flat directory layout, preserving Master Volume. This is
why allocator/configuration/older test files appear in the diff. No new allocation
policy, classification, duplicate normalization or timing changes were introduced
for this sound experiment. The mechanical debugger remains on its separate branch.

**The before/after comparison below uses the restored existing four-HDD pool.**
It does not claim identical assignments to the older three-HDD `main` inventory.
All seven songs use the same default 4 FDD / 4 DVD / VHS / 4 HDD / 2 tray
configuration and global Idle Reinforcement enabled, without song-specific overrides.

## Implementation

`hdd_articulation.py` is the domain classifier and parameter model. VirtualOrchestra
passes original note/channel/velocity/manual articulation into it when translating
PerformancePlan to acoustic events. Channel 10 (zero-based 9) uses a complete
35–81 GM table. Other channels routed to percussion use a coarse pitched-percussion
contour. Audio synthesis consumes the resulting frozen decision; it does not guess
GM meaning. Reinforcement inherits the source decision before target-device density
adaptation. PerformancePlan itself is not modified.

| Articulation | Gesture / sound layers | Typical GM use |
|---|---|---|
| SOFT_TAP | brief dry contact, tiny body | closed/pedal hat, muted conga, woodblock, triangle |
| MEDIUM_HIT | short contact + restrained chassis resonance | most toms, open hat, bongos, bells, blocks |
| HARD_HIT | stronger contact/body, quickly damped chassis | kick, strong low toms, crash-like accents |
| DOUBLE_TAP | two opposed impulses ~18–26 ms apart | side stick, snare-like hits, clap, tambourine |
| BUZZ_ROLL | small impulse train, ~20–80 ms plus short release | ride bell, splash, vibraslap, cabasa, guiro |

The source code contains the full explicit GM mapping. Unknown GM notes fall back
to a velocity-dependent dry/medium/hard movement. `DOUBLE_HIT` is respected as a
legacy manual alias; no hardware commands are added.

Procedural layers: 1.3 ms impact transient; short VCM movement texture; two
inharmonic chassis modes; a restrained low body for harder gestures. No drum
samples, external plates, bells, cymbals or resonators. A SHA-256-derived device
variation changes chassis frequency by at most ±3%, with small click differences.
No unseeded randomness. Velocity changes body, movement, decay, gesture duration
and amplitude. Density reduces decay/body/duration rather than moving onsets.

### Monophony and priority

Each HDD's acoustic intervals are scheduled separately. A retrigger ends the
previous interval exactly at the next hit and fades its final 6 ms to zero.
There is no resonance stack for one actuator. RAW uses one ~9 ms transient with
no roll/body/ringing. ARTICULATED uses the family above.

Primary density/decay is computed from primary neighbors only; extra events cannot
change the normal timbre. An extra cannot choke an active PRIMARY gesture/tail. It is omitted if it would
interrupt that sound, or ends before the next PRIMARY. This changes only acoustic
extras; planned primary events and reinforcement allocation remain untouched.
The existing primary park/settle offset remains: primary contact is rendered at
actualStart + parkMs + settleMs (normally 80 ms). No new onset offset was added.

### Application

ORCHESTRA → **HDD sound** → `HDD RAW / DRY` / `HDD ARTICULATED`.
Defaults to ARTICULATED. Mode is validated and saved in Virtual Orchestra presets.
A mode-only change regenerates the disposable audio asynchronously, retaining the
normal plan, transport clock and current playback position. Master Volume remains
available. Ordinary allocation continues while the replacement audio is prepared.

## Seven-song benchmark

Two independently allocated plans have identical full primary event decisions,
reinforcement decisions and tray decisions. Rendering each mode also checks that
no primary event dictionary changed. Aggregate PRIMARY totals: **39,867 played,
1,717 dropped in both modes**. These are normal allocator losses already present
in the common baseline, not renderer losses.

Audio duration is synthesized contact/tail duration, not the unchanged mechanical
reservation (`performedDuration`). Classification counts below include audible
primary + reinforcement HDD events.

| MIDI | HDD primary | RF planned / audible ART | mean ART ms | choke/retrigger | PRIMARY played A/B | dropped A/B |
|---|---:|---:|---:|---:|---:|---:|
| There There | 4447 | 0 / 0 | 72.54 | 0 | 8324 / 8324 | 181 / 181 |
| 2+2=5 | 1569 | 3 / 3 | 67.68 | 0 | 6034 / 6034 | 380 / 380 |
| Sail to the Moon | 464 | 0 / 0 | 67.28 | 0 | 1955 / 1955 | 2 / 2 |
| Let Down | 2021 | 0 / 0 | 75.78 | 0 | 6645 / 6645 | 645 / 645 |
| Jigsaw Falling Into Place | 2076 | 0 / 0 | 66.40 | 0 | 7270 / 7270 | 191 / 191 |
| No Surprises | 740 | 20 / 14 | 81.67 | 0 | 5114 / 5114 | 318 / 318 |
| Creep | 1266 | 6 / 6 | 84.66 | 0 | 4525 / 4525 | 0 / 0 |

| MIDI | SOFT_TAP | MEDIUM_HIT | HARD_HIT | DOUBLE_TAP | BUZZ_ROLL |
|---|---:|---:|---:|---:|---:|
| There There | 527 | 3064 | 490 | 366 | 0 |
| 2+2=5 | 523 | 343 | 326 | 308 | 72 |
| Sail to the Moon | 123 | 221 | 66 | 48 | 6 |
| Let Down | 326 | 910 | 336 | 449 | 0 |
| Jigsaw Falling Into Place | 839 | 405 | 443 | 387 | 2 |
| No Surprises | 226 | 72 | 262 | 194 | 0 |
| Creep | 268 | 399 | 446 | 159 | 0 |

All RAW gestures average 8.98 ms (sample-grid rounding), with zero choke/retrigger.
All 29 planned HDD reinforcements are audible in RAW. ARTICULATED plays 23 of them:
six No Surprises extras were suppressed to preserve an active primary tail.
No normal hit is suppressed. All benchmark passages had enough per-actuator space
after density adaptation that no primary retrigger was required. A separate dense
synthetic test forces retriggers, verifying monophony and the fade endpoint.
BUZZ_ROLL is used sparingly; it is not injected into There There without matching
source semantics.

## There There, first 30 seconds

File: `0071-09-radiohead_2003-there_there-[k] (2).mid`.
There are **390 requested percussion source events; all 390 are allocated**.
The first 30 seconds of acoustic output contain **387 contacts**. Three end-boundary
events contact after 30 seconds because of the existing 80 ms park/settle phase;
they are not dropped. No HDD reinforcement is selected for this intro.

The melodic track `Ed [Toms]` has GM program 117 and is semantically PERCUSSION,
but is **not** channel-10 drums. Its notes 42/52/57 use LOW/MID/HIGH chassis bands,
not GM hat/cymbal meanings and not equal-tempered tom synthesis.

| Source | Note | requested <30 s | contact <30 s | articulation / band | base chassis Hz | contacts by HDD |
|---|---:|---:|---:|---|---:|---|
| Ed [Toms] | 42 | 60 | 60 | MEDIUM_HIT / LOW | 226.2 | hdd_vcm-3: 60 |
| Ed [Toms] | 52 | 120 | 119 | MEDIUM_HIT / MID | 290.0 | hdd_vcm-1: 60, hdd_vcm-3: 59 |
| Ed [Toms] | 57 | 60 | 59 | MEDIUM_HIT / HIGH | 353.8 | hdd_vcm-1: 59 |
| Phil Steway | 35 | 45 | 44 | HARD_HIT / GM | 210.0 | hdd_vcm-2: 44 |
| Phil Steway | 37 | 30 | 30 | DOUBLE_TAP / GM | 340.0 | hdd_vcm-2: 30 |
| Phil Steway | 44 | 60 | 60 | SOFT_TAP / GM | 420.0 | hdd_vcm-2: 15, hdd_vcm-4: 45 |
| Phil Steway | 45 | 15 | 15 | MEDIUM_HIT / GM | 290.0 | hdd_vcm-2: 15 |

Contacts across the interchangeable pool: HDD1 **119**, HDD2 **104**, HDD3 **119**,
HDD4 **45**. Existing GM destination preferences still allow reassignment to any
free HDD; no articulation is permanently tied to an actuator. The same kick is
successfully routed across all four HDDs in the pool test. The intro itself routes
pitch 52 across HDD1/HDD3 and pedal hat across HDD2/HDD4.

Two 30-second A/B WAVs and a reproduction of the previous generic HDD audio are
available in `/tmp/hdd-articulation/`:
`there-there-raw.wav`, `there-there-articulated.wav`, `there-there-legacy.wav`.
All use the same orchestra onsets and unboosted PCM mix (app Master Volume is
applied during playback). The WAVs verify different synthesized waveforms; the
perceptual result should still be judged by listening. This does not prove the
same timbres are achievable on a physical drive.

## Tests and limitations

**372 backend tests passed without skips; 70 frontend tests passed; explicit
TypeScript typecheck and production build passed.** No lint script is configured.
Existing Orchestra tests emit React act warnings, and Starlette emits its existing
deprecation warning. `git diff --check` is clean.

Thirteen new backend tests cover complete mapping, stick vs kick waveforms, dry
hat, melodic contour, velocity shape, density, monophony, 6 ms release, primary
priority, raw bypass, deterministic Python/NumPy equivalence, inherited
reinforcement articulation, full event immutability, interchangeable four-HDD
pool and live mode changes without reallocating/stopping. One new frontend test
checks the RAW/ARTICULATED selector and unchanged device configuration.

This is a physically motivated **software approximation**, not a calibrated
actuator model. Travel, contact forces, chassis modes, noise and roll capability
are not measured. Cross-drive variability, limit-stop wear and power/current
limits cannot be validated here. Future hardware measurements may require narrower
articulation capabilities. This task adds no Arduino/GPIO/serial integration.

## Changed files

New HDD work:
- `host/playback/hdd_articulation.py` — classifier, parameters, synthesis primitives.
- `host/playback/virtual.py` — semantic acoustic metadata, mono lanes, shared render paths, mode.
- `host/playback/engine.py` — mode-only asynchronous audio refresh without allocation.
- `host/tests/test_hdd_articulation.py` — 13 backend tests.
- `web/src/components/VirtualOrchestra.tsx` — small A/B selector; Master Volume preserved.
- `web/src/components/VirtualOrchestra.test.tsx` — selector test.
- `web/src/types.ts` — optional validated `hddMode`.
- `scripts/benchmark_hdd_articulation.py` — reproducible seven-song audit and audio exports.
- `benchmarks/hdd-articulation.json` — full results and timestamped intro trace.
- `benchmarks/HDD_ARTICULATION_REPORT.md` — this report.

Existing feature restoration from `migrate`:
- `host/playback/allocator.py`, `capabilities.py`, `orchestra.py`, `performance.py`,
  `reinforcement.py`, `tray.py`, plus the corresponding existing virtual/engine integration.
- `host/tests/test_auto_arranger.py`, `test_dvd_experiment.py`, `test_idle_reinforcement.py`, `test_tray.py`.
- `web/src/App.test.tsx`, `components/ArrangementEditor.tsx`, `components/PianoRoll.tsx`,
  and corresponding existing Orchestra/types integration.

Local MIDI files were copied from the old nested MIDI directory into the active
flat checkout only where missing; they remain ignored. No MIDI was added to Git.
No changes were committed.
