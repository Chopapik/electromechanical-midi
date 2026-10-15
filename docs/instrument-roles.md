# FDD Riffs + DVD Tło

Select **Settings → Aranżacja → Preset aranżacji → FDD Riffs + DVD Tło**.
The internal preset ID is `instrument_roles`. Balanced remains the default.
Switching stops playback and rebuilds the common REAL/VIRTUAL timeline.

The existing physical allocator receives stronger musical preferences:

- FDD favors short notes and frequent changes of pitch.
- DVD favors held notes and stable background parts.
- The main PC Speaker keeps the detected vocal/lead pool; PC Speaker FX
  keeps the existing pitched ornament pool. Noise effects stay omitted.
- HDD percussion uses the same independent pool, priorities and timing.

Local context follows non-overlapping voices within each track/channel by
matching the closest pitches at successive onsets. A stationary bass or inner
voice therefore does not inherit the motion of a fast upper riff. Notes of
at least 650 ms strongly favor DVD; fast changing phrases
favor FDD, while stable repeated notes around half a second favor DVD.
Short notes below 450 ms generally leave DVD voices available for held parts.
These are initial musical heuristics, not motor safety specifications.

At a shared attack and source pitch, longer background layers get first
access to DVD. Unrelated parts, vocal/FX, percussion and manual rules keep
their existing scheduling positions. When a DVD already sustains that source
pitch for the full duration, the additional layer prefers an FDD attack of at
most 80 ms. Each source event remains independent; it is not merged or removed.
This avoids spending another DVD voice on the shorter duplicate while leaving
space for different background pitches. Existing micro-delay limits still apply.

Preferences apply only among mechanically admissible candidates. If the
preferred family is absent or occupied, the other can play the note. Long
FDD fallbacks receive an attack of at most 400 ms instead of a long hold;
the existing global gate budget may shorten it further. MIDI attacks and
source lengths are retained in the plan; only performed release changes.
Legacy FDD sustain and Source Continuity do not undo these gates in this
preset. DVD retains source sustain, existing continuous-sustain articulation
and the 600 Hz octave-folding ceiling. Optional FDD unison is disabled to
leave voices for independent riffs.

No firmware or transport changes. Existing mechanical checks, frequency
limits, user STOP and watchdog remain in place. The absence of carriage
travel does not establish unlimited thermal duty for DVD motors; continuous
periods are reported for physical verification.

## Software comparison

Reproduce with `.venv/bin/python scripts/compare_instrument_roles.py`.
Full results and MIDI hashes: `reports/instrument-roles.json`.

| Song / metric | Balanced | New preset |
| --- | ---: | ---: |
| Bodysnatchers: longest FDD hold | 7.676 s | 0.173 s |
| Bodysnatchers: dropped tonal notes | 169 | 159 |
| Every Breath You Take: long source notes assigned to DVD | 248 | 280 |
| Every Breath You Take: longest FDD hold | 3.949 s | 0.275 s |
| Every Breath You Take: dropped tonal notes | 0 | 0 |
| Overlapping reservations, either song | 0 | 0 |

Compiled speaker and percussion commands are identical across presets in
both comparisons. In that allocation-refinement comparison (before the stronger
background articulation below), longest planned continuous DVD periods are 11.780 s for
Bodysnatchers (previously 9.994 s) and 13.435 s for Every Breath You Take.
These measurements describe software schedules, not measured motor behavior.

## Background-tail regression

`reports/instrument-roles-refinement.json` compares the previous preset with
this refinement using the same three enabled DVD devices. DVD4 was disabled
when these measurements were recorded. The current registry enables all four;
the historical comparison below still describes three voices.

At 188.570976 s in Bodysnatchers, the shorter 5.708 s Thom guitar layer used
to occupy DVD1–3, while the 11.423 s Ed background became short FDD attacks.
The three Ed notes now hold on DVD1–3 until 199.993568 s. Compiled execution
commands cover the previously missing tail around 3:14–3:20.

After 2:00, silence of all DVDs while at least one long accompaniment note
exists in the source decreases from 16.333 s to 12.756 s. This is an aggregate
occupancy measure, not a guarantee that every background voice is represented.
Three enabled DVD voices still have finite polyphony. Real source pauses are
preserved, and independent FDD phrases remain short.

## Stronger DVD background sustain

Instrument Roles now adds background legato after retaining all valid bridges
from the previous dynamic articulation. The experimental background ceiling is
`dvdBackgroundMaxBridgeMs: 350`; other presets retain `dvdMaxBridgeMs: 200`.
`dvdContinuousSustain: false` disables both passes.

Within the same MIDI track/channel, DVD may connect unaccented repeated pitches,
slow held phrases and voice handoffs on an allocated monophonic lane. Intervening
attacks in the participating source voices still interrupt the phrase; activity
in an unrelated upper riff does not. No cross-track bridging is introduced.
The source gate must occupy at least 40% of the onset interval, and a filled
source gap cannot exceed 350 ms, 90% of the local beat, or 60% of the interval.
Explicit articulation, shortened/stolen gates, accented repeats, long rests,
reinforcement reservations and the full mechanical chronology can veto legato.

Only performed NOTE_OFF changes. Onsets, pitches, device assignments, drops,
FDD, percussion and speaker commands are unchanged. Both outputs consume the
same compiled timeline; the existing firmware changes target Hz without STOP.

Reproduce with `.venv/bin/python scripts/compare_dvd_background_sustain.py`.
Results: `reports/dvd-background-sustain.json`. Both columns use the same refined
Instrument Roles allocation with three enabled DVD devices at measurement time;
only the DVD articulation differs. The current registry enables DVD4 as well.

| Metric | Previous dynamic sustain | Background sustain |
| --- | ---: | ---: |
| Bodysnatchers: compiled DVD STOPs | 775 | 499 |
| Bodysnatchers: longest continuous DVD run | 11.780 s | 17.494 s |
| Bodysnatchers: dropped notes | 159 | 159 |
| Every Breath You Take: compiled DVD STOPs | 430 | 212 |
| Every Breath You Take: longest continuous DVD run | 13.435 s | 28.814 s |
| Every Breath You Take: dropped notes | 0 | 0 |
| Overlapping reservations, either song | 0 | 0 |

Work/silence metrics sum across DVD actuators, while the longest run is for one
actuator. These longer continuous periods require physical thermal verification;
the software comparison does not establish safe unlimited motor duty.
