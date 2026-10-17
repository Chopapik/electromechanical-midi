import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_source import MidiSource
from pitch import fold_note, midi_to_hz
from runtime.registry import DeviceRegistry
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from playback.mechanical_arrangement import _chronology
from test_allocator import write_tracks


class FddOctaveExperimentTests(unittest.TestCase):
    def test_all_four_drives_shift_source_and_working_register(self):
        r = DeviceRegistry()
        active = [d for d in r.devices if d['type']=='FDD' and d['enabled']]
        self.assertEqual([d['id'] for d in active], [f'fdd-{i}' for i in range(1,5)])
        for d in active:
            self.assertEqual(d['transpose'], -12)
            self.assertEqual(d['overrides']['preferredMinHz']['value'], 100)
            self.assertEqual(d['overrides']['preferredMaxHz']['value'], 205)
            p = r.profile(d['id'])
            self.assertEqual(p.get('musicalHz'), [100, 410])
            self.assertEqual(p.get('executionMinStepUs'), 2439)
            self.assertEqual(p.get('travelSteps'), 72)
            for mode in ('auto', 'low', 'high'):
                for note in range(24, 109):
                    before = fold_note(note, 200, 410, mode)
                    after = fold_note(note-12, 100, 205, mode)
                    self.assertAlmostEqual(after.hz, before.hz/2)

    def test_all_presets_strict_unison_and_expression_use_lower_register(self):
        presets = ('balanced', 'fdd_quality', 'fdd_quality_adaptive', 'dvd_lead_low_fdd',
                   'instrument_roles', 'instrument_roles_unison', 'instrument_roles_duet', 'universal')
        with tempfile.TemporaryDirectory() as directory:
            source = MidiSource(write_tracks(Path(directory)/'register.mid',
                [('Riff', 0, [(i*.3, i*.3+.15, 60) for i in range(8)])]))
            for preset in presets:
                for strict in (False, True):
                    with self.subTest(preset=preset, strict=strict):
                        r = DeviceRegistry()
                        for d in r.devices: d['enabled'] = d['type'] == 'FDD' and d['id'] in {f'fdd-{i}' for i in range(1,5)}
                        r.document['parameters']['arrangementPreset'] = preset
                        if strict:
                            r.document['routing'] = {'mode': 'STRICT_TRACKS', 'tracks': [1, None, None, None]}
                        p = arrange(source, r)
                        tones = [c for c in compile_plan(p).commands if c.kind == 'tone']
                        self.assertTrue(tones)
                        for c in tones:
                            self.assertAlmostEqual(c.hz, midi_to_hz(48))
                            if c.articulation:
                                self.assertTrue(all(abs(hz-c.hz)<1e-6 for hz in c.articulation['frequency']['values']))
                        self.assertTrue(all(e.note == 60 for e in p.events))
                        for d in r.devices:
                            if d['type'] != 'FDD': continue
                            self.assertIsNotNone(_chronology(r.profile(d['id']),
                                [e for e in p.events if e.played and e.device_id == d['id']],
                                [e for e in p.reinforcements if e.device_id == d['id']]))
