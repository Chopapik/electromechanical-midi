# DVD Lead + Low FDD — experimental arrangement

Third independent AUTO preset, selected in Arrangement · PerformancePlan.
Balanced remains the startup default. Preset selection is session-only and uses
Application.set_preset: confirmed STOP / virtual audio cancellation precedes
replanning; failure retains the previous preset and plan. Playback never resumes
automatically. STRICT_TRACKS retains its explicit track routing.

## Actual path and decisions

runtime.arranger.arrange → normalization / analysis → allocator.allocate →
hardware_arranger.allocate_hardware → physical validation → optional UNISON →
runtime.compiler.compile_plan → the same timeline for REAL and VIRTUAL.
There is no additional allocator or playback engine.

DVD1–3 receive a strong score preference for all tonal parts, with additional
musical salience, sustain and same-track/channel continuity bonuses. Availability,
transition time, pitch-dependent acceleration and timing conflicts are evaluated
by the existing hardware model. No lane is permanently assigned to melody, bass
or harmony. Optional sustains crossing an upcoming melody/bass attack yield space
rather than reserve a DVD. Existing priority-based DVD sustain competition and
lead/bass protection remain in effect. Three monophonic lanes give at most three
simultaneous DVD voices. Their current pitchRatio calibration and continuous
rotation profiles remain unchanged.

FDD candidates try exactly one octave below the source pitch plus any explicit
device/manual transpose. If this is outside the configured profile range, the
original candidate pitch is evaluated. Neither candidate is clamped or folded a
second time. A note requiring two octaves of folding can consequently be omitted
when no DVD is free. No global FDD range is enlarged. The current 200 Hz lower
musical bound is a working profile choice, not a precise measured acoustic limit.

PerformanceEvent.note/start/duration/velocity/track/channel retain MIDI provenance;
played_note/played_hz/actual_start/actual_duration record execution. Selection.lowFdd
records the explicit octave decision and range fallback. DVD retain their original
register (plus explicit user/device transpose), without automatic folding in this
preset. MIDI files, tempo and classification are unchanged.

The existing FDD cost model evaluates steps = performed Hz / pitchRatio × gate,
head phase, projected reversals, recent density, continuous activity, rests and
long sustain. Costs use the fddQuality* policy settings already available. Only
less important expensive candidates are omitted; phrase entries, moving motifs,
melody and bass keep fallback eligibility. Unlike FDD Quality, this preset does
not apply blanket gate shortening or subsequent FDD sustain extension. Important
source durations survive unless an existing physical/timing constraint prevents
execution. Mechanical head position is estimated, not measured.

UNISON remains a post-pass over idle FDD, at the performed low pitch and identical
onset/gate. Source salience, source and target movement costs, 12% default duty
budget, full chronology and future primary quality checks must pass. It never
changes primary allocations, and no fixed pairs are introduced.

## Diagnostics and comparison

UI displays DVD/FDD note counts, octave-lowered FDD notes, performed original-pitch
fallbacks due to range, estimated FDD steps/reversals (including UNISON), omissions,
shortened notes and UNISON use. The report also contains individual frequencies,
role counts/durations and per-device physical counters.

Run `.venv/bin/python scripts/compare_dvd_lead.py --baseline reports/dvd-lead-baseline.json`.
The baseline fingerprints were generated from commit ba2681b for Balanced and
FDD Quality. The script verifies exact events/reinforcements/compiled commands,
combined physical chronology, unchanged primary decisions with UNISON disabled,
and at most three DVD voices. Reports contain melody/bass and harmony retention,
additional important losses relative to Balanced, frequency summaries, DVD duty,
drops and movement estimates. Salience/classification are heuristics, not an
acoustic judgment of preserved melody or chords.

Reduced steps do not prove better sound. Existing octave folding in Balanced
already puts FDD into 200–410 Hz, so the new octave preference often cannot lower
its performed frequency further. Much of the reduction comes from DVD takeover
and fewer harmony voices. Physical listening is still needed, especially for
Thinking About You, which already sounded good, and Creep/2+2=5 where some
important events can be lost. No physical motor tests or flashing are performed.

## Verification and deployment

Backend: 525 tests pass. Frontend: 47 tests pass. TypeScript/Vite build passes
(existing large-bundle warning). Docker was rebuilt and restarted; healthcheck
passes and the served frontend contains the third preset. A separate offline
Application in the container generates this preset with playback stopped.
No firmware, BLE protocol, GPIO, calibration or motor-control changes; reflashing
is unnecessary.

## Verified A/B/C results

A = Balanced, B = FDD Quality, C = DVD Lead + Low FDD. Estimates include UNISON. Exact A/B fingerprints match commit ba2681b on all six songs.

| Song | FDD steps A / B / C | Reversals A / B / C | FDD notes A / B / C | DVD notes A / B / C | C lowered / range fallback | C additional melody/bass losses |
|---|---|---|---|---|---|---|
| Thinking About You | 197089 / 120045 / 153796 | 2736 / 1665 / 2134 | 2899 / 2838 / 2152 | 1877 / 1912 / 1854 | 3 / 2149 | 0 |
| Creep (Acoustic) | 316734 / 166475 / 190648 | 4397 / 2310 / 2645 | 2836 / 2268 / 1657 | 744 / 1312 / 2031 | 24 / 1633 | 64 |
| Where I End and You Begin | 215466 / 73178 / 61428 | 2990 / 1013 / 850 | 3862 / 3575 / 981 | 327 / 610 / 3082 | 368 / 613 | 0 |
| Jigsaw Falling Into Place | 236819 / 182072 / 136879 | 3287 / 2527 / 1900 | 3201 / 2536 / 1357 | 1581 / 2076 / 2413 | 152 / 1205 | 0 |
| Airbag | 174833 / 69265 / 60614 | 2427 / 961 / 839 | 2980 / 2431 / 578 | 473 / 1018 / 2549 | 289 / 289 | 0 |
| 2+2=5 | 155654 / 108150 / 102573 | 2160 / 1500 / 1422 | 2918 / 2382 / 1184 | 1012 / 1565 / 2638 | 70 / 1114 | 2 |

All C plans remain physically feasible in the configured model. UNISON on/off keeps primary events identical. Peak DVD polyphony never exceeds three. Melody/bass loss counts refer to IDs played in Balanced and missing in C, not just differences in aggregate counts. Creep labels most notes as bass, so the 64 losses are classified bass events; all classified lead events remain. In 2+2=5, two additional previously played lead events are lost despite the same aggregate lead count. Many harmony/motif events are also lost; the JSON separately lists musicallyImportantLostVsBalanced using the C salience heuristic. This preset is not established as musically better.
