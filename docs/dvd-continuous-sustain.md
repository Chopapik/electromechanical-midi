# DVD Continuous Sustain

> Aktualna aplikacja: wybór presetu w **Settings → Aranżacja**; cztery aktywne DVD,
> dwa PC Speakery. Wszystkie presety mają wspólny [limit ataków FDD](fdd-attack-rate.md).
> Tabele benchmarków i liczby testów poniżej są zapisami wersji wskazanej przy
> pomiarze, nie gwarancją bieżących wyników. [Pełny indeks](README.md).

Optional policy: `dvdContinuousSustain` (library default false, local device
configuration true), `dvdDynamicAware` (true), `dvdMaxBridgeMs` (200).
The 200 ms ceiling is experimental, not a calibrated optimum.

The small `dvd_sustain` articulation pass runs after Source Continuity and after
reinforcement/UNISON reservations are known. Each proposed extension is checked
against the complete final mechanical chronology before committing it. Failed
extensions leave the primary unchanged, rather than causing new drops. Adaptive
FDD plans run the pass only after their final reservations, too.

Only continuous-rotation DVD profiles participate. NOTE_ON, pitch, routing and
source duration stay fixed. The previous performed NOTE_OFF meets the following
NOTE_ON exactly. The compiler suppresses touching DVD STOP with a 1 ns tolerance
for floating-point arithmetic; actual release gaps still produce STOP. Firmware
is unchanged: Sled::play updates targetStepRate and its existing acceleration
ramp follows the new frequency. User ALL STOP and firmware watchdog are unchanged.
REAL and VIRTUAL consume the same compiled timeline.

A bridge requires the same logical track and channel, a changed pitch, no
explicit articulation, no stolen/shortened gate, no intervening source attack,
and no occupied reinforcement interval. Local unique note-on intervals within
two beats establish cadence (at least three attacks). Dynamic-aware mode requires
cadence <= 400 ms and <= 1.05 beats: fast quarter-note riffs qualify as well as
subdivisions. A pair must be <= 1.5 local median intervals apart; source rests
may occupy at most 55% of that interval or 0.6 beats, whichever is smaller.
Notes longer than two beats are preserved. Repeated pitches keep rearticulation.
Disabling dynamic-awareness removes the fast-cadence requirement, but preserves
all phrase, reservation and repeat safeguards.

This describes the dynamic pass shared by AUTO physical plans. Instrument Roles
and its paired variants, as well as Universal, additionally use the [background/grace sustain pass](instrument-roles.md#stronger-dvd-background-sustain),
with an experimental 350 ms ceiling and guarded repeated-note/handoff bridges.
STRICT_TRACKS uses only FDD. Routing across devices or independent parts can
still produce gaps. No new motor driver is introduced.

Run ` .venv/bin/python scripts/compare_dvd_sustain.py` to regenerate
`reports/dvd-sustain-comparison.json` for Bodysnatchers and Every Breath You Take.
Both runs use the current enabled inventory, balanced Mechanical-Aware policy,
Source Continuity and UNISON; only the sustain switch differs. The benchmark
asserts primary allocation equality, unchanged non-DVD events and all optional
reservations, zero overlaps, and complete valid hardware chronology. STOP counts
and work/silence/longest continuous duration come from ExecutionTimeline,
including optional tones. Work and between-note silence sum across DVD motors;
longest continuous duration refers to one motor, excluding leading/trailing idle.

Software checks do not establish thermal safety. Measure motor/driver temperature
and motor current and mechanical behavior on physical hardware before judging
continuous duty. In the current setup, excessive DVD motor heating was observed
at 5 V. The currently considered 3.3 V is the **motor supply at DRV8833 VM**,
not just logic voltage, and remains a provisional working value requiring those
measurements, not a verified safe limit. See the
[ESP32 wiring and supply notes](esp32-orchestra.md#gpio-wiring).
The report explicitly records the longest uninterrupted run for each comparison.
