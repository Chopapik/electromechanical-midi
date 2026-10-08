# Hardware-first planning (ESP32, offline implementation)

## Pipeline and scope

Previously the allocator used preview profiles, and physical commands came from
`VirtualOrchestra.events`. The ESP32 path now uses:

MIDI → existing duplicate normalization / semantic analysis → physical allocator
→ HardwareProfile evaluation → PerformancePlan → physical schedule → lane mapping
→ existing Serial/BLE parser → ESP32 execution.

`hardware_arranger.py` is the conservative physical branch of `allocator.allocate`;
it shares semantic analysis, policy, manual pins, articulation and PerformancePlan.
Virtual-only configurations keep the existing allocator and PCM renderer. Uno's
original controller and protocol remain unchanged. No new physics audio renderer
was implemented. The preview is a historical/demo approximation.

The ESP32 runtime selects physical planning when any configured instance is `real`
or `hybrid`. A disconnected controller yields `NO_DEVICE`, not fictitious voices.
On connection the plan is rebuilt. Even the old single-track ESP32 runtime cannot
bypass physical profiles. Only actual command-capable v2 lanes are eligible.

The physical branch is intentionally conservative: it does not steal an active
voice through an actuator transition, or synthesize unsupported tray/free-stepper
profiles. It may drop more notes than the ideal preview. A delay must fit the
existing role-specific micro-delay/arpeggio window. Source semantics, duplicate
normalization and the existing sustain pass are retained. Final performed
lengths are checked again after articulation.

## Sources of data

- `config/hardware-profiles/theoretical.json`: reference/theoretical priors.
- `config/hardware-profiles/instances.json`: declared physical inventory and
  per-instance calibration/configuration, keyed by stable physical lane.
- `docs/research/orkiestra-model-teoretyczny.md`: supplied research report.
- `hardware_profiles_generated.h`: **generated** ESP32 execution defaults.

Generate/check firmware defaults without hardware:

```sh
.venv/bin/python scripts/generate_hardware_profiles.py
.venv/bin/python scripts/generate_hardware_profiles.py --check
```

Never edit the generated header directly. Docker includes `config/` so the host
uses the same JSON data in a container. SPI remains 1 MHz and pin mapping is
unchanged.

Every quantity stores `value`, `unit`, `source`, `evidenceType`, `confidence`,
and optional `uncertainty`.

| Evidence | Meaning |
| --- | --- |
| FACT | Existing code/configuration or cited reference specification; not automatically a fact about our motor |
| DERIVED | Formula or range assembled from stated measurements/configuration |
| HYPOTHESIS | Planning prior to be tested |
| MEASURED | Measurement/working limit of this particular physical instance |

Confidence is `HIGH`, `MEDIUM`, `LOW`, or `UNKNOWN`. Reference motor examples are
explicitly named as references. A null requires UNKNOWN confidence. Numeric
values must be finite; ranges/positive parameters are validated.

Effective profile: theory → saved instance quantities → explicit device
`hardwareOverrides` (also accepted as `hardware_overrides`). A measured value is
not replaced by a non-measured guess. An explicit null revokes the value rather
than silently falling back. An explicit newer measured override can replace an
older measurement. Calibration of DVD1 is never propagated to DVD2–4.

**UNKNOWN ≠ SAFE. UNKNOWN ≠ UNLIMITED.** Unknown current, excursion, impact or
thermal ratings remain UNKNOWN in evaluation and telemetry. Nominal existing
drive can be planned with UNKNOWN load, visibly labelled; aggressive operation
cannot be authorized by missing safety data. These profiles are not proof of
physical safety. They do not invent current limits or output power ratings.

## Inventory and calibration overrides

The saved declaration currently contains FDD1, SLED1 and HDD1, based on the
previous bring-up. It does **not** claim the controller detects connected
peripherals: ESP32 `enabled=1` reports firmware state, not the presence of a
motor. Other lanes must be explicitly declared by the operator. Disabled
instances keep their ordinal: disabling FDD1 cannot remap FDD2 to its wiring.

Override an orchestra's physical inventory in JSON/API:

```json
{"hardware":{"inventory":{"fdd:1":true,"sled:1":true,"hdd:1":true}}}
```

This explicit inventory replaces the saved declaration. Absent entries are
absent, not implicitly present. Virtual-only instances never receive hardware
commands. Mute/solo also filter physical allocation.

On an existing DVD device, add quantities without replacing its legacy preview
profile or changing the arrangement schema:

```json
{
  "hardwareOverrides": {
    "travelSteps": {
      "value": 140,
      "unit": "steps",
      "evidenceType": "MEASURED",
      "confidence": "MEDIUM",
      "source": "DVD1 working software travel; manually placed at start"
    },
    "pitchRatio": {
      "value": 1.0,
      "evidenceType": "MEASURED",
      "confidence": "HIGH",
      "source": "replace with your measurement record before claiming measured"
    }
  }
}
```

The second entry is a **schema example**, not a measurement of our DVD. Until
measured, the shipped pitchRatio remains HYPOTHESIS/LOW. Old arrangement JSON
without these fields keeps valid defaults. HDD instances can declare
`hardwareRole: "HDD_PERCUSSION"` or `"HDD_TONAL"`; the physical actuator remains
`type: "HDD_VCM"`. This does not add a new virtual instrument.

## Device models

### FDD

The report supplies preferred 100–300 Hz, stable prior 65–330 Hz, musical
exploration 65–500 Hz, reference minimum STEP interval 3 ms (~333.333 steps/s),
reversal prior 18 ms (4–18), travel prior 60 (40–75). Reversal overhead is
`max(0, reversalIntervalMs - 1000 / fStep)`, not disk settling on each note.

FDD1 retains the existing 72-away-step guard, 5 ms DIR timing, and calibrated
upper comfort endpoint 410 Hz. Its lower 130 Hz is **retained configuration**,
not a measured musical minimum. The aggregate [130,410] range is DERIVED;
410 Hz itself was measured 38/40. The 5 Hz mechanical minimum is not substituted
for a musical lower bound. The existing calibration overrides the 3 ms reference
prior for this instance. Other FDD instances use the reference execution floor.

TRACK0 stays the physical source of truth. Firmware still uses only awaySteps,
not precise head position, negative position, delta compensation or POS_LOST.
DIR toward TRACK0 remains HIGH, away remains LOW. The STEP timestamp still comes
from the physical latch edge. Direction-ready time and the execution STEP floor
must both expire before a pulse. Startup HOME and watchdog remain intact.

Host travel/reversal rates (`fStep/travel`, `fStep/(2*travel)`) and the projected
away counter are approximate planning diagnostics, never position feedback.
The actual firmware counters and TRACK0 come from STATUS.

### DVD SLED

Only DVD1 has measured working **software** travel 140 and bring-up stable
250–300 steps/s. DVD2–4 have travel UNKNOWN (`soft_max=-1` in firmware) and PLAY
is rejected until configured. The 140 counter is not an absolute physical
position; boot zero requires manual placement at the starting end.

Audio frequency and step rate are separate (`stepRate = audioFrequency /
pitchRatio`). Default ratio 1 is LOW confidence; alternate priors .5, .25, 2
remain in the data. Reference Minebea specs are not our motor's ratings.

The host evaluates signed transition time `abs(target-current)/acceleration`
and braking distance `v²/(2a)`. Firmware executes the signed ramp (prior 5000
steps/s²), reverses the target before the limit using braking distance plus a
small two-command guard, retains the Q8–Q23/full-step phase sequence, and clamps
at the software boundary as a final guard. STOP de-energizes immediately and
retains the relative counter. DIR still sets the requested direction; velocity
changes gradually. Delayed loop servicing never produces catch-up phase bursts.

### HDD percussion

The planner uses priors 5 continuous hits/s, 10 burst hits/s, a 500 ms window,
and 200 ms nominal start-to-start. These are **not safe current/thermal ratings**.
The existing ESP32 drive baseline is retained: 40 ms reset/park, 40 ms settle,
4 ms strike. The theoretical 1 ms pulse prior is stored separately and does
not silently change the physical HIT command. Measured `strikeMs` overrides can
configure that instance; increasing the baseline pulse without known safety data
is considered aggressive and is not authorized.

Readiness separates mechanical, thermal-budget and impact-budget times. The
latter two are UNKNOWN until calibrated. Event diagnostics expose planned HIT,
RESET, SETTLE, CONTACT/STRIKE and READY phases. CONTACT is a label for the strike
command, not a detected mechanical contact. The old bridge state machine and
HIT/STOP commands remain operational.

### HDD tonal

There is a separate profile/role/state-continuity scoring branch: exploration
100–1500 Hz, preferred 200–800, stable UNKNOWN, transition=max(3/f,10 ms) after
a frequency change. The risk score checks odd square-wave harmonics against
reference resonance candidates. Unknown avoidBands never become hardcoded
measured exclusions; measured avoidBands can block candidates.

**Physical HDD tonal execution is not enabled.** The current firmware only has
percussion drive, without centering, excursion sensing/current limiting or a
validated tonal oscillator. These notes carry `PHYSICAL_UNKNOWN` and
`HDD_TONAL_EXECUTOR_UNAVAILABLE`; no HIT command is substituted for a tonal note.
This is deliberate architecture for later measured work, not a claim that a
safe tonal driver now exists.

VHS retains existing protocol range/drive; physical limits remain UNKNOWN.
Tray and unprofiled actuator families are excluded from the new physical
arranger pending suitable profiles. Their existing firmware commands and the
legacy preview remain unchanged.

## Evaluation and telemetry

Each physical candidate reports TIMING, QUALITY, PHYSICAL_LOAD independently as
PASS / DEGRADED / UNKNOWN / BLOCKED, plus `authorized`, `qualityReasons`,
`readyAt`, transition/braking/reversal estimates and harmonic risk.

Duration minimum is `max(floorMs, 1000 * minCycles / audioFrequency)`:
FDD 20 ms / 4 cycles; DVD 30 ms / 4; HDD tonal 20 ms / 4. Preferred duration,
change rate, preferred/stable range and transient cost affect quality. A short
but executable note can be DEGRADED instead of categorically rejected.

Rejected/unauthorized candidates cannot be selected. Eligible candidates must
fit the role's allowed delay, then are ordered by quality, transition cost,
braking/reversal cost, physical confidence, stable device id. Selection is
deterministic. The final sustain pass cannot reserve overlapping primary notes
or override mechanical/budget readiness.

Reasons include NO_DEVICE, PROFILE_UNKNOWN, TRAVEL_LIMIT_UNKNOWN,
PITCH_RATIO_UNKNOWN, STEP_INTERVAL_LIMIT, OUTSIDE_MUSICAL_RANGE,
TIMING_CONFLICT, DEVICE_BUSY, BURST_WINDOW, CONTINUOUS_HIT_RATE,
PHYSICAL_UNKNOWN, PHYSICAL_LIMIT, HDD_TONAL_EXECUTOR_UNAVAILABLE.
Quality reasons include NOTE_TOO_SHORT, SHORTER_THAN_PREFERRED,
OUTSIDE_PREFERRED_RANGE, OUTSIDE_STABLE_RANGE, ACCELERATION_LIMIT,
TRAVEL_REVERSAL, NOTE_CHANGE_RATE, HARMONIC_RESONANCE_CANDIDATE.

`PerformanceEvent.hardware` contains the selected evaluation and all candidate
evaluations. `PerformancePlan.hardware`, its report, and snapshot
`hardwarePlanning` expose effective metadata, lane mapping, projected end states
and per-device requestedNotes, acceptedNotes, playedNotes, droppedNotes,
degradedNotes, dropReasons, transitions/reversals/travelReversals,
accelerationLimited, tooShort, outsidePreferredRange, outsideStableRange and
physicalUnknown.

**Counters are labelled PLANNED, not measured playback.** requestedNotes and
droppedNotes count per-device candidate assessments/denials (one MIDI note may
be evaluated on several devices). dropReasons can have several reasons for one
denial. accepted/played describe selected command-plan events; no acoustic or
movement sensor verifies them. Reversals/travelReversals count projected travel reversals (not sensor-confirmed
mechanical reversals). Source-level drops remain the existing plan
report totals. Projected states are end-of-plan estimates, not live sensors.

STATUS adds FDD reversal/profile, DVD signed rate/target and LOW position
confidence/ramp, HDD logical state/readiness and UNKNOWN safety. STATUS remains
explicitly requested, never generated each tick. Lines/whole transactions are
bounded by the existing BLE packet/Serial queue sizes, covered by native tests.

New firmware advertises `hardware_profiles=1`. Runtime sends bounded FDD/SLED/HDD PROFILE
execution parameters while stopped (HDD uses reset/settle/strike milliseconds); an old firmware cannot silently execute a
physical plan assuming new ramps/timing overrides it does not have. No protocol parser duplication, BLE
callback hardware execution, auto-flash or automatic motor tests were added.

Optional reinforcement is filtered against real inventory/profiles and primary
reservations. Unknown-travel/unsafe/non-tonal dubs are removed. DVD dubs currently
only use terminal free gaps, because changing its software trajectory must not
invalidate a later primary event. FDD dubs reserve a direction-settling margin
before a following primary. Uncalibrated tray accents are removed on this path.

## First physical tests — checklist ONLY, not executed

1. Check wiring, manual DVD start position and declared inventory before enabling
   any lane. Keep uncalibrated DVD2–4 disabled.
2. Read STATUS; check protocol/profile capability, FDD DIR polarity and TRACK0
   raw/active. Confirm STOP and watchdog with a controlled low-rate test.
3. FDD1: verify existing 130–410 range, reversal timing and TRACK0 return at
   several frequencies; record failures per position/orientation.
4. DVD1: low-rate ramp, signed reversal and early braking; check actual travel
   against the software estimate, then measure pitchRatio. Do not infer motor
   temperature/current safety from successful movement.
5. HDD1: verify the unchanged 4 ms strike, reset/settle readiness and enforced
   hit-rate scheduling; measure peak current, temperature and impact before
   attempting stronger drive.
6. Record each instance's measured ranges/timing/travel in metadata overrides.
   Do not copy DVD1 measurements to other motors.
7. Compare a sparse MIDI and a dense arrangement with per-note reasons, measured
   STEP intervals and observed movement. Planned playedNotes alone are not proof.
8. HDD tonal requires separate electrical/centering/excursion characterization
   and an execution design before any oscillator test; it remains blocked here.

No steps above were performed during implementation. No USB/BLE was opened,
firmware was not flashed, motors were not commanded, and the running application
was not restarted because that could auto-connect/home hardware.

### Individual DVD1 resonance calibration

`config/hardware-profiles/instances.json`, `SLED:1.quantities.allowedBandsHz`,
records a physical sweep from 50 to 500 Hz in 10 Hz increments using the existing
Sled ramps and automatic reversal, with the existing `pitchRatio=1`.
Only these inclusive bands are qualified: **50–120, 180–190, 270–300,
340–470 Hz**. All intervening gaps and frequencies outside those bands are
unqualified and rejected. This measurement applies only to DVD1.

The values describe the physical STEP rate in Hz (equal to PLAY Hz during the
sweep). Host and ESP32 both compare `PLAY Hz / pitchRatio` with these bands;
changing the acoustic pitch mapping therefore cannot bypass the resonance
restriction. `musicalStepRate` and `stableStepRate` record the outer measured
envelope, 50–470 steps/s; the holes remain forbidden by `allowedBandsHz`.
The earlier 250–300 Hz bring-up observation is superseded for DVD1.

The hardware arranger searches only octave equivalents of the original MIDI
pitch. In automatic fold mode, A3/220 Hz can use A4/440 Hz. If no permitted
octave exists within the remaining constraints, another instrument is tried
before DROP. Manual routing without octave folding and final reinforcement
validation enforce the same measured bands. Measured bands cannot be erased or
widened by runtime profile overrides.

`scripts/generate_hardware_profiles.py` emits the per-instance whitelist in
`firmware/controller/include/hardware_profiles_generated.h`. Direct
`SLED 1 PLAY` commands outside the whitelist return `ERR VALUE`; STOP first
when testing successive values, because a rejected PLAY does not cancel an
already running valid note. DVD2–4 have no new whitelist. Travel limit 140,
phase sequence, acceleration, braking and reversal code are unchanged.
