"""Arrangement routing and note-level diagnostics without an audio device."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_source import MidiSource
from playback.arrangement import Arrangement, ArrangementMismatch, midi_identity
from playback.virtual import VirtualOrchestra


def write_song(path):
    midi = mido.MidiFile(ticks_per_beat=480)
    for name, channel, notes in [
        ('Guitar', 0, [(0, .5, 60, 90), (.2, .6, 72, 100), (.7, 1, 50, 40)]),
        ('Vocal', 1, [(.1, .4, 64, 80)]),
        ('Drums', 9, [(0, .1, 36, 110), (.2, .3, 38, 105), (.4, .5, 42, 50)]),
    ]:
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage('track_name', name=name, time=0))
        events = []
        for start, end, note, velocity in notes:
            events.extend([(round(start * 960), 1, 'note_on', note, velocity),
                           (round(end * 960), 0, 'note_off', note, 0)])
        previous = 0
        for tick, _, kind, note, velocity in sorted(events):
            track.append(mido.Message(kind, channel=channel, note=note, velocity=velocity, time=tick-previous))
            previous = tick
    midi.save(path)


def rule(ident, track, device, **filter_fields):
    return {'id': ident, 'source': {'track': track, **filter_fields},
            'destination': {'deviceId': device}, 'transform': {}}

class ArrangementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'song.mid'
        write_song(self.path)
        self.source = MidiSource(self.path)
        self.devices = [{'id': 'fdd', 'type': 'FDD'}, {'id': 'stepper', 'type': 'STEPPER_FREE'},
                        {'id': 'hdd', 'type': 'HDD_VCM'}]

    def tearDown(self): self.tmp.cleanup()

    def document(self, rules):
        return {'schemaVersion': 1, 'midi': midi_identity(self.source), 'name': 'Test',
                'devices': self.devices, 'rules': rules}

    def simulate(self, rules):
        arrangement = Arrangement.parse(self.document(rules), self.source)
        routes, notes = arrangement.route(self.source)
        orchestra = VirtualOrchestra(arrangement.devices)
        orchestra.simulate(self.source, routes)
        return arrangement, routes, notes, orchestra

    def test_schema_version_and_json_round_trip(self):
        arrangement = Arrangement.parse(self.document([rule('a', 0, 'fdd')]), self.source)
        copy = Arrangement.parse(json.loads(json.dumps(arrangement.as_dict())), self.source)
        self.assertEqual(copy.as_dict(), arrangement.as_dict())
        with self.assertRaisesRegex(ValueError, 'schemaVersion'):
            Arrangement.parse({**self.document([]), 'schemaVersion': 2}, self.source)

    def test_track_name_and_fingerprint_mismatch(self):
        doc = self.document([])
        doc['midi']['tracks'][1]['name'] = 'Other guitar'
        doc['midi']['sha256'] = 'bad'
        with self.assertRaises(ArrangementMismatch) as caught:
            Arrangement.parse(doc, self.source)
        self.assertEqual({x['kind'] for x in caught.exception.mismatches}, {'track', 'midi'})

    def test_missing_track_identity_is_rejected(self):
        doc = self.document([])
        del doc['midi']['tracks']
        with self.assertRaisesRegex(ValueError, 'track identities'):
            Arrangement.parse(doc, self.source)

    def test_filters_track_include_exclude_note_and_velocity_range(self):
        _, routes, _, _ = self.simulate([rule('filtered', 0, 'fdd', includeNotes=[60, 72],
            excludeNotes=[72], noteRange={'min': 55, 'max': 65}, velocityRange={'min': 85, 'max': 100})])
        self.assertEqual([n.note for n in routes['fdd']], [60])

    def test_one_track_multiple_devices_and_many_tracks_one_device(self):
        _, routes, _, orchestra = self.simulate([
            rule('guitar-fdd', 0, 'fdd'), rule('guitar-stepper', 0, 'stepper'),
            rule('vocal-fdd', 1, 'fdd')])
        self.assertEqual({n.track for n in routes['fdd']}, {0, 1})
        self.assertEqual({n.track for n in routes['stepper']}, {0})
        self.assertEqual(len(routes['fdd']), 4)
        self.assertGreater(orchestra.report['fdd']['dropped'], 0)

    def test_unassigned_is_distinct_from_mechanically_dropped(self):
        _, _, notes, orchestra = self.simulate([rule('guitar-fdd', 0, 'fdd')])
        unassigned = [n for n in notes if n['track'] == 2]
        self.assertTrue(all(n['status'] == 'UNASSIGNED' for n in unassigned))
        self.assertTrue(all(n['id'] not in orchestra.decisions for n in unassigned))
        self.assertTrue(any(result['status'] == 'DROPPED' for results in orchestra.decisions.values() for result in results))

    def test_drum_single_pitch_rule_overrides_broad_rule(self):
        broad = rule('all-drums', 2, 'hdd')
        kick = rule('kick', 2, 'hdd', includeNotes=[36]); kick['articulation'] = 'LEFT_HARD'
        snare = rule('snare', 2, 'hdd', includeNotes=[38]); snare['articulation'] = 'RIGHT_HARD'
        hat = rule('hat-off', 2, None, includeNotes=[42])
        _, routes, notes, orchestra = self.simulate([broad, kick, snare, hat])
        self.assertEqual([n.note for n in routes['hdd']], [36, 38])
        self.assertEqual(next(n for n in notes if n['note'] == 42)['status'], 'UNASSIGNED')
        self.assertEqual(next(n for n in routes['hdd'] if n.note == 38).articulation, 'RIGHT_HARD')
        self.assertIn('2:1', orchestra.decisions)

    def test_range_split_and_transform(self):
        low = rule('low', 0, 'stepper', noteRange={'max': 60})
        high = rule('high', 0, 'fdd', noteRange={'min': 61})
        high['transform'] = {'transpose': -12, 'gate': .5, 'octaveFold': False}
        _, routes, _, orchestra = self.simulate([low, high])
        self.assertEqual([n.note for n in routes['stepper']], [60, 50])
        self.assertEqual([n.note for n in routes['fdd']], [72])
        self.assertEqual(orchestra.decisions[routes['fdd'][0].note_id][0]['playedNote'], 60)

if __name__ == '__main__': unittest.main()
