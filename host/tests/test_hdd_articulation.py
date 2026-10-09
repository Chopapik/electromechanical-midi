"""Domain, waveform and actuator invariants, independent of loudspeakers."""
import dataclasses
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playback.hdd_articulation import classify, adapt, sample, GM, KINDS
from playback.virtual import AcousticEvent, VirtualOrchestra
from reference_audio import WavePreview
from playback.performance import ReinforcementEvent
from playback.allocator import allocate
from playback.orchestra import default_orchestra, parse_idle
from midi_source import MidiSource
from test_allocator import write_drums


def orchestra(hits, mode='articulated'):
    o = VirtualOrchestra()
    o.set_config({'devices': [{'id': 'hdd', 'type': 'HDD_VCM'}], 'hddMode': mode})
    o.events = [AcousticEvent(t, 'hit', 'hdd', duration=.105, velocity=v,
        hdd_articulation=classify(note, 9, v), reinforcement=extra, source_note=note, source_channel=9)
        for t, note, v, extra in hits]
    return o

class HDDTest(unittest.TestCase):
    def test_full_gm_mapping_and_distinct_movements(self):
        self.assertEqual(set(GM), set(range(35, 82)))
        self.assertEqual(set(GM.values()), set(KINDS))
        self.assertEqual(classify(35, 9, 100).kind, 'HARD_HIT')
        self.assertEqual(classify(37, 9, 100).kind, 'DOUBLE_TAP')
        self.assertEqual(classify(44, 9, 100).kind, 'SOFT_TAP')
        self.assertEqual(classify(53, 9, 100).kind, 'BUZZ_ROLL')

    def test_side_stick_and_kick_have_different_waveforms(self):
        t = np.arange(3000) / 22050
        self.assertFalse(np.allclose(sample(t, classify(37, 9, 110), 'a', np), sample(t, classify(35, 9, 110), 'a', np)))
        self.assertEqual(len(classify(37, 9, 110).impulses), 2)

    def test_hat_is_short_and_dry(self):
        hat, kick = classify(44, 9, 100), classify(35, 9, 100)
        self.assertLess(hat.duration, kick.duration / 3)
        self.assertLess(hat.body, kick.body / 10)
        self.assertLess(hat.decay, kick.decay / 3)

    def test_pitched_tom_contour_is_coarse_not_chromatic(self):
        toms = [classify(n, 0, 100) for n in (42, 52, 57)]
        self.assertEqual([t.pitch_band for t in toms], ['LOW', 'MID', 'HIGH'])
        self.assertEqual(len({t.resonance for t in toms}), 3)
        self.assertEqual(classify(52, 0, 100).resonance, classify(53, 0, 100).resonance)

    def test_velocity_changes_body_duration_and_transient(self):
        soft, hard = classify(35, 9, 40), classify(35, 9, 120)
        self.assertLess(soft.body, hard.body)
        self.assertLess(soft.movement, hard.movement)
        self.assertLess(soft.duration, hard.duration)
        self.assertLess(soft.intensity, hard.intensity)

    def test_dense_pattern_limits_ringing(self):
        art = classify(35, 9, 120)
        dense, sparse = adapt(art, .105), adapt(art, .5)
        self.assertLess(dense.decay, sparse.decay)
        self.assertLess(dense.body, sparse.body)
        self.assertLess(dense.duration, sparse.duration)

    def test_single_actuator_never_overlaps_and_release_goes_to_zero(self):
        o = orchestra([(0, 35, 120, False), (.05, 35, 120, False), (.11, 37, 120, False)])
        preview = WavePreview()
        lane = preview._plan(o, 10000)
        for a, b in zip(lane, lane[1:]):
            self.assertLessEqual(a[3]+a[4], b[3])
        self.assertGreater(preview.hdd_stats['chokes'], 0)
        left, _ = preview._render_numpy(np, lane[:1], 10000, 1)
        self.assertAlmostEqual(left[lane[0][4]-1], 0)
        self.assertTrue(np.all(left[lane[0][4]:] == 0))

    def test_reinforcement_cannot_choke_primary_and_ends_before_next_primary(self):
        o = orchestra([(0, 35, 120, False), (.03, 35, 120, True), (.15, 35, 120, True), (.20, 35, 120, False)])
        p = WavePreview(); lane = p._plan(o, 10000)
        self.assertEqual(p.hdd_stats['suppressedReinforcement'], 1)
        self.assertFalse(lane[0][2].reinforcement)
        without_extras = orchestra([(0, 35, 120, False), (.20, 35, 120, False)])
        baseline = WavePreview()._plan(without_extras, 10000)
        for normal, original in zip([x for x in lane if not x[2].reinforcement], baseline):
            self.assertEqual(normal[2].hdd_articulation, original[2].hdd_articulation)
            self.assertEqual(normal[4], original[4])
        extra = next(x for x in lane if x[2].reinforcement)
        self.assertLessEqual(extra[3]+extra[4], int(.20*p.RATE))

    def test_raw_bypasses_body_roll_and_ring(self):
        o = orchestra([(0, 37, 120, False)], 'raw')
        item = WavePreview()._plan(o, 5000)[0]
        art = item[2].hdd_articulation
        self.assertTrue(art.raw)
        self.assertEqual(art.impulses, (0.,))
        self.assertEqual(art.body, 0)
        self.assertLess(item[4] / 22050, .010)

    def test_renderer_paths_are_equivalent_and_deterministic(self):
        p = WavePreview(); lane = p._plan(orchestra([(0, 37, 100, False), (.20, 53, 100, False)]), 8000)
        a, b = p._render_python(lane, 8000, 1), p._render_numpy(np, lane, 8000, 1)
        np.testing.assert_allclose(a[0], b[0], atol=2e-6)
        np.testing.assert_array_equal(b[0], p._render_numpy(np, lane, 8000, 1)[0])

    def test_plan_is_immutable_and_reinforcement_inherits_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = MidiSource(write_drums(Path(folder)/'song.mid', [(0, .1, 35), (.2, .3, 37), (.4, .5, 44)]))
            config = default_orchestra(hdd_count=4)
            config.idle_reinforcement = parse_idle({'enabled': True})
            plan = allocate(source, config)
            played = [e for e in plan.events if e.played and e.device_type == 'HDD_VCM']
            e = played[0]
            plan.reinforcements.append(ReinforcementEvent(e.id, 'hdd_vcm-4', e.actual_start, .105, 0, e.velocity, kind='hit'))
            before = [dataclasses.asdict(e) for e in plan.events]
            for mode in ('raw', 'articulated'):
                o = VirtualOrchestra(); o.hdd_mode = mode; o.render_plan(plan)
                extras = [a for a in o.events if a.reinforcement and a.kind=='hit']
                primary = next(a for a in o.events if a.source_id==e.id and not a.reinforcement)
                self.assertEqual(extras[0].hdd_articulation, primary.hdd_articulation)
                WavePreview()._plan(o, int((plan.duration+1)*22050))
                self.assertEqual(before, [dataclasses.asdict(e) for e in plan.events])

    def test_four_hdds_are_interchangeable_pool(self):
        with tempfile.TemporaryDirectory() as folder:
            # Same kick repeatedly while preferred drive is busy; any free actuator can play it.
            notes = [(start, start+.1, 35) for start in (0, .02, .04, .06, 1.)]
            source = MidiSource(write_drums(Path(folder)/'song.mid', notes))
            plan = allocate(source, default_orchestra(hdd_count=4))
            hits = [e for e in plan.events if e.played]
            self.assertEqual(len(hits), 5)
            self.assertEqual(len({e.device_id for e in hits[:4]}), 4)
            self.assertEqual({classify(e.note, e.channel, e.velocity).kind for e in hits}, {'HARD_HIT'})
            self.assertTrue(any(e.outcome == 'REASSIGNED' for e in hits))
