# FDD Quality Adaptive

> Aktualna aplikacja: wybór presetu w **Settings → Aranżacja**; cztery aktywne DVD,
> dwa PC Speakery. Wszystkie presety mają wspólny [limit ataków FDD](fdd-attack-rate.md).
> Tabele benchmarków i liczby testów poniżej są zapisami wersji wskazanej przy
> pomiarze, nie gwarancją bieżących wyników. [Pełny indeks](README.md).

An independent AUTO preset, alongside the six other current choices.
Choose it explicitly in Settings → Aranżacja; startup
and Docker restart retain the existing Balanced default. Selection remains
session-only. Application.set_preset confirms STOP / virtual cancellation before
planning, increments the revision, and never automatically resumes playback.
STRICT_TRACKS still uses explicit track routing.

## Diagnosis before implementation

Canonical available files used:
- `0005-05-radiohead_1993-thinking_about_you.mid`
- `0041-10-radiohead_1997-no_surprises-[k].mid`
- `0032-01-radiohead_1997-airbag-[k].mid`

Raw / normalized counts: 7322 / 7322, 5432 / 5432, 7316 / 7316 respectively.
Normalization is unchanged; these files do not lose note events at this stage.
Quality's global accompaniment gate caps are 132.2, 363.5 and 163.7 ms.
It shortens 1165, 758 and 393 played FDD notes, respectively, before any Adaptive
change. In Airbag all 16 omitted tonal notes have long source gates (2.128–8.469 s),
not short riff gates. No event has FDD_QUALITY_OPTIONAL_COST as its final top-level
drop reason, although some individual candidates are rejected by that policy;
DEVICE_BUSY is often the first reported reason. Inspect candidate diagnostics
as well as aggregate drop reasons. This is why simply lowering a note-selection
threshold cannot recover nonexistent missing short notes in this file.

The JSON comparison contains final source and performed timing, original versus
normalized counts, gate restorations, recovered IDs, roles, per-FDD counts, actual
activity intervals, primary and including-UNISON 0–4 distributions and estimated
mechanical work. Exclusive zero-FDD silence buckets distinguish composition rests,
Quality gate/selection silence, unsuitable FDD material, material on other devices,
and remaining allocation/mechanical conflicts. These overlap-based classifications
are diagnostic estimates; silence can have multiple simultaneous musical causes.
The one-FDD opportunity duration is limited to valuable short recovery candidates
that pass full-lane chronology, not an exhaustive claim about every hypothetical
arrangement. It is reported separately for Quality and Adaptive.

## Algorithm

The actual entry point remains hardware_arranger.allocate_hardware. Adaptive first
uses that same function to build the unchanged FDD Quality reference. A reservation
refinement in the same hardware allocator recovers eligible source notes, then
restores short source gates. There is no second playback engine, different transport
allocator, or synthetic note generator. REAL and VIRTUAL consume compile_plan.

Density is analyzed after duplicate normalization in a moving local bar, updated
every half quarter-note. Tempo segments and time signatures determine seconds and
bar length, including changes within a bar. Features include independent track/channel
parts, note-on rate, median inter-onset gap, short-note fraction and velocity.
Fast coherent lane activity drives adaptation; chord size or a few short strum offsets
cannot activate it alone. The velocity-weighted lane rate and sustained onset density
both must exceed five onsets per quarter-note. Smoothstep feature weights and a
beat-based exponential attack/release (0.75 / 1.5 beats) avoid hard strategy changes.
The level is interpolated for individual source attacks. The thresholds are generic,
with no filename or track-name matching. Musical density is the input; actual available
FDD profiles, timing, phase, reservations and movement costs decide feasibility.

A fully calm analysis returns the existing Quality event/command plan unchanged.
For dynamic passages:
1. Existing primary attacks, pitch choices and DVD events are preserved.
2. Optional UNISON is removed before considering independent voices.
3. Valuable omitted source gates up to 500 ms can recover onto idle FDD, exactly
   at their source onset, without additional delay/arpeggiation. Rhythmic repeats
   receive motif protection even if their pitch does not change. Explicit manual
   transposition/folding settings remain respected. Recovery gates obey the model's
   minimum cycles/floor and the existing hardware authorization/timing constraints.
4. Candidate costs reuse FDD Quality's steps, head phase, reversal, density, rest
   and sustained-activity model. The optional budget grows smoothly by
   `1 + 1.5 * level`; recent usage softly favors less occupied independent lanes.
5. Important short notes (up to 0.75 MIDI quarter-note, capped at 600 ms) can regain
   part of their source gate. They never cross source note-off or a later reservation.
   A small descending set of extension candidates is checked against the complete
   device chronology and movement budget. Existing attacks are never shifted.
6. The plan is revalidated by the existing physical validator. UNISON is reconsidered
   last, and suppressed in dynamic windows. Independent voices take precedence.

No adaptive octave shift is added: existing Quality profile folding is retained.
No frequency, FDD range, DVD pitchRatio, continuous rotation, acceleration, firmware,
BLE protocol, GPIO, watchdog or STOP changes. Existing Quality notes carrying advisory
minimum-cycle warnings remain as in the reference; those hypotheses are not claimed
as newly measured motor limits. New recovery candidates use the conservative model
minimum as an eligibility condition.

## Verification

`reports/fdd-adaptive-baseline.json` records exact event/reinforcement/compiled-command
SHA256 fingerprints from commit 1cee5c0 for all three existing presets and all three
MIDI files. `scripts/compare_fdd_adaptive.py` checks them, physical combined chronology,
UNISON-on/off primary equality and identical DVD primary events. It exports
`reports/fdd-adaptive-comparison.json` with the full interval diagnostics.

Backend: 536 tests pass; 11 new Adaptive tests cover calm/dense/strum fragments,
smoothing, MIDI tempo/meter changes, natural rests, recovery across idle FDD,
source note-off including delayed attacks, conflicts, DVD preservation, duplicate
normalization, independent voices versus UNISON, determinism and safe REAL/VIRTUAL
switching. Frontend: 49 tests pass, including selection and diagnostic presentation.
TypeScript/Vite build passes (existing large-bundle warning).

Docker is rebuilt with `docker compose up -d --build orchestra`. Verify healthy,
served current frontend and offline generation through Application.set_preset.
There is no flashing or physical motor test, and firmware upload is unnecessary.

## Limits

Density and motif importance are heuristics. Activity, steps and reversals are planned
estimates, with no measured physical head position or acoustic noise measurement.
Recovering no omitted short notes in Airbag is a valid result: its short source riffs
were already represented. Improvement there comes from recovering source gate time,
not inventing attacks or taking sustained parts away from DVD. Whether the change
sounds sufficiently fuller requires listening. Other MIDI editions may differ.

## Verified comparison

| MIDI | FDD notes Quality / Adaptive | Primary activity seconds | Steps including UNISON | Reversals including UNISON | Restored gates | Recovered attacks |
|---|---|---|---|---|---|---|
| Thinking About You | 2838 / 2838 | 374.583 / 374.583 | 120045 / 120045 | 1665 / 1665 | 0 | 0 |
| No Surprises | 2211 / 2211 | 529.435 / 529.435 | 159183 / 159183 | 2208 / 2208 | 0 | 0 |
| Airbag | 2431 / 2431 | 246.105 / 258.502 | 69265 / 72319 | 961 / 1003 | 118 | 0 |

| MIDI | Active independent FDD 0 / 1 / 2 / 3 / 4 — Quality | Adaptive |
|---|---|---|
| Thinking About You | 37.55% / 1.70% / 1.05% / 1.92% / 57.77% | 37.55% / 1.70% / 1.05% / 1.92% / 57.77% |
| No Surprises | 22.68% / 15.36% / 7.92% / 16.87% / 37.18% | 22.68% / 15.36% / 7.92% / 16.87% / 37.18% |
| Airbag | 41.31% / 35.65% / 18.33% / 3.88% / 0.83% | 40.37% / 34.28% / 19.64% / 4.74% / 0.97% |

All three previous presets match their original fingerprints on all three files. All Adaptive lanes, including reinforcements, pass full chronology. UNISON does not change primary decisions. No previously accepted primary event is lost; all DVD primary events are identical. Thinking About You and No Surprises have identical event/compiled-command fingerprints to Quality.

Airbag gains 12.397 seconds of primary FDD gate time (+5.0%). Its zero-primary-FDD share falls from 41.31% to 40.37%; time with 2–4 independent FDD grows from 23.04% to 25.35%. Total FDD steps rise by 4.4%. UNISON falls from 11 to 7 events. No new attacks are recovered in these source files; the Airbag improvement is 118 restored source gates. This is a modest planned improvement, not a claim of verified better sound.

## Changed files

- `host/playback/fdd_adaptive.py`: tempo/meter density map, smoothing and interval diagnostics.
- `host/playback/hardware_arranger.py`: Adaptive reference, recovery and gate refinement using the existing physical allocator/validator.
- `host/playback/mechanical_arrangement.py`: independent-voice priority over dynamic UNISON.
- `host/playback/orchestra.py`, `host/runtime/application.py`: new preset validation and existing safe switching.
- `host/playback/performance.py`: Adaptive report.
- `web/src/runtime.ts`, `web/src/components/ArrangementPreview.tsx`: selector, activity/density timeline and recovery diagnostics.
- `host/tests/test_fdd_adaptive.py`, `web/src/App.test.tsx`, `web/src/components/ArrangementPreview.test.tsx`: unit/integration/UI coverage.
- `scripts/compare_fdd_adaptive.py`, `reports/fdd-adaptive-baseline.json`, `reports/fdd-adaptive-comparison.json`: reproducible comparisons and regression fingerprints.
- `docs/fdd-quality-adaptive.md`: algorithm, diagnosis, evidence and limits.

Final Docker container is healthy. The served bundle is `index-DtXfZyOA.js` and contains the selector and `meanActiveFdd` diagnostic. An offline Application in the container successfully selects Adaptive, remains stopped and has no transport attached. No flashing or motor tests.
