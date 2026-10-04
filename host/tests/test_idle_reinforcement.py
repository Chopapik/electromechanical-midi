"""A–M: primary invariance, musical compatibility and future reservations."""
import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path

import mido
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_source import MidiSource
from playback.allocator import allocate, ManualPin, _priority
from playback.analysis import MidiAnalysis
from playback.orchestra import default_orchestra, parse_idle, parse_orchestra
from playback.reinforcement import apply_reinforcement, legacy_dvd
from playback.tray import add_reinforcement
from playback.virtual import VirtualOrchestra, WavePreview
from playback.engine import PlaybackEngine
from test_allocator import write_tracks, write_drums


class IdleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.mid'

    def tearDown(self):
        self.tmp.cleanup()

    def tonal(self, notes=((0, 1, 60),), target='DVD_SLED', settings=None, pins=None):
        source = MidiSource(write_tracks(self.path, [('Guitar', 0, notes)]))
        config = default_orchestra(dvd_mode='reinforcement')
        config.idle_reinforcement = parse_idle({'enabled': True, 'deviceTypes': [target], **(settings or {})})
        analysis = MidiAnalysis([], None, 0, None, 0, {f'1:{n.order}': 'harmony' for n in source.notes(1)})
        pins = pins or {'1:0': ManualPin(device_id='DVD_STEPPER_1', rule_id='test')}
        return allocate(source, config, midi_analysis=analysis, pins=pins)

    def percussion(self, notes, settings=None):
        write_drums(self.path, notes)
        midi = mido.MidiFile(self.path)
        for track in midi.tracks:
            for message in track:
                if message.type == 'note_on':
                    message.velocity = 120
        midi.save(self.path)
        config = default_orchestra()
        config.idle_reinforcement = parse_idle({'enabled': True, **(settings or {})})
        return allocate(MidiSource(self.path), config)

    def assert_safe(self, plan):
        for extra in plan.reinforcements:
            for primary in plan.events:
                if primary.played and primary.device_id == extra.device_id:
                    self.assertTrue(extra.start + extra.duration <= primary.actual_start + 1e-8
                                    or extra.start >= primary.end - 1e-8)
        for source in plan.events:
            points = []
            for extra in [*plan.reinforcements, *plan.tray_events]:
                if extra.source_id == source.id:
                    points.extend([(extra.start, 1), (extra.start+extra.duration, -1)])
            count = 0
            for _, delta in sorted(points):
                count += delta
                self.assertLessEqual(count, plan.idle_reinforcement['maxCopiesPerEvent'])

    def test_a_idle_dvd(self):
        plan = self.tonal()
        self.assertTrue(plan.reinforcements)
        self.assert_safe(plan)
        self.assertTrue(all(e.source_device == 'DVD_STEPPER_1' and e.score >= 75 for e in plan.reinforcements))

    def test_b_idle_fdd_exact_pitch_no_new_harmony(self):
        plan = self.tonal(target='FDD')
        self.assertTrue(plan.reinforcements)
        self.assertTrue(all(e.hz == plan.events[0].played_hz for e in plan.reinforcements))
        self.assert_safe(plan)

    def test_c_incompatible_and_out_of_range(self):
        self.assertFalse(self.tonal(target='HDD_VCM').reinforcements)
        plan = self.tonal(notes=((0, 1, 90),), target='FDD')
        self.assertFalse(plan.reinforcements)
        self.assertGreater(plan.idle_report['rejected']['outOfRange'], 0)
        self.assertFalse(self.tonal(target='VHS').reinforcements)

    def test_d_future_primary_reserved(self):
        plan = self.tonal(notes=((0, .8, 60), (.08, .7, 64)),
            pins={'1:0': ManualPin(device_id='DVD_STEPPER_1', rule_id='a'),
                  '1:1': ManualPin(device_id='DVD_STEPPER_2', rule_id='b')})
        self.assertFalse(any(e.device_id == 'DVD_STEPPER_2' and e.start < .08 for e in plan.reinforcements))
        self.assertGreater(plan.idle_report['rejected']['deviceNeededSoon'], 0)
        self.assert_safe(plan)

    def test_e_primary_and_articulation_exactly_unchanged(self):
        plan = self.tonal(target='FDD')
        before = [e.as_dict() for e in plan.events]
        plan.idle_reinforcement = parse_idle({'enabled': False})
        apply_reinforcement(plan, lambda e: _priority(e.role, e.velocity, e.duration, plan.policy))
        self.assertEqual(before, [e.as_dict() for e in plan.events])
        self.assertEqual(plan.report()['tonal']['dropped'], 0)

    def test_f_shared_copy_limit_and_zero(self):
        plan = self.tonal(settings={'maxCopiesPerEvent': 2, 'minScore': 45})
        self.assertEqual(len(plan.reinforcements), 2)
        self.assert_safe(plan)
        self.assertFalse(self.tonal(settings={'maxCopiesPerEvent': 0}).reinforcements)
        drums = self.percussion([(0, .05, 49)])
        self.assertEqual(len(drums.reinforcements) + len(drums.tray_events), 1)
        self.assert_safe(drums)

    def test_g_low_score_stays_idle(self):
        plan = self.tonal(settings={'minScore': 1000})
        self.assertFalse(plan.reinforcements)
        self.assertGreater(plan.idle_report['rejected']['scoreTooLow'], 0)

    def test_h_hdd_strong_accents(self):
        plan = self.percussion([(0, .05, 49), (.8, .85, 48)], {'deviceTypes': ['HDD_VCM']})
        self.assertTrue(plan.reinforcements)
        self.assertTrue(all(e.kind == 'hit' for e in plan.reinforcements))
        self.assert_safe(plan)
        renderer = VirtualOrchestra().load_plan(plan)
        renderer.render_plan(plan)
        self.assertEqual(len([e for e in renderer.events if e.kind == 'hit']),
                         len([e for e in plan.events if e.played]) + len(plan.reinforcements))

    def test_i_dense_hats_stay_idle(self):
        plan = self.percussion([(i*.1, i*.1+.03, 42) for i in range(30)])
        self.assertFalse(plan.reinforcements)
        self.assertFalse(plan.tray_events)

    def test_j_tray_busy_and_cooldown(self):
        plan = self.percussion([(i*.12, i*.12+.04, 49) for i in range(20)])
        self.assertTrue(plan.tray_events)
        for device in ('DVD_TRAY_1', 'DVD_TRAY_2'):
            events = [e for e in plan.tray_events if e.device_id == device]
            for a, b in zip(events, events[1:]):
                self.assertGreaterEqual(b.start + 1e-8, a.start+a.duration+a.cooldown)
        self.assert_safe(plan)

    def test_k_l_legacy_dvd_and_tray_preserved_when_disabled(self):
        plan = self.tonal()
        plan.idle_reinforcement = parse_idle({'enabled': False})
        priority = lambda e: _priority(e.role, e.velocity, e.duration, plan.policy)
        expected = legacy_dvd(plan, priority)
        add_reinforcement(plan)
        trays = plan.tray_events[:]
        apply_reinforcement(plan, priority)
        self.assertEqual(plan.reinforcements, expected)
        self.assertEqual(plan.tray_events, trays)

    def test_m_roundtrip_ui_and_primary_counts(self):
        config = default_orchestra()
        config.idle_reinforcement = parse_idle({'enabled': True, 'deviceTypes': ['FDD']})
        self.assertEqual(parse_orchestra(config.as_dict()).as_dict(), config.as_dict())
        write_tracks(self.path, [('Guitar', 0, [(0, 1, 60), (0, 1, 64)])])
        engine = PlaybackEngine(auto_arrange=True)
        try:
            engine.load_file(self.path)
            before = engine.arrangement_view()['notes']
            engine.configure_virtual({**config.as_dict(), 'enabled': True})
            view = engine.arrangement_view()
            self.assertEqual(before, view['notes'])
            self.assertTrue(view['reinforcementNotes'])
            self.assertTrue(all(e['eventKind'] == 'reinforcement' and e['reason'] for e in view['reinforcementNotes']))
        finally:
            engine.shutdown()

    def test_global_threshold_applies_to_trays_and_hdd(self):
        plan = self.percussion([(0, .05, 49)], {'minScore': 1000})
        self.assertFalse(plan.reinforcements)
        self.assertFalse(plan.tray_events)

    def test_semantic_mismatch_is_rejected(self):
        plan = self.tonal(notes=((0, .5, 60), (.6, 1.4, 64)), target='FDD',
            pins={'1:0': ManualPin(device_id='fdd-1', rule_id='a'),
                  '1:1': ManualPin(device_id='DVD_STEPPER_1', rule_id='b')})
        # Bind an otherwise idle device to a known, incompatible track role.
        plan.devices = [dict(d, track=999) if d['id'] == 'fdd-2' else d for d in plan.devices]
        # Test the pure compatibility boundary directly with explicit identity.
        from playback.reinforcement import _compatible
        from playback.capabilities import capability_for
        from playback.virtual import VirtualDeviceInstance
        target = VirtualDeviceInstance.parse(next(d for d in plan.devices if d['id'] == 'fdd-2'))
        reject, _, _ = _compatible(plan.events[1], target, capability_for(target),
                                   ('KEYS', 'Piano', 0), (999, 'GUITAR', 'Guitar', 24))
        self.assertEqual(reject, 'incompatibleRole')

    def test_global_toggle_builds_plan_when_auto_arranger_was_disabled(self):
        write_tracks(self.path, [('Guitar', 0, [(0, 1, 60), (0, 1, 64)])])
        engine = PlaybackEngine(auto_arrange=False)
        try:
            engine.load_file(self.path)
            config = default_orchestra()
            config.idle_reinforcement = parse_idle({'enabled': True})
            engine.configure_virtual({**config.as_dict(), 'enabled': True})
            view = engine.arrangement_view()
            self.assertTrue(view['report']['idleReinforcement']['enabled'])
            self.assertTrue(view['reinforcementNotes'])
        finally:
            engine.shutdown()

    def test_configuration_validation_and_no_compatible_material(self):
        for settings in ({'maxCopiesPerEvent': 3}, {'deviceTypes': ['HDD_RANDOM']}, {'lookAheadMs': -1}, {'minScore': float('nan')}):
            with self.assertRaises(ValueError):
                parse_idle(settings)
        plan = self.tonal(settings={'deviceTypes': []})
        self.assertFalse(plan.reinforcements)
        self.assertFalse(plan.tray_events)
        self.assertGreater(plan.idle_report['devices']['DVD_STEPPER_2']['idleSeconds'], 0)
