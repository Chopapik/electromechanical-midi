# Paired FDD riffs with DVD background

Settings → Aranżacja → Preset aranżacji exposes two experimental variants:

- **FDD Riffs + DVD Tło · Pary Unisono** (`instrument_roles_unison`).
- **FDD Riffs + DVD Tło · Pary Dwugłos** (`instrument_roles_duet`).

The physical pairs are always FDD1+FDD2 and FDD3+FDD4. Each pair follows one
source MIDI track/channel. Unison plays one selected source note on both
members with the same pitch, attack, gate and velocity; there is no echo.
Duet selects two distinct notes from the same MIDI part when available, using
nearby pitches for voice leading. It creates no harmony notes. A single-line
part falls back to unison. Two different source notes that fold to the same
performed pitch do not count as a duet.

The existing Instrument Roles allocator first schedules the orchestra. A
small FDD-only revoicing pass then selects from FDD accompaniment notes and
unallocated accompaniment, leaving assigned DVD, main/FX speaker and
percussion notes alone. It retains the completed DVD background sustain.
Source durations, pitches and note-on times remain in the plan. FDD performed
gates stay within 400 ms, or 80 ms when a DVD covers the original note. A gate
can end earlier to leave room for the next riff attack; neither echo nor late
arpeggiation is added.

Selection considers upcoming note-on activity over 750 ms. Existing owners
have priority at their attacks; an imminent pickup within 120 ms can reserve
the pair rather than causing a brief switch to another instrument. Longer
rests allow another active part to take over. The other pair represents a
different part. Strummed chord attacks within 15 ms can share a duet; each
keeps its original note-on time. Physical gates and manual reservations can
still prevent a new attack.

Two pairs represent **at most two independent accompaniment parts at once**.
Unison halves the independent FDD note capacity; duet can retain two source
notes per part. If four instruments play at once, some notes are intentionally
not selected. The existing non-paired preset remains available for maximum
independent FDD polyphony. If only one eligible part exists, one pair can be
silent; MIDI silence is not replaced with invented notes.

Disabled, muted, solo-excluded or unavailable drives never get copied notes.
A missing pair member leaves a single drive in its original pair; FDD1 never
becomes paired with FDD3. Manual decisions and dedicated lead notes retain
their reservations. Optional idle FDD reinforcement is replaced by the paired
policy; non-FDD reservations remain. Every proposed member must pass the full
physical chronology, including future manual notes. Both outputs consume the
same compiled ExecutionTimeline; firmware, user STOP and watchdog are unchanged.
Non-FDD expression/envelopes, including a DVD copy whose original FDD source
was omitted, are resolved before revoicing and retained by the common compiler.

The plan's `hardware.fddPairs` reports memberships, mode, part changes,
selected primary notes, unison copies and omitted accompaniment notes. Omitted
notes use reason `FDD_PAIR_CAPACITY`; this is a musical reduction, not evidence
of a physical actuator failure.

Run `.venv/bin/python scripts/compare_fdd_pairs.py` for the full-song comparison
on Bodysnatchers and Every Breath You Take. The report `reports/fdd-pairs.json`
includes compiled FDD attacks by drive, selected parts, dropped notes and DVD
continuity. It verifies unchanged non-FDD execution commands, source note-on
times, source pitches, physical chronologies and absence of overlapping
reservations. Software tests do not measure sound quality or motor temperature.

## Initial comparison, four enabled FDD and four DVD

| Song / metric | Existing preset | Pairs Unison | Pairs Duet |
| --- | ---: | ---: | ---: |
| Bodysnatchers: physical FDD attacks | 6137 | 3972 | 3972 |
| Bodysnatchers: distinct selected FDD source notes | 6137 | 1986 | 3064 |
| Bodysnatchers: FDD1 / FDD2 attacks | 1956 / 1586 | 1069 / 1069 | 1069 / 1069 |
| Bodysnatchers: FDD3 / FDD4 attacks | 1490 / 1105 | 917 / 917 | 917 / 917 |
| Bodysnatchers: all omitted source notes | 94 | 4245 | 3167 |
| Bodysnatchers: DVD STOPs | 426 | 426 | 426 |
| Every Breath You Take: physical FDD attacks | 1582 | 2522 | 2512 |
| Every Breath You Take: all omitted source notes | 0 | 321 | 250 |
| Every Breath You Take: DVD STOPs | 284 | 284 | 284 |
| Overlapping reservations, either song | 0 | 0 | 0 |

A unison copy increases the number of physical attacks but does not preserve
an additional source note. Thus the paired presets deliberately omit more
MIDI voices in dense music; they are alternate arrangements, not a way to
retain all four independent FDD voices. On Bodysnatchers, duet retains 1078
more FDD source notes than unison at the same number of physical attacks.
The non-FDD compiled commands are identical in all three variants for both
songs. DVD's longest continuous run remains 17.137 s on Bodysnatchers and
28.814 s on Every Breath You Take; thermal safety is unmeasured.
