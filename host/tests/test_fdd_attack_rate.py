import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playback.fdd_attack_rate import apply
from playback.performance import PerformanceEvent, PerformancePlan, ReinforcementEvent
from playback.orchestra import parse_policy
from playback.mechanical_arrangement import _chronology
from runtime.registry import DeviceRegistry
from runtime.compiler import compile_plan


def event(i, start, duration=.03, **changes):
    return replace(PerformanceEvent(str(i), 1, 'riff', 57, None, 100, 0, start, duration,
        'fdd-1', 'FDD', 57, 220., start, duration, 'ACCEPTED'), **changes)


def plan(events):
    return PerformancePlan('riff', events, [{'id': 'fdd-1', 'type': 'FDD'},
        {'id': 'fdd-2', 'type': 'FDD'}, {'id': 'DVD_STEPPER_1', 'type': 'DVD_SLED'}], parse_policy({}))


class FddAttackRateTests(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()

    def assert_rate(self, p):
        tones = [c for c in compile_plan(p).commands if c.kind == 'tone' and c.device_id.startswith('fdd-')]
        for ident in ('fdd-1', 'fdd-2', 'fdd-3', 'fdd-4'):
            times = [c.time for c in tones if c.device_id == ident]
            self.assertTrue(all(b-a >= .12-1e-9 for a, b in zip(times, times[1:])))
            self.assertIsNotNone(_chronology(self.registry.profile(ident),
                [e for e in p.events if e.played and e.device_id == ident],
                [e for e in p.reinforcements if e.device_id == ident]))

    def test_repeated_45ms_attacks_become_slower_sustained_pulses(self):
        original = [event(i, i*.045) for i in range(12)]
        p = plan(original)
        report = apply(p, self.registry)
        self.assertEqual(report['suppressedAttacks'], 8)
        self.assertEqual(report['coalescedRepeats'], 8)
        kept = [e for e in p.events if e.played]
        self.assertEqual([round(e.actual_start, 3) for e in kept], [0, .135, .27, .405])
        self.assertAlmostEqual(kept[0].actual_duration, .12)
        for a, b in zip(original, p.events):
            self.assertEqual((a.start, a.duration, a.note), (b.start, b.duration, b.note))
        self.assert_rate(p)
        before = compile_plan(p)
        apply(p, self.registry)
        self.assertEqual(compile_plan(p), before)

    def test_fast_pitch_changes_are_reduced_without_delaying_or_inventing_notes(self):
        p = plan([event(i, i*.04, note=57+i, played_note=57+i, played_hz=220.+i*10) for i in range(10)])
        apply(p, self.registry)
        self.assertEqual([e.id for e in p.events if e.played], ['0', '3', '6', '9'])
        self.assertTrue(all(e.actual_start == e.start and e.actual_duration == e.duration
                            for e in p.events if e.played))
        self.assert_rate(p)

    def test_normal_riff_long_notes_and_real_rests_are_preserved(self):
        for events in ([event(i, i*.18, .15) for i in range(10)],
                       [event(0, 0, 1), event(1, 2, 1)],
                       [event(0, 0, .01), event(1, .1, .01)]):
            p = plan(events)
            apply(p, self.registry)
            if len(events) == 2 and events[1].start == .1:
                self.assertEqual(p.events[0].actual_duration, .01)  # Do not fill an 90 ms rest.
            else:
                self.assertEqual(p.events, events)

    def test_no_merging_across_parts_or_explicit_articulation(self):
        for changes in ({'track': 2}, {'channel': 1}, {'articulation': 'STACCATO'}, {'played_hz': 330.}):
            p = plan([event(0, 0), event(1, .045, **changes)])
            apply(p, self.registry)
            self.assertEqual(p.events[0].actual_duration, .03)
            self.assertFalse(p.events[1].played)

    def test_unison_copies_and_duet_members_are_rate_limited_too(self):
        p = plan([event(i, i*.045) for i in range(8)])
        p.reinforcements = [ReinforcementEvent(e.id, 'fdd-2', e.start, e.actual_duration,
            e.played_hz, e.velocity, kind='FDD_PAIR_UNISON') for e in p.events]
        apply(p, self.registry)
        self.assertEqual([(e.actual_start, e.actual_duration, e.played_hz) for e in p.events if e.played],
                         [(e.start, e.duration, e.hz) for e in p.reinforcements])
        self.assert_rate(p)

    def test_other_actuators_and_extra_expression_keep_exact_commands(self):
        p = plan([event(i, i*.045) for i in range(8)]+[
            event(30, .02, .4, device_id='DVD_STEPPER_1', device_type='DVD_SLED')])
        p.reinforcements = [ReinforcementEvent('1', 'fdd-2', .045, .03, 220, 100),
                            ReinforcementEvent('1', 'DVD_STEPPER_1', 1, .2, 220, 100)]
        p.execution_articulation = {'30': {'gate': .4}, 'extra:0': {'gate': .03},
                                   'extra:1': {'gate': .2, 'gain': {'times': [0], 'values': [.8]}}}
        before = [c for c in compile_plan(p).commands if c.device_id == 'DVD_STEPPER_1']
        apply(p, self.registry)
        self.assertEqual([c for c in compile_plan(p).commands if c.device_id == 'DVD_STEPPER_1'], before)

    def test_extension_mechanical_veto_falls_back_to_original_gate(self):
        from playback.hardware_profiles import evaluate
        p = plan([event(0, 0), event(1, .045)])
        def veto(profile, note, state):
            ev = evaluate(profile, note, state)
            return replace(ev, authorized=False) if note.duration > .031 else ev
        with patch('playback.fdd_attack_rate.evaluate', side_effect=veto):
            apply(p, self.registry)
        self.assertEqual(p.events[0].actual_duration, .03)
        self.assert_rate(p)

    def test_common_floor_cannot_be_disabled_or_nonfinite(self):
        self.assertEqual(parse_policy({})['fddMinAttackIntervalMs'], 120)
        for value in (0, 119, float('nan'), float('inf'), 1001):
            with self.assertRaises(ValueError):
                parse_policy({'fddMinAttackIntervalMs': value})
        self.assertEqual(parse_policy({})['fddFixedToneMs'],0)
        for value in (-1,float('nan'),float('inf'),5001):
            with self.assertRaises(ValueError):
                parse_policy({'fddFixedToneMs':value})

    def test_every_preset_and_strict_routing_use_the_common_final_pass(self):
        from midi_source import MidiSource
        from runtime.arranger import arrange
        from test_allocator import write_tracks
        presets = ('balanced', 'fdd_quality', 'fdd_quality_adaptive', 'dvd_lead_low_fdd',
                   'instrument_roles', 'instrument_roles_unison', 'instrument_roles_duet',
                   'instrument_roles_unison4', 'universal')
        with tempfile.TemporaryDirectory() as directory:
            source = MidiSource(write_tracks(Path(directory)/'fast.mid',
                [('Riff', 0, [(i*.045, i*.045+.03, 57+i%3) for i in range(24)])]))
            for preset in presets:
                for strict in (False, True):
                    with self.subTest(preset=preset, strict=strict):
                        r = DeviceRegistry()
                        for d in r.devices: d['enabled'] = d['type'] == 'FDD'
                        r.document['parameters']['arrangementPreset'] = preset
                        if strict:
                            r.document['routing'] = {'mode': 'STRICT_TRACKS', 'tracks': [1, None, None, None]}
                        p = arrange(source, r)
                        self.assertEqual(p.articulation['fddAttackRate']['minAttackIntervalMs'], 203)
                        self.assertEqual(p.articulation['fddAttackRate']['fixedToneMs'],200)
                        tones=[c for c in compile_plan(p).commands
                               if c.kind=='tone' and c.device_id.startswith('fdd-')]
                        self.assertTrue(tones)
                        self.assertTrue(all(abs(c.duration-.2)<1e-9 for c in tones))
                        self.assert_rate(p)
                        self.assertEqual(compile_plan(p), compile_plan(arrange(source, r)))
