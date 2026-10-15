"""Noise trigger keys must never become harmonic motor/speaker notes."""
import sys
import tempfile
import unittest
from pathlib import Path

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_source import MidiSource
from playback.analysis import analyze
from playback.allocator import allocate, ManualPin
from playback.duplicates import normalize
from playback.orchestra import default_orchestra
from playback.sound_roles import GM_NOISE, source_effects, UNPITCHED_EFFECT, UNSUPPORTED_EFFECT
from playback.strict_tracks import allocate_strict
from runtime.arranger import arrange
from runtime.compiler import compile_plan
from runtime.registry import DeviceRegistry


def phrase(channel, program, count=24):
    track = mido.MidiTrack([mido.Message('program_change', channel=channel, program=program)])
    for i in range(count):
        track.extend([
            mido.Message('note_on', channel=channel, note=60+i%3, velocity=90, time=240),
            mido.Message('note_off', channel=channel, note=60+i%3, time=240),
        ])
    return track


class UnpitchedEffectsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'sounds.mid'

    def source(self, *tracks):
        midi = mido.MidiFile(ticks_per_beat=480)
        midi.tracks.extend(tracks)
        midi.save(self.path)
        return MidiSource(self.path)

    def test_noise_cannot_become_lead_bass_or_tone_even_when_named_vocal(self):
        for program, name in GM_NOISE.items():
            with self.subTest(program=program):
                track = phrase(0, program)
                track.insert(0, mido.MetaMessage('track_name', name='Lead Vocal'))
                source = self.source(track)
                analysis = analyze(source)
                self.assertIsNone(analysis.lead_track)
                self.assertIsNone(analysis.bass_track)
                self.assertEqual(analysis.classifications[0].final_role, 'UNPITCHED_EFFECT')
                self.assertEqual(set(analysis.unpitched_effects.values()), {name})
                plan = arrange(source, DeviceRegistry())
                self.assertEqual(len(plan.events), 24)
                self.assertTrue(all(e.reason == UNSUPPORTED_EFFECT and not e.played for e in plan.events))
                self.assertFalse(compile_plan(plan).commands)
                self.assertFalse(plan.reinforcements)
                self.assertFalse(plan.tray_events)
                self.assertEqual(plan.report()['tonal']['requested'], 0)
                self.assertEqual(plan.report()['unpitchedEffects']['omitted'], 24)

    def test_pitched_fx_and_percussion_are_not_blanket_filtered(self):
        for program in (80, 96, 103, 112, 114, 115, 117, 118, 123, 124):
            with self.subTest(program=program):
                source = self.source(phrase(0, program))
                self.assertFalse(source_effects(source))
                self.assertTrue(any(e.played for e in arrange(source, DeviceRegistry()).events))
        source = self.source(phrase(9, 127))
        self.assertFalse(source_effects(source))
        self.assertTrue(all(e.device_type == 'HDD_VCM' for e in arrange(source, DeviceRegistry()).events if e.played))

    def test_channel_program_changes_cross_tracks_and_latch_at_note_on(self):
        # C4 starts before the noise program at this same tick; D4 after it.
        notes = mido.MidiTrack([
            mido.Message('note_on', note=60, velocity=90),
            mido.Message('program_change', program=122),
            mido.Message('note_on', note=62, velocity=90),
            mido.Message('note_off', note=60, time=480),
            mido.Message('note_off', note=62),
            mido.Message('note_on', note=64, velocity=90, time=480),
            mido.Message('note_off', note=64, time=480),
        ])
        # Program change on another track, before the third NOTE_ON.
        conductor = mido.MidiTrack([mido.Message('program_change', program=80, time=720)])
        source = self.source(notes, conductor)
        self.assertEqual(source.note_programs(), {(0, 0): 0, (0, 1): 122, (0, 2): 80})
        self.assertEqual(source_effects(source), {'0:1': 'Seashore'})
        plan = arrange(source, DeviceRegistry())
        self.assertEqual([e.id for e in plan.events if e.reason == UNSUPPORTED_EFFECT], ['0:1'])

    def test_bank_select_applies_only_on_program_change_and_unknown_bank_is_not_guessed(self):
        track = mido.MidiTrack([
            mido.Message('program_change', program=122),
            mido.Message('control_change', control=0, value=8),
            mido.Message('note_on', note=60, velocity=90),
            mido.Message('note_off', note=60, time=480),
            mido.Message('program_change', program=122),
            mido.Message('note_on', note=62, velocity=90),
            mido.Message('note_off', note=62, time=480),
        ])
        source = self.source(track)
        self.assertEqual(source.note_programs(), {(0, 0): 122, (0, 1): None})
        self.assertEqual(source_effects(source), {'0:0': 'Seashore'})

    def test_noise_layer_is_not_a_tonal_duplicate(self):
        source = self.source(phrase(0, 121), phrase(1, 45), phrase(2, 45))
        normalized = normalize(source)
        self.assertEqual(len(normalized.tracks), 2)  # strings still deduplicate
        self.assertEqual(len(source_effects(normalized)), 24)
        plan = arrange(source, DeviceRegistry())
        self.assertTrue(all(not e.played for e in plan.events if e.track == 0))
        self.assertTrue(any(e.played for e in plan.events if e.track != 0))

    def test_legacy_manual_pins_and_adaptive_rescue_cannot_reintroduce_noise(self):
        source = self.source(phrase(0, 122), phrase(1, 0))
        config = default_orchestra()
        pin = ManualPin(device_id=config.devices[0]['id'], rule_id='test-pin')
        legacy = allocate(normalize(source), config, pins={'0:0': pin})
        self.assertEqual(next(e for e in legacy.events if e.id == '0:0').reason, UNSUPPORTED_EFFECT)
        for preset in ('balanced', 'fdd_quality', 'dvd_lead_low_fdd'):
            with self.subTest(preset=preset):
                registry = DeviceRegistry()
                registry.document['parameters']['arrangementPreset'] = preset
                plan = arrange(source, registry)
                self.assertTrue(all(e.role == UNPITCHED_EFFECT and not e.played
                                    for e in plan.events if e.track == 0))
                self.assertEqual(compile_plan(plan), compile_plan(arrange(source, registry)))

    def test_strict_track_mapping_also_rejects_noise(self):
        source = self.source(phrase(0, 127))
        config = default_orchestra()
        config.devices = [d for d in config.devices if d['type'] == 'FDD']
        plan = allocate_strict(source, config, [0, None, None, None])
        self.assertTrue(all(e.reason == UNSUPPORTED_EFFECT for e in plan.events))
        self.assertFalse(compile_plan(plan).commands)

    def test_noise_does_not_reserve_voices_or_change_tonal_schedule(self):
        registry = DeviceRegistry()
        source = self.source(phrase(0, 122), phrase(1, 0), phrase(2, 33))
        with_noise = compile_plan(arrange(source, registry))
        source = self.source(mido.MidiTrack(), phrase(1, 0), phrase(2, 33))
        without_noise = compile_plan(arrange(source, registry))
        self.assertTrue(with_noise.commands)
        self.assertEqual(with_noise.commands, without_noise.commands)


if __name__ == '__main__':
    unittest.main()
