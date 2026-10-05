# TONAL EXTREME v2 — Creep, final PCM

## Implementation and exact mapping

The UI has four independent choices: RAW, ARTICULATED, EXTREME v1 and EXTREME v2.
Normal ART is not retuned. v2 only changes PLUCKED final audio; CONTINUOUS stays
unchanged. No changes to parsing, semantic classification, normalization,
allocator, PerformancePlan, routing, reinforcement policy, MIDI durations or onset.

Let v = velocity/127, x = clamp((sourceDuration−0.080)/0.720, 0, 1),
b = x²(3−2x). Every parameter below interpolates with b between short and long.
Source ≤80 ms uses the short endpoint; source ≥800 ms uses the long endpoint.
Intermediate notes smoothly blend, without track/song hardcoding.

| Parameter | Short endpoint | Long endpoint |
|---|---|---|
| attack | (15−10v) ms | (70−30v) ms |
| decay | (180−80v) ms | (550−200v) ms |
| sustain | 5+5v % | 5+7v % |
| release base | (150+150v) ms | (700+400v) ms |

FDD release is base×0.92 (138–276 ms short / 644–1012 ms long).
DVD release is base×1.0 (150–300 ms short / 700–1100 ms long).
DVD attack is base×1.08. Both attacks are capped at 35% of performed gate, so
source-long but physically shortened notes still develop an audible attack.
Decay uses the existing EXTREME exp(−t/(decay/4)) shape; release also uses
exp(−t/(release/4)), plus the existing 6 ms terminal fade/choke.
Source note length, allocated gate, and physical busy time are never extended.

### Velocity and mechanical families

- brightness = 0.02+2v⁴, changes pulse sharpness/resonance energy;
- existing transient coefficient = 0.02+4.2v⁴;
- extra impact coefficient = 0.03+3.2v⁴;
- body coefficient = 0.04+0.28v²;
- harmonic coefficient = 0.02+0.25v⁴;
- existing intensity mapping v^0.65 and MIDI CC curves remain intact.

FDD: extra inharmonic 2300/3710/5270 Hz impact modes with weights 1/.55/.30,
1.8 ms exponential half-width centered at attack, stronger high harmonics.
DVD: 1250/2170/3190 Hz modes, 4.5 ms half-width, transient and impact×0.45,
lower harmonic, longer smoother tail. Existing transient also remains at the
attack peak with 3 ms half-width. Deterministic procedural synthesis, no sample,
strum, humanization, reverb, amp, cabinet or distortion.
No additional reversal knock has been restored.

At velocity 40/90/120, transient coefficient is approximately
0.061/1.079/3.368: intentionally soft low velocity and brutal high velocity.
This is a sonic diagnostic, not a measurement-calibrated hardware model.

## Render method and invariants

Exact input: `0002-02-radiohead_1993-creep-[k] (2).mid`.
Full source timeline for every solo and full render, shared fixed gain×1, no
per-file peak/RMS normalization, no limiter, zero clipped samples.
Guitar 2 starts at 61.304 s, so the first minute would not contain it.
Solo: full allocation and per-actuator scheduling happen before filtering;
only normal tones of that guitar remain. No HDD/VHS/bass/other guitar/extras.
Filtering does not return other tracks' physical reservations to the solo voice.
Full mix retains ordinary orchestra and enabled idle reinforcement.
Both use the identical WavePreview._plan / _render_numpy / _write implementation.
Metrics are computed by reading final stereo PCM16 at 22050 Hz from the WAVs.

Frozen full plan (including extras) is unchanged after every render; normal
IDs, onsets, gates and normal gate coverage are checked. PRIMARY:
**4525 requested / 4525 played / 0 dropped** for all four modes.
Audio-only release can suppress an optional extra through existing rules; it
cannot reserve physical time or interrupt a normal note. New primary truncates
previous tail with existing 6 ms fade. One actuator never stacks release voices.

Regression: parameter mapping and float samples of every scheduled legacy tone
are bit-identical against the implementation at commit 9f01049:
RAW 4975 tones, ART 4748, EXTREME v1 4624. Different tone counts include optional
extras already suppressed differently by the legacy envelope durations.

## Final waveform comparisons

All ratios use RMS of the first member of the pair. Gain-removed residual fits
one least-squares scalar; substantial residual demonstrates waveform change.

| Signal / comparison | RMS difference | Gain-removed residual | PCM correlation |
| Guitar 1 raw_vs_articulated | 45.71% | 20.06% | 0.9435 |
| Guitar 1 raw_vs_extreme-v1 | 82.50% | 65.60% | 0.5919 |
| Guitar 1 raw_vs_extreme-v2 | 120.06% | 114.99% | 0.4847 |
| Guitar 1 v1_vs_v2 | 150.49% | 146.48% | 0.3975 |
| Guitar 2 raw_vs_articulated | 47.60% | 21.79% | 0.9333 |
| Guitar 2 raw_vs_extreme-v1 | 85.21% | 72.90% | 0.6013 |
| Guitar 2 raw_vs_extreme-v2 | 129.44% | 119.79% | 0.3866 |
| Guitar 2 v1_vs_v2 | 149.49% | 136.34% | 0.2676 |
| Full mix v1_vs_v2 | 35.97% | 35.87% | 0.9381 |

## Representative real Creep notes

RMS and peaks below are actual decoded PCM. dB times use the first post-peak
5 ms block RMS crossing, measured from the peak block. They include mechanical
ripple, so they are not fitted ADSR constants. `—` means no crossing before the
scheduled/choked end, or no sustain interval after attack+decay and before gate.
Audible duration is the last sample >−60 dB relative to that note's own peak;
this analysis threshold does not normalize or change the WAV.

### long: Guitar 1, 1:209, source 5198.354 ms

| Mode | Attack ms | Peak | RMS 0–50 | RMS 50–200 | RMS 200–500 | Sustain RMS | Release RMS | To −6 dB ms | To −20 dB ms | Audible ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| raw | 1.000000 | 0.034089 | 0.004275 | 0.004396 | 0.000000 | 0.004390 | 0.002335 | 4.988662 | — | 191.836735 |
| articulated | 3.555906 | 0.029969 | 0.003685 | 0.002200 | 0.000277 | 0.002018 | 0.000654 | 4.988662 | 189.569161 | 229.659864 |
| extreme-v1 | 29.724409 | 0.032014 | 0.005770 | 0.001917 | 0.000349 | — | 0.000329 | 9.977324 | 29.931973 | 619.365079 |
| extreme-v2 | 49.448819 | 0.060152 | 0.006962 | 0.005053 | 0.000856 | — | 0.000555 | 9.977324 | 159.637188 | 1062.630385 |

### short: Guitar 2, 5:63, source 62.500 ms

| Mode | Attack ms | Peak | RMS 0–50 | RMS 50–200 | RMS 200–500 | Sustain RMS | Release RMS | To −6 dB ms | To −20 dB ms | Audible ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| raw | 1.000000 | 0.028840 | 0.003753 | 0.003885 | 0.000000 | 0.003870 | 0.000252 | 4.988662 | — | 70.430839 |
| articulated | 4.141732 | 0.024354 | 0.002613 | 0.001357 | 0.000000 | 0.001693 | 0.000241 | 4.988662 | 54.875283 | 77.006803 |
| extreme-v1 | 19.341940 | 0.027558 | 0.002785 | 0.001467 | 0.000000 | — | 0.000578 | 19.954649 | 59.863946 | 80.680272 |
| extreme-v2 | 10.590551 | 0.023682 | 0.003160 | 0.001253 | 0.000000 | — | 0.000705 | 9.977324 | — | 81.043084 |

The long Guitar 1 source is 5.198 s but its existing performed gate is 190 ms.
v1 release 437 ms versus v2 896 ms; audible duration ~619 versus ~1063 ms.
The short Guitar 2 source is 62.5 ms, performed gate 69.52 ms. v2 nominal release
is 198.85 ms, but the next primary already arrives ~81.5 ms after onset, choking
the tail. Actual duration is therefore ~81 ms, not a second.
Even this short note develops v2 attack at ~10 ms instead of v1 ~15 ms peak.

The results prove a substantial change in final PCM, surviving the full mix.
Whether v2 is musically better remains an audition choice; normal ART remains
untouched. No downstream physical loudspeaker/system DSP claim is made.

## Files for audition

All paths under `/tmp/tonal-extreme-v2/`:

- /tmp/tonal-extreme-v2/creep-guitar1-raw.wav
- /tmp/tonal-extreme-v2/creep-guitar1-articulated.wav
- /tmp/tonal-extreme-v2/creep-guitar1-extreme-v1.wav
- /tmp/tonal-extreme-v2/creep-guitar1-extreme-v2.wav
- /tmp/tonal-extreme-v2/creep-guitar2-raw.wav
- /tmp/tonal-extreme-v2/creep-guitar2-articulated.wav
- /tmp/tonal-extreme-v2/creep-guitar2-extreme-v1.wav
- /tmp/tonal-extreme-v2/creep-guitar2-extreme-v2.wav
- /tmp/tonal-extreme-v2/creep-full-extreme-v1.wav
- /tmp/tonal-extreme-v2/creep-full-extreme-v2.wav

Regenerate: `.venv/bin/python scripts/diagnose_tonal_extreme_v2.py`.
Detailed sample statistics: `benchmarks/tonal-extreme-v2-diagnostic.json`.
Tests: full backend 396 PASS; frontend 71 PASS; typecheck/build PASS.
Final focused tonal suite 23 PASS after strengthening physical-state checks.
Known pre-existing Starlette deprecation and React act warnings remain.

Changed files: host/playback/tonal_articulation.py, host/playback/virtual.py,
host/tests/test_tonal_articulation.py, web/src/types.ts,
web/src/components/VirtualOrchestra.tsx, web/src/components/VirtualOrchestra.test.tsx,
scripts/diagnose_tonal_extreme_v2.py, benchmarks/tonal-extreme-v2-diagnostic.json,
this report and waveform PNG. No commit.
