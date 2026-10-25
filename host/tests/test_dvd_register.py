"""Musical DVD register; real profiles and compiled schedules, no hardware I/O."""
import copy
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import patch

import test_mechanical_arrangement as helpers
from playback.dvd_register import apply
from playback.performance import PerformanceEvent, PerformancePlan, ReinforcementEvent
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.registry import DeviceRegistry
from runtime.outputs import RealOutput, VirtualOutput


class DvdRegisterTests(helpers.unittest.TestCase):
    setUp = helpers.MechanicalArrangementTests.setUp
    source = helpers.MechanicalArrangementTests.source
    assert_feasible = helpers.MechanicalArrangementTests.assert_feasible

    def event(self, ident, hz, start=0., duration=.5, track=0, device='DVD_STEPPER_1', note=55):
        return PerformanceEvent(str(ident), track, 'Pad', note, None, 80, 0, start, duration,
            device, 'DVD_SLED', note, hz, start, duration, 'ACCEPTED')

    def plan(self, events, extras=()):
        r = DeviceRegistry()
        p = PerformancePlan('fixture', list(events), r.configuration().devices, {},
                            reinforcements=list(extras))
        return p, r

    def test_whole_phrase_moves_up_without_boundary_jump(self):
        p, r = self.plan([self.event(0, 196.), self.event(1, 220., .5, note=57)])
        apply(p, r, None)
        self.assertEqual([e.played_hz for e in p.events], [392., 440.])
        self.assertEqual([e.played_note for e in p.events], [67, 69])
        self.assertEqual(p.hardware['dvdRegister']['individualFoldPhrases'], 0)
        self.assertEqual([c.kind for c in compile_plan(p).commands], ['tone', 'tone', 'stop'])
        self.assert_feasible(p, r)

    def test_real_and_virtual_dispatch_the_same_remapped_timeline(self):
        p, r = self.plan([self.event(0, 196.), self.event(1, 220., .5)])
        apply(p, r, None)
        timeline = compile_plan(p)
        lines, packets = [], []
        real = RealOutput(r)
        real.link = SimpleNamespace(controller_status={'atx': 'ON'},
                                    send_batch=lambda batch: lines.extend(batch))
        virtual = VirtualOutput(packets.append)
        real.dispatch(timeline.commands)
        virtual.dispatch(timeline.commands, epoch=1)
        self.assertEqual(lines, ['SLED 1 PLAY 392.00', 'SLED 1 PLAY 440.00', 'SLED 1 STOP'])
        self.assertEqual(packets[0]['commands'], [c.as_dict() for c in timeline.commands])

    def test_phrase_chooses_common_register_below_ceiling(self):
        p, r = self.plan([self.event(0, 300.), self.event(1, 600., .5, note=67)])
        apply(p, r, None)
        self.assertEqual([e.played_hz for e in p.events], [300., 600.])

    def test_800_hz_is_inclusive_and_higher_notes_fold_instead_of_dropping(self):
        for original, expected in ((199., 398.), (200., 400.), (400., 800.),
                                   (800., 800.), (801., 400.5), (1000., 500.)):
            with self.subTest(hz=original):
                p, r = self.plan([self.event(0, original)])
                apply(p, r, None)
                self.assertEqual(len(p.events), 1)
                self.assertTrue(p.events[0].played)
                self.assertEqual(p.events[0].played_hz, expected)
                self.assertEqual(p.hardware['dvdRegister']['maximumHz'], 800.)

    def test_multiple_octaves_and_unavoidable_individual_folding(self):
        p, r = self.plan([self.event(0, 55.), self.event(1, 880., .5, note=103)])
        apply(p, r, None)
        self.assertEqual([e.played_hz for e in p.events], [220., 440.])
        self.assertEqual(p.hardware['dvdRegister']['individualFoldPhrases'], 1)

    def test_same_source_phrase_follows_device_migration(self):
        p, r = self.plan([self.event(0, 300.),
            self.event(1, 600., .5, device='DVD_STEPPER_2', note=67)])
        apply(p, r, None)
        self.assertEqual([e.played_hz for e in p.events], [300., 600.])
        self.assertEqual(p.hardware['dvdRegister']['phrases'], 1)

    def test_real_rest_and_independent_tracks_split_registers(self):
        for kwargs in ({'start': 3.}, {'start': .5, 'track': 1}):
            with self.subTest(kwargs=kwargs):
                p, r = self.plan([self.event(0, 300.), self.event(1, 600., **kwargs)])
                apply(p, r, None)
                self.assertEqual([e.played_hz for e in p.events], [600., 600.])
                self.assertEqual(p.hardware['dvdRegister']['phrases'], 2)

    def test_simultaneous_independent_voices_have_separate_registers(self):
        p, r = self.plan([self.event(0, 55., note=33),
            self.event(1, 440., device='DVD_STEPPER_2', note=69)])
        apply(p, r, None)
        self.assertEqual([e.played_hz for e in p.events], [220., 440.])

    def test_tempo_controls_phrase_rest_boundary(self):
        source = SimpleNamespace(tempo=SimpleNamespace(_segments=[SimpleNamespace(seconds=0., tempo=250000)]))
        p, r = self.plan([self.event(0, 300.), self.event(1, 600., 1.1)])
        apply(p, r, source)
        self.assertEqual([e.played_hz for e in p.events], [600., 600.])

    def test_envelopes_bends_and_extras_use_target_register(self):
        primary = replace(self.event(0, 110.), device_id='fdd-1', device_type='FDD')
        extra = ReinforcementEvent('0', 'DVD_STEPPER_1', 0., .5, 220., 80)
        p, r = self.plan([primary], [extra])
        art = {'frequency': {'times': (0., .2), 'values': (110., 120.)},
               'gain': {'times': (0.,), 'values': (.8,)}, 'gate': .5}
        p.execution_articulation = {'0': art, 'extra:0': copy.deepcopy(art)}
        before = copy.deepcopy(p.execution_articulation['0'])
        apply(p, r, None)
        self.assertEqual(p.events[0], primary)
        self.assertEqual(p.reinforcements[0].hz, 440.)
        self.assertEqual(p.execution_articulation['extra:0']['frequency']['values'], (440., 480.))
        self.assertEqual(p.execution_articulation['extra:0']['gain'], art['gain'])
        self.assertEqual(p.execution_articulation['0'], before)

    def test_extreme_pitch_bend_samples_fold_without_clipping_pitch_class(self):
        p, r = self.plan([self.event(0, 220.)])
        p.execution_articulation = {'0': {'frequency': {'times': (0., .2), 'values': (55., 1760.)}}}
        apply(p, r, None)
        self.assertEqual(p.execution_articulation['0']['frequency']['values'], (220., 440.))
        self.assertEqual(p.hardware['dvdRegister']['curveSamplesFolded'], 2)

    def test_idempotence_and_dropped_event_preservation(self):
        dropped = replace(self.event('dropped', 110.), device_id=None, outcome='DROPPED')
        p, r = self.plan([self.event(0, 110.), dropped])
        apply(p, r, None)
        before = copy.deepcopy(p)
        apply(p, r, None)
        self.assertEqual(p, before)
        self.assertEqual(p.events[1], dropped)

    def test_invalid_reservations_fail_without_silently_dropping_notes(self):
        p, r = self.plan([self.event(0, 220.), self.event(1, 330., .1)])
        before = copy.deepcopy(p)
        with self.assertRaisesRegex(ValueError, 'mechanical chronology'):
            apply(p, r, None)
        self.assertEqual(p, before)

    def test_all_presets_preserve_allocation_and_non_dvd_execution(self):
        source = self.source([('Guitar', 0, [(i*.3, i*.3+.25, 48+i%9) for i in range(12)]),
            ('Pad', 1, [(0., 3., 43), (0., 3., 55)]),
            ('Lead Vocal', 2, [(0., 1., 72), (1.2, 2.5, 74)]),
            ('Drums', 9, [(i*.25, i*.25+.02, 36 if i%2 else 38) for i in range(12)])])
        for preset in ('balanced', 'fdd_quality', 'dvd_lead_low_fdd', 'fdd_quality_adaptive',
                       'instrument_roles', 'instrument_roles_unison', 'instrument_roles_duet',
                       'instrument_roles_unison4', 'fdd_expressive', 'fdd_expressive_solo', 'fdd_legato', 'universal'):
            with self.subTest(preset=preset):
                r = DeviceRegistry()
                r.document['parameters']['arrangementPreset'] = preset
                with patch('playback.dvd_register.apply'):
                    baseline = arrange(source, r)
                experiment = arrange(source, r)
                self.assertEqual([e for e in baseline.events if e.device_type != 'DVD_SLED'],
                                 [e for e in experiment.events if e.device_type != 'DVD_SLED'])
                self.assertEqual(len(baseline.reinforcements), len(experiment.reinforcements))
                for a, b in zip(baseline.events, experiment.events):
                    ignored = {'played_note', 'played_hz', 'hardware'}
                    self.assertEqual({k: v for k, v in asdict(a).items() if k not in ignored},
                                     {k: v for k, v in asdict(b).items() if k not in ignored})
                types = {d['id']: d['type'] for d in baseline.devices}
                old, new = compile_plan(baseline), compile_plan(experiment)
                self.assertEqual([c for c in old.commands if types[c.device_id] != 'DVD_SLED'],
                                 [c for c in new.commands if types[c.device_id] != 'DVD_SLED'])
                signature = lambda c: (c.time, c.kind, c.device_id, c.duration, c.velocity, c.source_id)
                self.assertEqual([signature(c) for c in old.commands], [signature(c) for c in new.commands])
                self.assertTrue(all(200. <= c.hz <= 800. for c in new.commands
                                    if c.kind == 'tone' and types[c.device_id] == 'DVD_SLED'))
                self.assert_feasible(experiment, r)
