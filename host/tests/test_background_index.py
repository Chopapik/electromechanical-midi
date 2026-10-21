"""Indexed DVD reservations must answer exactly like the full allocation history."""
import random
import unittest
from dataclasses import replace

from midi_source import NoteSpan
from playback.instrument_roles import BackgroundIndex, held_background
from playback.performance import PerformanceEvent


class BackgroundIndexTests(unittest.TestCase):
    def event(self, ident, lane, start, end, note):
        return PerformanceEvent(id=ident, track=0, track_name='Pad', note=note,
            name=None, velocity=80, channel=0, start=start, duration=end-start,
            device_id=lane, device_type='DVD_SLED', played_note=note, played_hz=220.,
            actual_start=start, actual_duration=end-start, outcome='ACCEPTED')

    def test_queries_match_history_including_delayed_starts_and_voice_steals(self):
        rng = random.Random(731)
        index = BackgroundIndex()
        history, priorities = [], {}
        lane_end = {f'DVD{i}': 0. for i in range(4)}
        for n in range(100):
            lane = f'DVD{n%4}'
            start = lane_end[lane] + rng.uniform(0., .3)
            end = start + rng.uniform(.2, 3.)
            event = self.event(str(n), lane, start, end, rng.randrange(48, 56))
            history.append(event)
            priorities[event.id] = rng.randrange(10)
            index.put(event)
            if n % 3 == 0:
                event = replace(event, actual_duration=event.actual_duration/2)
                history[-1] = event
                index.put(event)
            lane_end[lane] = event.end
            # Include exact boundaries and times before a delayed reservation.
            times = [start-1e-8, start, event.end, event.end+1e-8]
            times += [rng.uniform(0., max(lane_end.values())) for _ in range(15)]
            for t in times:
                for pitch in (event.note, rng.randrange(48, 56)):
                    span = NoteSpan(t, t+.05, pitch, 80, 0)
                    self.assertEqual(index.covered(span), held_background(span, history))
                expected = min((priorities[e.id] for e in history
                    if e.device_id == lane and e.end > t), default=float('inf'))
                self.assertEqual(index.active_priority(lane, t, priorities), expected)

    def test_shortened_note_no_longer_covers_original_tail(self):
        index = BackgroundIndex()
        event = self.event('a', 'DVD1', 1., 3., 60)
        span = NoteSpan(2., 2.5, 60, 80, 0)
        index.put(event)
        self.assertTrue(index.covered(span))
        index.put(replace(event, actual_duration=.5))
        self.assertFalse(index.covered(span))
