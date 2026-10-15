# Common FDD attack-rate reduction

Every runtime arrangement, including every preset and STRICT TRACKS, receives
the same final FDD pass before compilation. `fddMinAttackIntervalMs` defaults
to 120 ms and can only be increased, up to 1000 ms. This is an initial musical
quality setting (at most 8.33 attacks/s per drive), not a measured motor safety
specification. It limits NOTE_ON attacks, including repeated pitches, rather
than the frequency of the audible tone.

The first attack survives; subsequent attacks within the interval are omitted
without moving later attacks or changing source MIDI pitch/timing. Short,
same-pitch repeats in the same source track/channel can extend the retained
gate when their performed release gap is at most 40 ms. Extensions stop before
the next retained note, do not add a hold longer than 400 ms, preserve real
rests and do not merge across explicit articulation or shortened/stolen gates.
Different pitches are reduced without inventing new pitches or queuing delayed
notes. This deliberately simplifies fast ornaments and stutters on FDD.

The pass examines all actual FDD lanes, combining primary notes, optional
reinforcement and paired-unison copies. Matching unison streams receive the
same reduction. Manual and strict-track attacks obey this shared ceiling too.
Other actuators keep their compiled commands and expression, including copies
whose original FDD attack is omitted. FDD expression sidecars follow the new
gates, and reinforcement sidecars are reindexed after removed copies.

The reduced sequence is mechanically reevaluated because deleting notes or
merging gates changes carriage travel and reversal phase. An inadmissible
extension falls back to the original gate; an inadmissible retained attack is
omitted. There is no firmware change. REAL and VIRTUAL share the resulting
ExecutionTimeline; user STOP and watchdog keep their existing behavior.

`articulation.fddAttackRate` reports before/after attacks per physical drive,
suppressed attacks, repeat-coalescing candidates and mechanical vetoes. Omitted
primary attacks remain in the plan with reason `FDD_ATTACK_RATE` and their
original MIDI timing and pitch. Note-loss counts can therefore increase; some
omitted repeated attacks instead contribute to the preceding held note.

## Airbag regression

The supplied MIDI has repeated A notes from 94.285620 s, with attacks as close
as 44.643 ms and source gates around 29.762 ms. The old physical model emitted
a soft `NOTE_CHANGE_RATE` quality penalty; that did not prevent rapid attacks.

Run `.venv/bin/python scripts/compare_fdd_attack_rate.py /path/to/Airbag.mid`.
Add `--all-presets` to benchmark every available preset. The default compares
Balanced and the reported Pairs Duet preset using their complete, unchanged
allocations before/after the shared final pass. Results and MIDI hash:
`reports/fdd-attack-rate-airbag.json`.

| Airbag 1:34–1:40 | Before | After |
| --- | ---: | ---: |
| Pairs Duet: FDD attacks, sum across four drives | 284 | 152 |
| Pairs Duet: intervals below 120 ms | 206 | 0 |
| Pairs Duet: shortest attack interval per drive | 44.643 ms | 133.928 ms |
| Balanced: FDD attacks, sum across four drives | 175 | 105 |
| Balanced: intervals below 120 ms | 108 | 0 |
| Balanced: shortest attack interval per drive | 29.762 ms | 133.928 ms |

Both complete-song comparisons have zero intervals below 120 ms after the pass,
valid full FDD physical chronologies and identical non-FDD execution commands.
Tests also exercise all presets and strict routing, repeated/variable pitches,
real rests, unison copies, source immutability and mechanical extension vetoes.
Listening on the real drives remains necessary to tune the musical threshold.
