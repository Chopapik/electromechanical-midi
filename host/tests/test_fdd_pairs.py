"""Paired instruments select real source parts and share one output timeline."""
import dataclasses
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_mechanical_arrangement as helpers
from playback.fdd_pairs import PRESETS
from playback.fdd_pairs import arrange as pair_plan
from playback.performance import ReinforcementEvent
from playback.tonal_articulation import resolve, retarget
from playback.allocator import allocate, ManualPin
from playback.analysis import analyze
from playback.orchestra import parse_policy
from runtime.application import Application
from runtime.compiler import compile_plan
from runtime.registry import PlanningProfiles
from runtime.outputs import RealOutput, VirtualOutput
from runtime.arranger import arrange


class FddPairTests(unittest.TestCase):
    setUp = helpers.MechanicalArrangementTests.setUp
    source = helpers.MechanicalArrangementTests.source
    registry = helpers.MechanicalArrangementTests.registry
    plan = helpers.MechanicalArrangementTests.plan
    assert_feasible = helpers.MechanicalArrangementTests.assert_feasible

    def selected(self, preset=PRESETS[0], **counts):
        r = self.registry(**counts)
        r.document['parameters'].update(arrangementPreset=preset,
            mechanicalSustain=True, sourceContinuity=True, fddUnisonEnabled=True)
        return r

    def tones(self, p):
        return [c for c in compile_plan(p).commands if c.kind == 'tone' and c.device_id.startswith('fdd-')]

    def test_unison_pairs_play_two_different_parts_at_identical_attacks(self):
        tracks = [(name, channel, [(i*.25, i*.25+.15, pitch+i%3) for i in range(8)])
                  for name, channel, pitch in [('A', 0, 60), ('B', 1, 67)]]
        r = self.selected()
        p = self.plan(tracks, r)
        tones = self.tones(p)
        for first, second in [('fdd-1', 'fdd-2'), ('fdd-3', 'fdd-4')]:
            signature = lambda ident: [(c.time, c.hz, c.duration, c.source_id, c.velocity)
                                      for c in tones if c.device_id == ident]
            self.assertEqual(signature(first), signature(second))
            self.assertEqual(len(signature(first)), 8)
        self.assertEqual(len({e.track for e in p.events if e.played}), 2)
        self.assert_feasible(p, r)

    def test_duet_uses_two_real_chord_notes_from_each_part(self):
        tracks = [(name, channel, [(i*.25, i*.25+.15, pitch+j)
                   for i in range(8) for j in (0, 4, 7)])
                  for name, channel, pitch in [('A', 0, 60), ('B', 1, 67)]]
        r = self.selected(PRESETS[1], dvd=0)
        p = self.plan(tracks, r)
        self.assertFalse(p.reinforcements)
        for i in range(8):
            for pair in [('fdd-1', 'fdd-2'), ('fdd-3', 'fdd-4')]:
                notes = [e for e in p.events if e.played and e.device_id in pair and e.start == i*.25]
                self.assertEqual(len(notes), 2)
                self.assertEqual(len({e.track for e in notes}), 1)
                self.assertEqual(len({e.played_note for e in notes}), 2)
        self.assert_feasible(p, r)

    def test_duet_single_line_falls_back_to_unison_and_strums_keep_times(self):
        for offsets in [(0,), (0, .01)]:
            tracks = [('A', 0, [(i*.25+offset, i*.25+offset+.1, 60+j*7)
                       for i in range(5) for j, offset in enumerate(offsets)])]
            r = self.selected(PRESETS[1])
            p = self.plan(tracks, r)
            self.assertEqual(len(self.tones(p)), 10)
            self.assertTrue(all(e.actual_start == e.start for e in p.events if e.played))
            self.assertEqual(len(p.reinforcements), 5 if len(offsets) == 1 else 0)
            self.assert_feasible(p, r)

    def test_silent_part_is_replaced_and_other_pair_keeps_its_phrase(self):
        tracks = [('A', 0, [(0, .15, 60), (.25, .4, 62)]),
                  ('B', 1, [(i*.25, i*.25+.15, 67+i%3) for i in range(12)]),
                  ('C', 2, [(i*.25, i*.25+.15, 55+i%3) for i in range(3, 12)])]
        for preset in PRESETS:
            r = self.selected(preset)
            p = self.plan(tracks, r)
            by_name = {name: {e.device_id for e in p.events if e.played and e.track_name == name}
                       for name in ('A', 'B', 'C')}
            self.assertEqual(by_name['A'], by_name['C'])
            self.assertTrue(by_name['A'].isdisjoint(by_name['B']))
            for i in range(3, 12):
                self.assertEqual(len([c for c in self.tones(p) if c.time == i*.25]), 4)
            self.assert_feasible(p, r)

    def test_active_owners_do_not_swap_or_leave_an_idle_pair_among_four_parts(self):
        tracks = [(name, channel, [(i*.25, i*.25+.15, 55+channel*3+i%3) for i in range(12)])
                  for channel, name in enumerate(('A', 'B', 'C', 'D'))]
        for preset in PRESETS:
            r = self.selected(preset)
            p = self.plan(tracks, r)
            for i in range(12):
                self.assertEqual(len([c for c in self.tones(p) if c.time == i*.25]), 4)
            self.assertEqual(p.hardware['fddPairs']['partChanges'], {'1': 0, '2': 0})
            self.assert_feasible(p, r)

    def test_missing_member_does_not_renumber_the_pairs(self):
        r = self.selected()
        r.by_id['fdd-2']['enabled'] = False
        tracks = [('A', 0, [(i*.25, i*.25+.15, 60+i%3) for i in range(4)]),
                  ('B', 1, [(i*.25, i*.25+.15, 67+i%3) for i in range(4)])]
        p = self.plan(tracks, r)
        self.assertEqual(p.hardware['fddPairs']['pairs'], [['fdd-1'], ['fdd-3', 'fdd-4']])
        self.assertNotIn('fdd-2', {c.device_id for c in self.tones(p)})
        self.assert_feasible(p, r)

    def test_overlapping_gates_leave_room_for_every_riff_attack(self):
        tracks = [('A', 0, [(i*.2, i*.2+.3, 60+i%3) for i in range(10)]),
                  ('B', 1, [(i*.2, i*.2+.3, 67+i%3) for i in range(10)])]
        for preset in PRESETS:
            r = self.selected(preset, dvd=0)
            p = self.plan(tracks, r)
            self.assertEqual(len(self.tones(p)), 40)
            self.assert_feasible(p, r)

    def test_manual_note_and_drop_remain_fixed_and_reserved(self):
        source = self.source([('A', 0, [(0, .3, 60), (.5, .6, 62)]),
                              ('B', 1, [(i*.1, i*.1+.05, 67+i%3) for i in range(8)])])
        analysis = analyze(source)
        analysis = dataclasses.replace(analysis, roles={f'{t.index}:{n.order}': 'harmony'
            for t in source.tracks for n in source.notes(t.index)})
        pins = {'1:0': ManualPin(device_id='fdd-1', rule_id='fixed'),
                '1:1': ManualPin(device_id=None, rule_id='omit')}
        r = self.selected('instrument_roles', dvd=0)
        build = lambda: allocate(source, r.configuration(), hardware_context=PlanningProfiles(r),
                                 midi_analysis=analysis, pins=pins)
        baseline = {e.id: e for e in build().events}
        for preset in PRESETS:
            r.document['parameters']['arrangementPreset'] = preset
            p = build()
            for e in p.events:
                if e.id in pins:
                    self.assertEqual(e, baseline[e.id])
            self.assertFalse(any(e.source_id in pins for e in p.reinforcements))
            self.assert_feasible(p, r)

    def test_pairs_are_deterministic_and_leave_non_fdd_allocations_unchanged(self):
        tracks = [('Riff A', 0, [(i*.25, i*.25+.15, 60+i%3) for i in range(8)]),
                  ('Riff B', 1, [(i*.25, i*.25+.15, 67+i%3) for i in range(8)]),
                  ('Pad', 2, [(0, 3, 48), (0, 3, 55), (0, 3, 60)])]
        base_registry = self.selected('instrument_roles')
        base = self.plan(tracks, base_registry)
        for preset in PRESETS:
            r = self.selected(preset)
            p, q = self.plan(tracks, r), self.plan(tracks, r)
            self.assertEqual(p.events, q.events)
            self.assertEqual(compile_plan(p), compile_plan(q))
            self.assertEqual([e for e in base.events if e.device_type == 'DVD_SLED'],
                             [e for e in p.events if e.device_type == 'DVD_SLED'])
            self.assert_feasible(p, r)

    def test_preset_switch_rebuilds_common_timeline_and_stops_playback(self):
        source = self.source([('Riff', 0, [(i*.25, i*.25+.15, 60+i%3) for i in range(8)])])
        app = Application(self.selected())
        app.load(source.path)
        app.real.link = helpers.Link()
        app.real.configured = True
        for preset in PRESETS:
            app.player.play()
            self.assertEqual(app.player.state, 'playing')
            self.assertEqual(parse_policy({'arrangementPreset': preset})['arrangementPreset'], preset)
            app.set_preset(preset)
            self.assertEqual(app.plan.policy['arrangementPreset'], preset)
            self.assertEqual(app.timeline, compile_plan(app.plan))
            self.assertEqual(app.player.state, 'stopped')

    def test_both_outputs_receive_all_paired_attacks(self):
        tracks = [('A', 0, [(0, .15, 60)]), ('B', 1, [(0, .15, 67)])]
        for preset in PRESETS:
            r = self.selected(preset)
            timeline = compile_plan(self.plan(tracks, r))
            lines, packets = [], []
            real = RealOutput(r)
            real.link = SimpleNamespace(send_batch=lambda batch: lines.extend(batch))
            virtual = VirtualOutput(packets.append)
            real.dispatch(timeline.commands)
            virtual.dispatch(timeline.commands, epoch=1)
            self.assertEqual(packets[0]['commands'], [c.as_dict() for c in timeline.commands])
            self.assertEqual(len([line for line in lines if ' PLAY ' in line]), 4)
            self.assertEqual({line.split(' PLAY ')[0] for line in lines if ' PLAY ' in line},
                             {'FDD 1', 'FDD 2', 'FDD 3', 'FDD 4'})

    def test_dvd_copy_keeps_expression_when_its_fdd_source_is_omitted(self):
        tracks = [('A', 0, [(0, .15, 60), (0, .15, 64)]),
                  ('B', 1, [(0, .15, 67)]), ('C', 2, [(0, .15, 69)])]
        r = self.selected('instrument_roles', dvd=1)
        base = self.plan(tracks, r)
        source_note = next(e for e in base.events if e.note == 64)
        self.assertEqual(source_note.device_type, 'FDD')
        copy = ReinforcementEvent(source_note.id, 'DVD_STEPPER_1', 0, .15,
                                  source_note.played_hz, 100, source_device=source_note.device_id)
        base.reinforcements.append(copy)
        tonal, _ = resolve(base)
        expected = dataclasses.asdict(retarget(tonal[source_note.id], 'DVD_SLED', .15, 100))
        r.document['parameters']['arrangementPreset'] = PRESETS[0]
        paired = pair_plan(base, r.configuration(), PlanningProfiles(r))
        self.assertFalse(next(e for e in paired.events if e.id == source_note.id).played)
        with patch('runtime.arranger.allocate', return_value=paired):
            final = arrange(self.source(tracks), r)
        command = next(c for c in compile_plan(final).commands if c.device_id == 'DVD_STEPPER_1' and c.kind == 'tone')
        self.assertEqual(command.articulation, expected)
        self.assertEqual(final.reinforcements[0], copy)
        self.assert_feasible(final, r)
