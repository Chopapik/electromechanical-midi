"""Mechaniczna artykulacja FDD: sourceDuration -> performedDuration.

Wiekszosc testow buduje PerformancePlan RECZNIE - dzieki temu sprawdzaja sam
pass artykulacji, a nie to, co akurat wymyslil allocator.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midi_source import MidiSource  # noqa: E402
from playback import allocator, articulation, duplicates  # noqa: E402
from playback.articulation import SustainParams, apply, planned_end  # noqa: E402
from playback.capabilities import capabilities_for  # noqa: E402
from playback.orchestra import BALANCED, default_orchestra  # noqa: E402
from playback.performance import PerformanceEvent, PerformancePlan  # noqa: E402
from playback.virtual import VirtualDeviceInstance  # noqa: E402

PARAMS = SustainParams(enabled=True, minimum=0.120, preferred=0.190,
                       release=0.003, max_extension=0.200)


def device(ident: str, kind: str) -> VirtualDeviceInstance:
    profiles = {'FDD': 'FDD_CURRENT', 'VHS': 'VHS_CURRENT',
                'HDD_VCM': 'WD_CAVIAR_CURRENT'}

    return VirtualDeviceInstance.parse(
        {'id': ident, 'type': kind, 'name': ident, 'profile': profiles[kind]})


def event(ident: str, start: float, duration: float, device_id: str = 'fdd-1',
          kind: str = 'FDD', outcome: str = 'ACCEPTED', note: int = 60):
    return PerformanceEvent(
        id=ident, track=1, track_name='T', note=note, name='C4', velocity=100,
        channel=0, start=start, duration=duration, device_id=device_id,
        device_type=kind, played_note=note, played_hz=261.6,
        actual_start=start, actual_duration=duration, outcome=outcome)


def plan_with(events) -> PerformancePlan:
    return PerformancePlan(name='test', events=list(events), devices=[], policy={})


def capabilities(*devices):
    return capabilities_for(list(devices))


class TestPlannedEnd(unittest.TestCase):
    """Czysta funkcja: czy i o ile wydluzyc jedna nute."""

    def test_1_short_isolated_note_is_extended(self):
        # 60 ms, nastepna nuta dopiero za 400 ms -> jest gdzie wybrzmiec.
        end = planned_end(0.0, 0.060, limit=0.400, params=PARAMS)

        self.assertAlmostEqual(end, 0.190, places=4)

    def test_2_next_note_close_blocks_the_extension(self):
        # C4 @ 0, D4 @ 80 ms: C4 musi skonczyc sie przed D4.
        end = planned_end(0.0, 0.060, limit=0.080 - 0.003, params=PARAMS)

        self.assertAlmostEqual(end, 0.077, places=4)
        self.assertLess(end, 0.080)

    def test_3_long_note_is_left_alone(self):
        # 800 ms - nic nie trzeba robic.
        self.assertAlmostEqual(planned_end(0.0, 0.800, limit=5.0, params=PARAMS), 0.800, places=6)

    def test_note_between_preferred_and_source_is_untouched(self):
        self.assertAlmostEqual(planned_end(0.0, 0.300, limit=5.0, params=PARAMS), 0.300, places=6)

    def test_max_extension_caps_the_growth(self):
        params = SustainParams(True, 0.120, 5.0, 0.003, 0.200)
        self.assertAlmostEqual(planned_end(0.0, 0.050, limit=10.0, params=params),
                               0.250, places=4)

    def test_never_shortens_below_source(self):
        end = planned_end(0.0, 0.500, limit=0.100, params=PARAMS)
        self.assertGreaterEqual(end, 0.500)

    def test_disabled_pass_changes_nothing(self):
        params = SustainParams(False, 0.120, 0.190, 0.003, 0.200)
        self.assertAlmostEqual(planned_end(0.0, 0.060, limit=5.0, params=params), 0.060, places=6)

    def test_no_room_means_no_change(self):
        self.assertAlmostEqual(planned_end(1.0, 1.060, limit=1.0, params=PARAMS), 1.060, places=6)


class TestArticulationPass(unittest.TestCase):
    def setUp(self):
        self.caps = capabilities(device('fdd-1', 'FDD'), device('vhs-1', 'VHS'),
                                 device('hdd-1', 'HDD_VCM'))

    def run_pass(self, events, params=PARAMS):
        plan = plan_with(events)
        stats = apply(plan, self.caps, params)

        return plan, stats

    def test_4_fast_riff_keeps_onsets_and_never_overlaps(self):
        # Szybki riff, ale o zmieniajacej sie wysokosci (typowy przypadek).
        events = [event(f'n{i}', i * 0.070, 0.060, note=60 + i) for i in range(8)]
        plan, stats = self.run_pass(events)

        for index, item in enumerate(plan.events):
            self.assertAlmostEqual(item.actual_start, index * 0.070, places=9,
                                   msg='NOTE_ON nie moze sie przesunac')

        for left, right in zip(plan.events, plan.events[1:]):
            self.assertLessEqual(left.end, right.actual_start + 1e-9,
                                 f'{left.id} nachodzi na {right.id}')
            self.assertAlmostEqual(right.actual_start - left.end, 0.003, places=6)

        self.assertEqual(stats['extended'], len(events))

    def test_4b_same_pitch_riff_keeps_mechanical_articulation(self):
        # Powtorka tego samego pitchu co 70 ms: release rosnie do 12 ms, wiec
        # 60 ms nuty NIE da sie wydluzyc - i to jest poprawne.
        events = [event(f'n{i}', i * 0.070, 0.060, note=60) for i in range(8)]
        plan, stats = self.run_pass(events)

        for index, item in enumerate(plan.events):
            self.assertAlmostEqual(item.actual_start, index * 0.070, places=9)

        for left, right in zip(plan.events, plan.events[1:]):
            self.assertLessEqual(left.end, right.actual_start + 1e-9)
            # Pass nie moze ZMNIEJSZYC przerwy ponizej zrodlowej (10 ms),
            # bo wymog artykulacji powtorki (12 ms) jest od niej wiekszy.
            self.assertGreaterEqual(right.actual_start - left.end, 0.010 - 1e-9)

        # Wszystkie procz ostatniej (ta nie ma nastepnej nuty, wiec moze wybrzmiec).
        unchanged = [item for item in plan.events[:-1] if item.sustain_added > 0]
        self.assertEqual(unchanged, [], 'powtorka tego samego pitchu nie jest wydluzana')
        self.assertLessEqual(stats['extended'], 1)

    def test_5_shortened_note_is_not_restored(self):
        shortened = event('cut', 0.0, 0.050, outcome='SHORTENED')
        following = event('next', 0.050, 0.060)
        plan, _ = self.run_pass([shortened, following])

        self.assertAlmostEqual(plan.events[0].actual_duration, 0.050, places=6,
                               msg='sustain nie moze cofac decyzji SHORTEN')
        self.assertAlmostEqual(plan.events[0].sustain_added, 0.0, places=9)

    def test_6_stolen_event_keeps_its_slot(self):
        # Allocator oddal glos: poprzednia nuta skrocona, nowa STOLEN w jej miejscu.
        taken = event('victim', 0.0, 0.200, outcome='SHORTENED')
        thief = event('thief', 0.200, 0.060, outcome='STOLEN')
        later = event('later', 0.900, 0.060)
        plan, _ = self.run_pass([taken, thief, later])

        self.assertAlmostEqual(plan.events[0].actual_duration, 0.200, places=6)
        self.assertAlmostEqual(plan.events[1].actual_start, 0.200, places=6)
        # STOLEN moze dostac sustain tylko do nastepnej nuty, nie dalej.
        self.assertLessEqual(plan.events[1].end, 0.900)
        self.assertGreater(plan.events[1].actual_duration, 0.060)

    def test_7_hdd_is_untouched(self):
        events = [event('h1', 0.0, 0.060, 'hdd-1', 'HDD_VCM'),
                  event('h2', 1.0, 0.060, 'hdd-1', 'HDD_VCM')]
        plan, stats = self.run_pass(events)

        self.assertEqual(stats['extended'], 0)
        self.assertEqual([item.actual_duration for item in plan.events], [0.060, 0.060])

    def test_8_vhs_is_untouched(self):
        events = [event('v1', 0.0, 0.060, 'vhs-1', 'VHS', note=72),
                  event('v2', 1.0, 0.060, 'vhs-1', 'VHS', note=74)]
        plan, stats = self.run_pass(events)

        self.assertEqual(stats['extended'], 0)
        self.assertEqual([item.actual_duration for item in plan.events], [0.060, 0.060])

    def test_same_pitch_repeat_keeps_mechanical_articulation(self):
        """Powtorka tego samego pitchu nie moze zlac sie w jedna ciagla nute."""
        events = [event('a', 0.0, 0.060, note=60), event('b', 0.100, 0.060, note=60)]
        plan, _ = self.run_pass(events)
        gap = plan.events[1].actual_start - plan.events[0].end

        self.assertGreaterEqual(gap, 0.012 - 1e-9)

    def test_different_pitch_may_use_the_short_release(self):
        events = [event('a', 0.0, 0.060, note=60), event('b', 0.100, 0.060, note=64)]
        plan, _ = self.run_pass(events)
        gap = plan.events[1].actual_start - plan.events[0].end

        self.assertAlmostEqual(gap, 0.003, places=6)

    def test_dropped_events_are_ignored(self):
        events = [event('a', 0.0, 0.060), event('b', 0.100, 0.0, outcome='DROPPED')]
        plan, stats = self.run_pass(events)

        self.assertEqual(stats['extended'], 1)
        self.assertEqual(plan.events[1].actual_duration, 0.0)

    def test_9_determinism(self):
        events = [event(f'n{i}', i * 0.070, 0.050) for i in range(10)]
        first, _ = self.run_pass([event(f'n{i}', i * 0.070, 0.050) for i in range(10)])
        second, _ = self.run_pass([event(f'n{i}', i * 0.070, 0.050) for i in range(10)])

        self.assertEqual([e.actual_duration for e in first.events],
                         [e.actual_duration for e in second.events])

    def test_sustain_added_is_recorded_and_source_survives(self):
        plan, _ = self.run_pass([event('a', 0.0, 0.060), event('b', 1.0, 0.060)])
        first = plan.events[0]

        self.assertAlmostEqual(first.duration, 0.060, places=6)      # zrodlo nietkniete
        self.assertAlmostEqual(first.actual_duration, 0.190, places=4)
        self.assertAlmostEqual(first.sustain_added, 0.130, places=4)


class TestSustainReporting(unittest.TestCase):
    def test_event_exposes_source_and_performed_duration(self):
        caps = capabilities(device('fdd-1', 'FDD'))
        plan = plan_with([event('a', 0.0, 0.060), event('b', 1.0, 0.060)])
        apply(plan, caps, PARAMS)
        payload = plan.events[0].as_dict()

        self.assertAlmostEqual(payload['sourceDuration'], 0.060, places=6)
        self.assertAlmostEqual(payload['performedDuration'], 0.190, places=4)
        self.assertAlmostEqual(payload['sustainExtendedMs'], 130.0, places=1)
        self.assertEqual(payload['mechanicalArticulation'], 'mechanical-sustain')

    def test_untouched_event_has_no_mechanical_articulation(self):
        caps = capabilities(device('fdd-1', 'FDD'))
        plan = plan_with([event('a', 0.0, 0.800)])
        apply(plan, caps, PARAMS)

        self.assertIsNone(plan.events[0].as_dict()['mechanicalArticulation'])


class TestArticulationOnRealSongs(unittest.TestCase):
    MIDI_DIR = Path(__file__).resolve().parents[2] / 'midi'
    CREEP = MIDI_DIR / '0002-02-radiohead_1993-creep-[k].mid'
    TWO_PLUS_TWO = MIDI_DIR / '0063-01-radiohead_2003-2+2=5-[k].mid'

    def plans(self, path):
        source = duplicates.normalize(MidiSource(path))
        base = default_orchestra(dvd_count=0)
        off = allocator.allocate(source, type(base)(
            devices=base.devices, policy={**BALANCED, 'mechanicalSustain': False}))
        on = allocator.allocate(source, base)

        return off, on

    def test_10_creep_gaps_shrink(self):
        if not self.CREEP.is_file():
            self.skipTest('brak pliku benchmarkowego')

        off, on = self.plans(self.CREEP)
        before, after = off.report()['continuity'], on.report()['continuity']

        self.assertGreater(after['accompanimentContinuity'],
                           before['accompanimentContinuity'] + 0.2)
        self.assertLess(after['longGapCount'], before['longGapCount'])
        self.assertLess(after['orchestraSilentTime'], before['orchestraSilentTime'])
        self.assertEqual(off.report()['totals']['played'], on.report()['totals']['played'])
        self.assertEqual(off.report()['totals']['dropped'], on.report()['totals']['dropped'])

    def test_11_two_plus_two_onsets_are_bit_for_bit_identical(self):
        if not self.TWO_PLUS_TWO.is_file():
            self.skipTest('brak pliku kontrolnego')

        off, on = self.plans(self.TWO_PLUS_TWO)

        self.assertEqual(len(off.events), len(on.events))

        for left, right in zip(off.events, on.events):
            self.assertEqual(left.id, right.id)
            self.assertEqual(left.actual_start, right.actual_start)
            self.assertEqual(left.device_id, right.device_id)
            self.assertEqual(left.outcome, right.outcome)
            self.assertEqual(left.duration, right.duration)

    def test_only_fdd_durations_change(self):
        if not self.TWO_PLUS_TWO.is_file():
            self.skipTest('brak pliku kontrolnego')

        off, on = self.plans(self.TWO_PLUS_TWO)

        for left, right in zip(off.events, on.events):
            if abs(left.actual_duration - right.actual_duration) > 1e-9:
                self.assertEqual(left.device_type, 'FDD')

            if left.device_type in ('VHS', 'HDD_VCM'):
                self.assertEqual(left.actual_duration, right.actual_duration)

    def test_no_fdd_overlap_after_sustain(self):
        if not self.CREEP.is_file():
            self.skipTest('brak pliku benchmarkowego')

        _, on = self.plans(self.CREEP)
        by_device: dict[str, list] = {}

        for item in on.events:
            if item.played and item.device_type == 'FDD':
                by_device.setdefault(item.device_id, []).append(item)

        for device_id, events in by_device.items():
            events.sort(key=lambda item: item.actual_start)

            for left, right in zip(events, events[1:]):
                self.assertLessEqual(left.end, right.actual_start + 1e-9,
                                     f'{device_id}: {left.id} nachodzi na {right.id}')


if __name__ == '__main__':
    unittest.main()
