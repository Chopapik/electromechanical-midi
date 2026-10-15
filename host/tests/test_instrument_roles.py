"""The preset uses existing allocation and mechanical validation end to end."""
import unittest
from unittest.mock import patch

import test_mechanical_arrangement as helpers
from runtime.arranger import arrange
from runtime.application import Application
from runtime.compiler import compile_plan
from playback.instrument_roles import PRESET


class InstrumentRolesTests(unittest.TestCase):
    setUp = helpers.MechanicalArrangementTests.setUp
    source = helpers.MechanicalArrangementTests.source
    registry = helpers.MechanicalArrangementTests.registry
    plan = helpers.MechanicalArrangementTests.plan
    assert_feasible = helpers.MechanicalArrangementTests.assert_feasible

    def selected(self, **counts):
        r = self.registry(**counts)
        r.document['parameters']['arrangementPreset'] = PRESET
        return r

    def test_riff_and_sustained_bed_share_the_orchestra(self):
        tracks = [('Riff', 0, [(i*.2, i*.2+.15, 60+i%5) for i in range(12)]),
                  ('Pad', 1, [(0, 3, 48), (0, 3, 55), (0, 3, 60)])]
        r = self.selected()
        p = self.plan(tracks, r)
        self.assertTrue(all(e.device_type == 'FDD' for e in p.events if e.track_name == 'Riff'))
        self.assertTrue(all(e.device_type == 'DVD_SLED' and e.actual_duration == 3
                            for e in p.events if e.track_name == 'Pad'))
        self.assert_feasible(p, r)

    def test_equal_gates_choose_by_pitch_changes_instead_of_note_density(self):
        for changing, kind in ((False, 'DVD_SLED'), (True, 'FDD')):
            with self.subTest(changing=changing):
                p = self.plan([('Part', 0, [(i*.5, i*.5+.48, 60+i%3 if changing else 60)
                                            for i in range(8)])], self.selected())
                self.assertTrue(all(e.played and e.device_type == kind for e in p.events))

    def test_repeated_chord_is_not_a_fast_melodic_line(self):
        tracks = [('Pad', 0, [(i*.6, i*.6+.5, note) for i in range(6) for note in (48, 55, 60)])]
        p = self.plan(tracks, self.selected())
        self.assertTrue(all(e.device_type == 'DVD_SLED' for e in p.events))
        self.assertTrue(all(e.hardware['selection']['pitchChangesPerSecond'] == 0 for e in p.events))

    def test_longer_background_wins_over_shorter_simultaneous_layer(self):
        tracks = [('Short layer', 0, [(0, 6, n) for n in (38, 45, 50)]),
                  ('Long background', 1, [(0, 12, n) for n in (38, 45, 50)])]
        r = self.selected(dvd=3)
        p = self.plan(tracks, r)
        background = [e for e in p.events if e.track_name == 'Long background']
        self.assertTrue(all(e.device_type == 'DVD_SLED' and e.end == 12 for e in background))
        self.assertTrue(all(e.device_type == 'FDD' and e.actual_duration <= .4
                            for e in p.events if e.track_name == 'Short layer'))
        tones = [c for c in compile_plan(p).commands if c.kind == 'tone' and c.device_id.startswith('DVD')]
        self.assertEqual(len([c for c in tones if c.time <= 6 and c.time+c.duration >= 12]), 3)
        self.assert_feasible(p, r)

    def test_stable_inner_voice_is_independent_of_fast_upper_riff(self):
        notes = [(i*.6, i*.6+.5, 48) for i in range(8)]
        notes += [(i*.2, i*.2+.15, 67+i%4) for i in range(24)]
        r = self.selected()
        p = self.plan([('Layered guitar', 0, notes)], r)
        low = [e for e in p.events if e.note == 48]
        high = [e for e in p.events if e.note >= 67]
        self.assertTrue(all(e.device_type == 'DVD_SLED' for e in low))
        self.assertTrue(all(e.hardware['selection']['pitchChangesPerSecond'] == 0 for e in low))
        self.assertTrue(all(e.device_type == 'FDD' for e in high))
        self.assert_feasible(p, r)

    def test_real_background_pause_remains_silent(self):
        r = self.selected()
        r.document['parameters'].update(sourceContinuity=True, dvdContinuousSustain=True)
        p = self.plan([('Background', 0, [(0, 2, 48), (5, 7, 48)])], r)
        dvd = [e for e in p.events if e.played and e.device_type == 'DVD_SLED']
        self.assertEqual(len(dvd), 2)
        self.assertEqual([(e.actual_start, e.end) for e in dvd], [(0, 2), (5, 7)])
        self.assertFalse(any(c.kind == 'tone' and c.time < 5 and c.time+c.duration > 2
                             for c in compile_plan(p).commands))

    def test_doubled_attack_does_not_block_an_independent_riff(self):
        tracks = [('Short double', 0, [(0, .35, 60)]),
                  ('Sustained layer', 1, [(0, 4, 60)]),
                  ('Independent riff', 2, [(.05, .35, 64)])]
        r = self.selected(fdd=1, dvd=1)
        p = self.plan(tracks, r)
        self.assertTrue(all(e.played for e in p.events))
        double = next(e for e in p.events if e.track_name == 'Short double')
        self.assertEqual(double.start, 0)
        self.assertLessEqual(double.actual_duration, .08)
        riff = next(e for e in p.events if e.track_name == 'Independent riff')
        self.assertEqual(riff.device_type, 'FDD')
        self.assertLessEqual(riff.actual_start-riff.start, p.policy['maxArpeggioMs']/1000)
        self.assert_feasible(p, r)

    def test_spare_dvd_is_not_wasted_on_a_shorter_duplicate_layer(self):
        tracks = [('Short double', 0, [(0, 6, 38)]),
                  ('Long backgrounds', 1, [(0, 12, 38), (0, 13, 45), (0, 14, 50)])]
        r = self.selected(fdd=1, dvd=3)
        p = self.plan(tracks, r)
        self.assertTrue(all(e.device_type == 'DVD_SLED' and e.end == e.start+e.duration
                            for e in p.events if e.track_name == 'Long backgrounds'))
        double = next(e for e in p.events if e.track_name == 'Short double')
        self.assertEqual(double.device_type, 'FDD')
        self.assertTrue(double.hardware['selection']['coveredByDvd'])
        self.assert_feasible(p, r)

    def test_missing_or_busy_preferred_family_falls_back(self):
        for counts, notes, kind in [({'dvd': 0}, [(0, 3, 60)], 'FDD'),
                                    ({'fdd': 0}, [(0, .15, 60)], 'DVD_SLED'),
                                    ({'dvd': 1, 'fdd': 1}, [(0, 3, 60), (0, 3, 64)], None)]:
            r = self.selected(**counts)
            p = self.plan([('Part', 0, notes)], r)
            self.assertTrue(all(e.played for e in p.events))
            if kind:
                self.assertTrue(all(e.device_type == kind for e in p.events))
            else:
                self.assertEqual({e.device_type for e in p.events}, {'FDD', 'DVD_SLED'})
            self.assert_feasible(p, r)

    def test_source_continuity_cannot_restore_long_fdd_fallback_holds(self):
        r = self.selected(dvd=0)
        r.document['parameters'].update(mechanicalSustain=True, sourceContinuity=True,
                                       minMechanicalSustainMs=800, preferredMechanicalSustainMs=1000)
        p = self.plan([('Pad', 0, [(0, 8, 60)])], r)
        event = p.events[0]
        self.assertTrue(event.played)
        self.assertEqual(event.device_type, 'FDD')
        self.assertEqual(event.start, 0)
        self.assertEqual(event.duration, 8)
        self.assertLessEqual(event.actual_duration, .4)

    def test_percussion_schedule_is_identical_and_plan_is_deterministic(self):
        tracks = [('Riff', 0, [(i*.2, i*.2+.15, 60+i%3) for i in range(12)]),
                  ('Drums', 9, [(i*.25, i*.25+.1, 36+i%3*3) for i in range(12)])]
        r = self.registry()
        source = self.source(tracks)
        before = arrange(source, r)
        r.document['parameters']['arrangementPreset'] = PRESET
        after = arrange(source, r)
        self.assertEqual([c for c in compile_plan(before).commands if c.kind == 'hit'],
                         [c for c in compile_plan(after).commands if c.kind == 'hit'])
        self.assertEqual(compile_plan(after), compile_plan(arrange(source, r)))

    def test_speaker_vocal_and_fx_routing_stays_in_separate_pools(self):
        import mido
        from pathlib import Path
        from midi_source import MidiSource
        from runtime.registry import DeviceRegistry
        midi = mido.MidiFile(ticks_per_beat=480)
        for channel, program, pitch, name in [(0, 26, 60, 'Lead Vocal'), (1, 73, 80, 'Ornaments')]:
            track = mido.MidiTrack([mido.MetaMessage('track_name', name=name),
                                   mido.Message('program_change', channel=channel, program=program)])
            midi.tracks.append(track)
            for i in range(24):
                track.append(mido.Message('note_on', channel=channel, note=pitch+i%3, velocity=90, time=240 if i else 0))
                if channel == 0:
                    track.append(mido.MetaMessage('lyrics', text='word'+str(i)))
                track.append(mido.Message('note_off', channel=channel, note=pitch+i%3, time=240))
        path = Path(self.tmp.name)/'vocal.mid'
        midi.save(path)
        source = MidiSource(path)
        r = DeviceRegistry()
        before = arrange(source, r)
        r.document['parameters']['arrangementPreset'] = PRESET
        after = arrange(source, r)
        speaker = lambda p: [c for c in compile_plan(p).commands
                             if c.device_id in ('vhs-1', 'pc-speaker-fx')]
        self.assertEqual(speaker(before), speaker(after))
        self.assertTrue(all(e.device_id == 'vhs-1' for e in after.events if e.track == 0))
        if 'pc-speaker-fx' in r.by_id:
            self.assertTrue(all(e.device_id == 'pc-speaker-fx' for e in after.events if e.track == 1))

    def test_switch_rebuilds_shared_timeline_without_resuming(self):
        app = Application(self.registry())
        app.load(self.source([('Part', 0, [(0, 3, 60)])]).path)
        original = arrange
        def check_stopped(*args):
            self.assertEqual(app.player.state, 'stopped')
            return original(*args)
        with patch('runtime.application.arrange', side_effect=check_stopped):
            app.set_preset(PRESET)
        self.assertEqual(app.plan.policy['arrangementPreset'], PRESET)
        self.assertEqual(app.timeline, compile_plan(app.plan))
        before = app.timeline
        app.router.switch('VIRTUAL')
        self.assertEqual(before, app.timeline)
        self.assertFalse(app.plan.policy['fddUnisonEnabled'])


if __name__ == '__main__':
    unittest.main()
