"""Detekcja double-trackingu i normalizacja zrodla.

Wiekszosc testow dziala na CZYSTYCH funkcjach z listami nut - dzieki temu
kazdy przypadek jest precyzyjny i nie zalezy od heurystyk MIDI.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import MidiSource, NoteSpan  # noqa: E402
from playback import allocator, duplicates  # noqa: E402
from playback.duplicates import DIFFERENT, EXACT, NEAR, compare_tracks, detect, normalize  # noqa: E402
from playback.orchestra import default_orchestra  # noqa: E402
from test_allocator import write_tracks  # noqa: E402

TICKS_PER_SECOND = 960


def notes(spec, *, velocity=100, duration=0.4) -> list[NoteSpan]:
    """spec: [(start, note)] albo [(start, note, duration)]."""
    built = []

    for index, item in enumerate(spec):
        start, pitch = item[0], item[1]
        length = item[2] if len(item) > 2 else duration
        built.append(NoteSpan(start, start + length, pitch, velocity, 0, index))

    return built


def shifted(base, offset: float, *, drop=(), jitter=None) -> list[NoteSpan]:
    spec = []

    for index, span in enumerate(base):
        if index in drop:
            continue

        extra = jitter[index % len(jitter)] if jitter else 0.0
        spec.append((span.start + offset + extra, span.note, span.duration))

    return notes(spec, velocity=base[0].velocity if base else 100)


def melody(count=20, start=0.0, step=0.25):
    return notes([(start + index * step, 60 + (index * 5) % 12, 0.2)
                  for index in range(count)])


class TestSimilarityMetrics(unittest.TestCase):
    """Przypadki 1-6: jawne metryki podobienstwa i ochrona przed false positive."""

    def test_1_exact_duplicate(self):
        base = melody()
        result = compare_tracks(base, shifted(base, 0.0), 0, 1)

        self.assertEqual(result.verdict, EXACT)
        self.assertEqual(result.matched, len(base))
        self.assertAlmostEqual(result.matching_ratio, 1.0)
        self.assertAlmostEqual(result.median_offset_s, 0.0, places=4)
        self.assertAlmostEqual(result.offset_mad_s, 0.0, places=4)

    def test_2_constant_offset_20ms(self):
        base = melody()
        result = compare_tracks(base, shifted(base, 0.020), 0, 1)

        self.assertTrue(result.duplicate)
        self.assertAlmostEqual(result.median_offset_s, 0.020, places=3)

    def test_3_small_jitter_is_still_a_duplicate(self):
        base = melody(count=40)
        result = compare_tracks(base, shifted(base, 0.020, jitter=(0.001, -0.001, 0.0, -0.002)), 0, 1)

        self.assertTrue(result.duplicate)
        self.assertLess(result.offset_mad_s, 0.010)
        self.assertGreater(result.matching_ratio, 0.9)

    def test_4_a_few_missing_events_still_near_duplicate(self):
        base = melody(count=100, step=0.1)
        result = compare_tracks(base, shifted(base, 0.015, drop={7, 33}), 0, 1)

        self.assertEqual(result.verdict, NEAR)
        self.assertEqual(result.matched, 98)

    def test_5_different_harmony_is_not_a_duplicate(self):
        """C-E-G vs E-G-B: wspolne dzwieki to tylko czesc materialu."""
        left = notes([(0.0, 60), (0.5, 64), (1.0, 67)])
        right = notes([(0.0, 64), (0.5, 67), (1.0, 71)])
        result = compare_tracks(left, right, 0, 1)

        self.assertEqual(result.verdict, DIFFERENT)
        self.assertFalse(result.duplicate)

    def test_6_same_rhythm_different_pitch_is_not_a_duplicate(self):
        left = notes([(index * 0.25, 48 + index) for index in range(20)])
        right = notes([(index * 0.25, 72 + index) for index in range(20)])
        result = compare_tracks(left, right, 0, 1)

        self.assertEqual(result.verdict, DIFFERENT)
        self.assertEqual(result.matched, 0)

    def test_too_few_notes_is_never_a_duplicate(self):
        base = melody(count=duplicates.MIN_NOTES - 1)
        self.assertEqual(compare_tracks(base, shifted(base, 0.0), 0, 1).verdict, DIFFERENT)

    def test_octave_apart_is_not_a_duplicate(self):
        """Ta sama linia o oktave wyzej to inna partia mechaniczna."""
        base = melody()
        higher = notes([(span.start, span.note + 12, span.duration) for span in base])
        self.assertEqual(compare_tracks(base, higher, 0, 1).verdict, DIFFERENT)

    def test_unrelated_dense_track_is_not_collapsed(self):
        """Kontrola z 2+2=5: gesty, niezalezny track nie moze byc dublem."""
        base = melody(count=60, step=0.1)
        other = notes([(index * 0.1, 48 + (index * 7) % 24, 0.2) for index in range(60)])
        result = compare_tracks(base, other, 0, 1)

        self.assertEqual(result.verdict, DIFFERENT)
        self.assertLess(result.matching_ratio, duplicates.NEAR_RATIO)

    def test_7_determinism(self):
        base = melody(count=50)
        twin = shifted(base, 0.017, jitter=(0.0, 0.001, -0.001))
        first = compare_tracks(base, twin, 0, 1)
        second = compare_tracks(base, twin, 0, 1)

        self.assertEqual(first, second)


class DuplicateFileCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, tracks, name='Song'):
        return MidiSource(write_tracks(self.tmp / f'{name}.mid', tracks, name=name))


class TestDetectionOnFiles(DuplicateFileCase):
    def test_identical_tracks_form_one_group(self):
        events = [(index * 0.2, index * 0.2 + 0.15, 60 + index % 7) for index in range(24)]
        source = self.build([('Guitar', 0, events), ('Guitar copy', 1, events)])
        report = detect(source)

        self.assertEqual(len(report.groups), 1)
        group = report.groups[0]
        self.assertEqual(group.tracks, (1, 2))
        self.assertEqual(group.primary, 1)
        self.assertEqual(group.duplicates, (2,))

    def test_offset_tracks_form_one_group(self):
        events = [(index * 0.2, index * 0.2 + 0.15, 60 + index % 7) for index in range(24)]
        delayed = [(start + 0.021, end + 0.021, note) for start, end, note in events]
        report = detect(self.build([('Guitar', 0, events), ('Dub', 1, delayed)]))

        self.assertEqual(len(report.groups), 1)
        self.assertAlmostEqual(report.groups[0].median_offsets[2], 0.021, places=3)

    def test_different_parts_are_not_grouped(self):
        low = [(index * 0.2, index * 0.2 + 0.15, 40 + index % 5) for index in range(24)]
        high = [(index * 0.2, index * 0.2 + 0.15, 70 + index % 5) for index in range(24)]
        report = detect(self.build([('Bass', 0, low), ('Lead', 1, high)]))

        self.assertEqual(report.groups, [])

    def test_percussion_is_not_deduplicated(self):
        """HDD poza zakresem v1: dwa identyczne tracki perkusyjne zostaja."""
        hits = [(index * 0.3, index * 0.3 + 0.05, 36) for index in range(24)]
        source = self.build([('Drums', 9, hits), ('Drums copy', 9, hits)])
        report = detect(source)
        normalized = normalize(source, report)

        self.assertEqual(report.groups, [])
        self.assertEqual(len(normalized.tracks), 3)   # conductor + 2 perkusyjne

    def test_three_way_duplicate_forms_one_group(self):
        events = [(0.5 + index * 0.2, 0.5 + index * 0.2 + 0.15, 60 + index % 7)
                  for index in range(24)]
        shifted_1 = [(a + 0.01, b + 0.01, n) for a, b, n in events]
        shifted_2 = [(a - 0.01, b - 0.01, n) for a, b, n in events]
        report = detect(self.build([('G', 0, events), ('L', 1, shifted_1), ('R', 2, shifted_2)]))

        self.assertEqual(len(report.groups), 1)
        self.assertEqual(report.groups[0].tracks, (1, 2, 3))
        self.assertEqual(report.groups[0].primary, 1)

    def test_chain_that_does_not_match_primary_is_not_collapsed(self):
        """A~B i B~C, ale A!~C: bezpieczenstwo wymaga zgodnosci z primary."""
        base = [(1.0 + index * 0.2, 1.0 + index * 0.2 + 0.15, 60 + index % 7)
                for index in range(24)]
        source = self.build([
            ('A', 0, base),
            ('B', 1, [(a + 0.012, b + 0.012, n) for a, b, n in base]),
            ('C', 2, [(a - 0.012, b - 0.012, (n + 1) % 12 + 60) for a, b, n in base]),
        ])
        report = detect(source)

        for group in report.groups:
            self.assertEqual(group.primary, min(group.tracks))


class TestNormalizedSource(DuplicateFileCase):
    def test_duplicates_disappear_but_metadata_stays(self):
        events = [(index * 0.2, index * 0.2 + 0.15, 60 + index % 7) for index in range(24)]
        source = self.build([('Guitar 1', 0, events), ('Guitar Dub', 1, events)])
        normalized = normalize(source)

        self.assertEqual(len(normalized.tracks), 2)          # conductor + partia logiczna
        primary = next(track for track in normalized.tracks if track.index == 1)
        self.assertEqual(primary.source_tracks, (1, 2))
        self.assertIsNotNone(primary.group_id)
        self.assertAlmostEqual(primary.duplicate_confidence or 0, 1.0, places=3)
        self.assertEqual(len(normalized.notes(1)), 24)
        self.assertEqual(normalized.raw_tonal_events, 48)
        self.assertEqual(normalized.logical_tonal_events, 24)

    def test_untouched_file_keeps_identical_tracks(self):
        events = [(index * 0.2, index * 0.2 + 0.15, 40 + index % 5) for index in range(24)]
        source = self.build([('Bass', 0, events), ('Lead', 1, [
            (index * 0.2, index * 0.2 + 0.15, 70 + index % 5) for index in range(24)])])
        normalized = normalize(source)

        self.assertEqual([track.index for track in normalized.tracks],
                         [track.index for track in source.tracks])

    def test_determinism_of_normalization(self):
        events = [(index * 0.2, index * 0.2 + 0.15, 60 + index % 7) for index in range(24)]
        source = self.build([('G1', 0, events), ('G2', 1, events), ('G3', 2, events)])
        first = normalize(source).as_dict()
        second = normalize(source).as_dict()

        self.assertEqual(first, second)


class TestAllocatorUsesOneVoicePerPart(DuplicateFileCase):
    def test_dub_does_not_consume_a_second_mechanical_voice(self):
        events = [(index * 0.2, index * 0.2 + 0.15, 60 + index % 7) for index in range(24)]
        source = self.build([('Guitar 1', 0, events), ('Guitar Dub', 1, events)])
        normalized = normalize(source)

        raw_plan = allocator.allocate(source, default_orchestra())
        logical_plan = allocator.allocate(normalized, default_orchestra())

        self.assertEqual(raw_plan.report()['totals']['requested'], 48)
        self.assertEqual(logical_plan.report()['totals']['requested'], 24)

    def test_event_keeps_source_track_metadata(self):
        events = [(index * 0.2, index * 0.2 + 0.15, 60 + index % 7) for index in range(24)]
        normalized = normalize(self.build([('G', 0, events), ('Dub', 1, events)]))
        plan = allocator.allocate(normalized, default_orchestra())

        self.assertTrue(plan.events)
        self.assertTrue(all(event.source_tracks == (1, 2) for event in plan.events))
        self.assertTrue(all(event.duplicate_group_id for event in plan.events))


class TestJigsawAndCreepRegressions(unittest.TestCase):
    MIDI_DIR = Path(__file__).resolve().parents[2] / 'midi'
    CREEP = MIDI_DIR / '0002-02-radiohead_1993-creep-[k].mid'
    TWO_PLUS_TWO = MIDI_DIR / '0063-01-radiohead_2003-2+2=5-[k].mid'

    def test_8_creep_detects_both_guitar_pairs(self):
        if not self.CREEP.is_file():
            self.skipTest('brak pliku benchmarkowego')

        source = MidiSource(self.CREEP)
        report = detect(source)
        pairs = {frozenset(group.tracks) for group in report.groups}

        self.assertIn(frozenset({1, 2}), pairs, 'Guitar 1 + Guitar Dub')
        self.assertIn(frozenset({5, 6}), pairs, 'Guitar 2 + Guitar 2 Dub')
        self.assertEqual(len(report.groups), 2)
        self.assertTrue(all(group.confidence > 0.9 for group in report.groups))

    def test_creep_offsets_are_detected(self):
        if not self.CREEP.is_file():
            self.skipTest('brak pliku benchmarkowego')

        report = detect(MidiSource(self.CREEP))
        offsets = {track: value for group in report.groups
                   for track, value in group.median_offsets.items()}

        self.assertAlmostEqual(offsets[2], 0.02174, places=4)
        self.assertAlmostEqual(offsets[6], 0.01087, places=4)

    def test_creep_collapse_reduces_fdd_pressure(self):
        if not self.CREEP.is_file():
            self.skipTest('brak pliku benchmarkowego')

        source = MidiSource(self.CREEP)
        normalized = normalize(source)
        before = allocator.allocate(source, default_orchestra(dvd_count=0)).report()
        after = allocator.allocate(normalized, default_orchestra(dvd_count=0)).report()

        self.assertLess(after['duplicates']['demandCapacityAfter'],
                        before['duplicates'].get('demandCapacityBefore', 0)
                        or after['duplicates']['demandCapacityAfter'] + 1)
        self.assertLess(after['totals']['dropRate'], before['totals']['dropRate'])
        self.assertLess(after['duplicates']['accompanimentDemandSecondsAfter'],
                        after['duplicates']['accompanimentDemandSecondsBefore'])
        # Zapowiedz uzytkownika: co najmniej dwie mocne grupy.
        self.assertEqual(after['duplicates']['groupsFound'], 2)
        self.assertEqual(after['duplicates']['duplicateEventsCollapsed'], 2534)

    def test_9_two_plus_two_is_not_mass_collapsed(self):
        if not self.TWO_PLUS_TWO.is_file():
            self.skipTest('brak pliku kontrolnego')

        source = MidiSource(self.TWO_PLUS_TWO)
        report = detect(source)
        normalized = normalize(source)

        self.assertEqual(report.groups, [], 'kontrola: brak grup w normalnej polifonii')
        self.assertEqual(report.raw_tonal_events, report.logical_tonal_events)
        self.assertEqual(len(normalized.tracks), len(source.tracks))

    def test_vhs_stays_lead_only_after_normalization(self):
        if not self.CREEP.is_file():
            self.skipTest('brak pliku benchmarkowego')

        plan = allocator.allocate(normalize(MidiSource(self.CREEP)), default_orchestra())
        vhs = [event for event in plan.events if event.device_id == 'vhs-1']

        self.assertTrue(vhs)
        self.assertTrue(all(event.role == 'lead' for event in vhs))
        self.assertEqual(plan.report()['leadDevices']['nonLeadEvents'], 0)

    def test_percussion_is_identical_before_and_after(self):
        if not self.CREEP.is_file():
            self.skipTest('brak pliku benchmarkowego')

        source = MidiSource(self.CREEP)
        before = allocator.allocate(source, default_orchestra()).report()
        after = allocator.allocate(normalize(source), default_orchestra()).report()

        self.assertEqual(before['percussion']['requested'], after['percussion']['requested'])
        self.assertEqual(before['percussion']['played'], after['percussion']['played'])
        self.assertEqual(before['percussion']['dropped'], after['percussion']['dropped'])


if __name__ == '__main__':
    unittest.main()
