# Tonal articulation — Creep source audit and A/B benchmark

## 1. Scope and pipeline

The allocator policy, semantic classification, duplicate normalization and existing mechanical sustain pass remain unchanged. The allocator adds only a timed expression sidecar after making its normal decisions. PerformanceEvent source start/duration/velocity, actual assignment/timing and physical reservations stay unchanged.

`MidiSource.expression_events → PerformancePlan.expression → Tonal Articulation Resolver → device-specific acoustic decision → Virtual renderer`

No guitar samples, amplifier/cabinet effects, new humanization, generated strums, serial commands or Arduino/ESP32 implementation.

## 2. What is actually in Creep MIDI

File: `0002-02-radiohead_1993-creep-[k] (2).mid`. Source file duration 237.377 s. GM program numbers below are zero based (add 1 for GM chart numbering).

| Track | Semantic role | GM program(s) | Notes | Velocity min–max | Duration min / median / p90 / max ms | Distinct-onset overlaps |
|---|---|---|---:|---|---|---:|
| 1 · Guitar 1 | GUITAR | 26 | 942 | 42–96 | 144.02 / 633.15 / 1937.49 / 5198.35 | 367 |
| 2 · Guitar Dub | GUITAR | 26 | 942 | 18–63 | 144.02 / 633.15 / 1937.49 / 5198.35 | 367 |
| 3 · Bass | BASS | 32 | 428 | 73–92 | 149.46 / 312.50 / 1127.71 / 5203.79 | 0 |
| 4 · Voice | VOCAL | 65 | 243 | 91–110 | 8.15 / 307.06 / 959.24 / 3894.01 | 0 |
| 5 · Guitar 2 | GUITAR | 30 | 1592 | 20–107 | 8.15 / 62.50 / 62.50 / 5335.58 | 2 |
| 6 · Guitar 2 Dub | GUITAR | 28 | 1592 | 20–107 | 8.15 / 62.50 / 62.50 / 7807.04 | 2 |
| 7 · Piano | KEYS | 0 | 54 | 87–87 | 307.06 / 959.24 / 2589.67 / 5198.35 | 0 |

Guitar 1 program 26 is electric jazz guitar; Guitar 2 program 30 is distortion guitar; Guitar 2 Dub program 28 is muted guitar. These are MIDI source identities, not samples reproduced by the mechanical renderer.

Guitar 1/Guitar Dub have 113 chord candidate groups each; Guitar 2/Guitar 2 Dub have 768 each. Within the 50 ms audit windows, **all chord onset spreads are 0 ms**. There are no source strums detected in Creep. Guitar 1 does contain overlap between distinct successive onsets (367 cases), while Guitar 2 has only two such cases. Simultaneous members of a chord are not counted as legato transitions.

Guitar 2 is overwhelmingly short: p10/median/p90 are all about 62.50 ms. Guitar 1 has much longer notes: median 633.15 ms, p90 1937.49 ms. Source key-off timing matters; these two parts must not use the same rectangular gate or a universal long release.

### Controllers and note-off

| Track | Pitchwheel messages / nonzero | CC7 messages / value range | CC1 | CC11 | CC64 |
|---|---:|---|---:|---:|---:|
| Guitar 1 | 1 / 0 | 1 / 84–84 | 1 | 0 | 0 |
| Guitar Dub | 1 / 0 | 1 / 78–78 | 0 | 0 | 0 |
| Bass | 13 / 9 | 32 / 53–102 | 0 | 0 | 0 |
| Voice | 1 / 0 | 1 / 114–114 | 1 | 0 | 0 |
| Guitar 2 | 15 / 10 | 130 / 0–104 | 1 | 0 | 0 |
| Guitar 2 Dub | 15 / 10 | 1 / 107–107 | 0 | 0 | 0 |
| Piano | 1 / 0 | 1 / 102–102 | 0 | 0 | 0 |

Creep contains **47 pitchwheel messages, 29 nonzero**, across the raw source including duplicate tracks. Guitar 1 and Voice only initialize bend at zero; moving bends occur in Bass and Guitar 2 (+ its dub). Each tonal track has one program change, not a mid-song series of instrument changes. RPN 0 (CC101/100 and data-entry CC6/38) sets bend range to **12 semitones**. Treating these values as the usual default ±2 would be incorrect.

CC7 has 169 messages in the whole source, including percussion: Bass has 32 and Guitar 2 has 130. CC1 appears three times, with small values 9/12/10 on Guitar 1/Voice/Guitar 2. **No CC64, CC11, channel aftertouch or polyphonic aftertouch occurs in Creep.** The implementation supports these in synthetic tests; it does not invent pedal or expression events in this song.

Each tonal track has a matching NOTE_OFF message count for its NOTE_ON count. The parser already preserves key-off times as source duration. NOTE_ON velocity zero is not used for key-off in these tracks. Other initial messages include CC121 reset, CC123 all notes off, CC10 pan and RPN setup. CC10 remains captured as metadata; device pan remains the existing user-controlled mix parameter. Other unused controllers are retained as metadata but do not acquire arbitrary new meanings.

### Duplicate normalization

Existing normalization collapses Guitar 1 + Guitar Dub (median dub offset 21.74 ms, confidence 0.9811) and Guitar 2 + Guitar 2 Dub (10.87 ms, confidence 1.0). Raw tonal events: 5793; logical tonal events: 3259; 2534 duplicate events removed. These offsets are **between duplicate tracks**, not a strum inside the primary chord. Normalization keeps the primary track onsets and controllers; it does not blend the discarded dub’s velocity or controller stream.

## 3. What the previous pipeline lost

The note parser did not expose controllers/bends to the PerformancePlan. Source note timing and velocity survived allocation, but the previous FDD/DVD tone waveform did not use velocity, CC7/11, pitch bend or modulation. Stepper audio had a hard gate with no natural decay/release; VHS had a fixed 25 ms attack and abrupt key-off. Duplicate normalization and allocator rescue delays are existing musical/mechanical decisions, not new renderer quantization.

## 4. Articulation added by this implementation

- PLUCKED for Guitar/Bass/Piano-style programs or matching semantic roles: brief attack, velocity-dependent transient/brightness, exponential decay toward a retained mechanical body, short release.
- CONTINUOUS for other tonal/lead families: higher sustain, smoother attack and shorter attack on source legato transitions.
- Attack depends on velocity and performed duration; short source notes (≤120 ms) have release capped to 16% of their length. Dense source onsets cap release to 18 ms. No timestamps are moved.
- Velocity affects intensity, brightness, transient, attack, decay and body, rather than only gain.
- FDD: sharper step impulses, 900 Hz mechanical coloration, base attack 4 ms/release 45 ms. DVD sled: smoother impulses, 1300 Hz coloration, base attack 8 ms/release 70 ms. VHS: continuous mechanical whine, base attack 18 ms/release 95 ms. Values are procedural model assumptions, not measurements.
- CC7 and CC11 enter the gain curve once, alongside note velocity and existing device/master gain. Pressure has a restrained intensity effect. Pitch bend retains RPN range and changes frequency with 5 ms ramps and continuous phase, not chromatic retriggers. CC1 enables only small bounded vibrato; there is no automatic vibrato when CC1 is absent.
- Program changes select the next note’s family. A held note is not switched to another instrument midway.

## 5. Release, pedal, retrigger and reinforcement

Audio tails do not extend physical reservations. Per-actuator audio scheduling clips the previous tail at the next normal note and fades its endpoint over 6 ms; the next note has its own attack. Legato is interpreted with a softer attack and this brief transition, not unbounded overlapping voices. The source CC64 state at key-off can hold the audible gate until pedal-up (or file end); a new PRIMARY on that actuator always preempts it. This does not add sustain reservations to the allocator. The transport includes the final audible tail, so the song-end stop does not erase it.

Reinforcement inherits the source family, pitch/expression curves and performance character; target-device attack is adapted for its own actuator. Extras never interrupt an active PRIMARY gate/tail, never change normal density context, and cannot extend beyond their planned reservation. Thus some optional extras are suppressed in ARTICULATED. This is an acoustic-only change, not a drop of normal notes.

## 6. Source timing / strums

All eight benchmark runs assert exact equality of source onset, duration and velocity against parsed normalized spans, exact normal-event equality between A/B plans, and acoustic onset equality against actualStart. A separate synthetic 0/11/23/36 ms chord verifies its source spread survives parsing, allocation metadata and rendering. A simultaneous chord does not acquire new onset delays. STRUM_LIKE metadata requires at least three overlapping chord pitches with monotonic onset direction in a ≤50 ms window; it never creates a strum.

Creep still has the existing 47 ARPEGGIATED allocator rescue events, with 62.5 ms delay. Their timestamps are identical in both modes. There are no new arranger delays or source-onset rounding changes (PCM has its normal 22050 Hz sample grid).

## 7. Eight-song benchmark

Configuration: 4 FDD / 4 DVD / VHS / 4 HDD / 2 trays; idle reinforcement ON; identical allocator settings. No song-specific tuning. BEFORE/AFTER metrics below mean TONAL RAW / TONAL ARTICULATED. All normal assignments and statistics match; the older renderer is additionally exported for listening.

| MIDI | PRIMARY played A=B | dropped A=B | drop rate | ART mean attack / decay / release ms | legato | staccato | strum groups |
|---|---:|---:|---:|---|---:|---:|---:|
| Creep | 4525 | 0 | 0.00% | 5.01 / 50.88 / 35.01 | 0 | 1525 | 0 |
| No Surprises | 5114 | 318 | 5.85% | 5.62 / 113.44 / 55.12 | 33 | 99 | 0 |
| Let Down | 6645 | 645 | 8.85% | 5.61 / 162.27 / 56.61 | 1 | 0 | 1 |
| Jigsaw Falling Into Place | 7270 | 191 | 2.56% | 5.38 / 109.86 / 54.88 | 9 | 119 | 0 |
| Nude | 2757 | 62 | 2.20% | 4.62 / 140.49 / 50.72 | 14 | 68 | 2 |
| Street Spirit | 3598 | 24 | 0.66% | 4.93 / 132.86 / 50.07 | 1 | 0 | 0 |
| 2+2=5 | 6034 | 380 | 5.92% | 5.58 / 73.68 / 42.32 | 3 | 764 | 0 |
| There There | 8324 | 181 | 2.13% | 5.04 / 139.34 / 51.99 | 4 | 138 | 0 |

RAW has mean attack 1 ms, decay 0 and release 2 ms. ART values above are requested articulation parameters; actual tails can be shorter because of retrigger. Tests/benchmark also assert that no normal audio gate becomes shorter than its performed duration (except at most two PCM samples of rounding).

| MIDI | Pitchwheel / nonzero | CC7 / CC11 / CC64 / CC1 messages | Retriggers RAW / ART | Tonal RF planned | Tonal RF audible RAW / ART |
|---|---|---|---|---:|---|
| Creep | 47 / 29 | 169 / 0 / 0 / 3 | 47 / 474 | 1850 | 1716 / 1489 |
| No Surprises | 2332 / 2161 | 1325 / 0 / 0 / 0 | 277 / 3290 | 791 | 613 / 411 |
| Let Down | 2319 / 1770 | 1066 / 0 / 0 / 0 | 669 / 4135 | 920 | 787 / 637 |
| Jigsaw Falling Into Place | 1526 / 1249 | 110 / 0 / 0 / 0 | 1436 / 4326 | 1218 | 1137 / 851 |
| Nude | 52 / 33 | 101 / 0 / 0 / 1 | 73 / 1244 | 413 | 314 / 239 |
| Street Spirit | 2928 / 2857 | 991 / 0 / 0 / 0 | 2 / 133 | 2609 | 2558 / 2504 |
| 2+2=5 | 5240 / 4187 | 381 / 0 / 0 / 66 | 606 / 2642 | 1200 | 1081 / 854 |
| There There | 3144 / 2673 | 1263 / 0 / 0 / 0 | 78 / 2480 | 1386 | 1264 / 1049 |

Controller counts refer to raw MIDI (including dub tracks); rendered expression follows the surviving logical primary tracks. This suite has no CC64/CC11 messages; their support is verified with synthetic fixtures.

Aggregate: **44,267 PRIMARY played and 1,801 dropped in both modes**. The drops are existing allocator losses. Normal event identities, assigned devices, played pitches, actual starts/durations, velocity and outcomes are equal, not just aggregate counters.

### Creep BEFORE/AFTER in detail

3259 normal tonal events: 3016 PLUCKED, 243 CONTINUOUS. Both modes classify 1525 staccato source notes, zero tonal legato transitions and zero strum groups. There is no evidence to justify adding legato or strumming in this source. RAW attack/decay/release 1/0/2 ms; ART averages 5.01/50.88/35.01 ms. Retriggers: 47 RAW versus 474 ART, because normal tails now reach subsequent notes and are safely cut; these are **not** extra note starts or losses.

Tonal reinforcement: 1850 planned; 1716 audible in RAW and 1489 in ART. ART omits 361 extras (RAW 134) to protect normal sound. The underlying reinforcement plan is identical.

Full-song WAVs use the same unboosted device mix, not loudness normalization. Measured stereo RMS: raw 0.003472, articulated 0.002872, legacy 0.004391. The new decay and correct MIDI CC7 lower average energy; a more articulated sound is not claimed to be louder. App Master Volume remains available. These metrics and distinct waveforms verify synthesis changes, not subjective listening quality.

Audio files:
- `/tmp/tonal-articulation/creep-legacy.wav` — previous generic gated tonal synth; source velocity/controllers/bends ignored as before.
- `/tmp/tonal-articulation/creep-raw.wav` — simple gate, but source velocity/controllers/bends preserved.
- `/tmp/tonal-articulation/creep-articulated.wav` — source expression plus new mechanical articulation.

## 8. UI and tests

ORCHESTRA → **Tonal sound** → TONAL RAW / TONAL ARTICULATED. Default ARTICULATED; saved with existing presets. Switching replaces the cached audio asynchronously without reallocating or resetting the transport. Browser verification switched Creep during PLAYING at 46–51 s with the clock continuing. Active device cards expose optional Tonal articulation debug metadata (source duration, velocity, role, profile, timings, legato/staccato/strum/pedal, gain). Creep is left loaded and stopped in ARTICULATED.

**390 backend tests passed, 71 frontend tests passed, explicit typecheck and production build passed.** No lint script configured. Existing React act warnings and Starlette deprecation warning remain. `git diff --check` clean. Eighteen new backend tests cover note-off tail, RAW gate, plucked/continuous profile, velocity timbre, staccato, retained long-note body, mono retrigger, source microtiming, legato context, CC64/preemption/final tail, CC7/11, RPN bend/phase, modulation, device profiles, reinforcement inheritance/priority, Python/NumPy parity, conductor-track expression and live mode switching. New frontend test verifies the selector preserves HDD mode and routing.

## 9. Changed files

- `host/midi_source.py` — public timed MIDI expression extraction; note parser unchanged.
- `host/playback/performance.py` — expression sidecar and JSON serialization.
- `host/playback/allocator.py` — capture sidecar after allocation (two lines); policy unchanged.
- `host/playback/tonal_articulation.py` — resolver, expression curves, source context, mechanical waveform articulation.
- `host/playback/virtual.py` — attach decisions, per-actuator tails/retriggers, RAW mode, final transport tail.
- `host/playback/engine.py` — live audio-only mode changes and active debug metadata.
- `host/tests/test_tonal_articulation.py` — expression/timing/voice invariants.
- `web/src/components/VirtualOrchestra.tsx` — selector and optional active debug details.
- `web/src/components/VirtualOrchestra.test.tsx` — selector test.
- `web/src/types.ts` — mode/debug types.
- `scripts/benchmark_tonal_articulation.py` — source audit, eight-song benchmark and full-song WAV exports.
- `benchmarks/tonal-articulation.json` — complete source controller trace, per-track distributions, benchmark metrics and Creep acoustic event metadata.
- `benchmarks/TONAL_ARTICULATION_REPORT.md` — this report.

## 10. Hardware limits and remaining constraints

This is a procedural host-audio model, not calibrated physical expression. Actual travel/torque/drive constraints, achievable bends, VCM/stepper slew and chassis tails require hardware measurement. No new hardware capability is asserted. Existing allocator note-duration caps and arpeggiation remain audible; this renderer does not restore notes/durations the allocator could not physically reserve. CC64 tails can be preempted by later primary notes on the same actuator. Unsupported controller meanings stay metadata; there are no external resonators, samples, amp/reverb simulations or automatic humanization.

Changes are **not committed**. MIDI and WAVs are not added to Git.
