# Unpitched MIDI effects

AUTO arrangement separates explicit GM noise programs from harmonic voices in
every preset (including Balanced / Mechanical-Aware and FDD Quality Adaptive).
STRICT_TRACKS also refuses to turn these triggers into FDD tones.

Recognized programs, **zero based**: 119 Reverse Cymbal, 120 Guitar Fret Noise,
121 Breath Noise, 122 Seashore, 125 Helicopter, 126 Applause, 127 Gunshot.
The original MIDI stays unchanged. Source keys remain visible in the plan with
role `unpitched_effect`, outcome `DROPPED`, reason
`UNPITCHED_EFFECT_UNSUPPORTED`, and no assigned device. They reserve no voice,
create no reinforcement and contribute nothing to phrase/density decisions.
The report counts them separately in `unpitchedEffects`; tonal retention does
not count these omissions as missing melodic notes. Overall dropped totals
still include every explicitly omitted source event for auditability.

The current hardware has no matching noise generator. A sustained seashore or
reverse cymbal is therefore omitted rather than represented as a motor note
or an unrelated HDD hit. PC Speaker FX remains a **pitched ornament voice**;
Synth Effects, Synth Lead, melodic percussion, Bird Tweet and Telephone Ring
are not blanket-filtered by this rule. Ordinary MIDI drum-channel hits retain
their existing HDD routing.

Program selection is channel-wide, follows changes across tracks, and is
latched at each NOTE_ON, including same-tick message ordering. Bank selection
takes effect at program change. Only default bank 0/0 is interpreted as GM;
unknown sound banks and manufacturer-specific part remapping are not guessed.
Noise-bearing tracks cannot be collapsed into tonal duplicate groups just
because their trigger notes match a melodic part.

Run the reproducible software comparison with:

```sh
.venv/bin/python scripts/compare_unpitched_effects.py /path/to/Avicii_Levels.mid
```

The script compares identical inventory/policy with noise semantics disabled
and enabled, checks compiled execution commands and deterministic results,
and also checks available Every Breath You Take / Counting Stars control files.
It neither opens hardware nor copies the supplied MIDI into the repository.

## Recorded comparison

`reports/levels-unpitched-effects.json` records the supplied Levels file and
its SHA-256. With the same default Balanced / Mechanical-Aware inventory:

| Levels metric | Before | After |
| --- | ---: | ---: |
| Compiled tones originating from GM noise | 80 | 0 |
| Played tonal notes, excluding noise triggers | 3310 | 3312 |
| Dropped tonal notes, excluding noise triggers | 40 | 38 |
| Played percussion hits | 1050 | 1050 |
| Overlapping device reservations | 0 | 0 |

The 261.626 Hz event at 34.285680 s and 130.813 Hz events at 40.476150 s
and 41.904720 s are now explicitly omitted. All 581 noise triggers are
accounted for, including the 500-note Breath Noise layer previously hidden
by tonal duplicate normalization. No previously played tonal note is lost
in this Levels comparison.

Every Breath You Take has no recognized noise programs and produces an
identical compiled timeline. Counting Stars loses 14 spurious noise tones;
its greedy allocator also changes some late accompaniment choices: tonal
drops become 166 instead of 165 (three previously retained notes are lost,
two previously dropped notes are recovered). All device reservations remain
non-overlapping. This is reported explicitly; removing a competing source
does not guarantee globally optimal allocation by the existing allocator.
