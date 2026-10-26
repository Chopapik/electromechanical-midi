"""Local, source-relative articulation; heuristics, not an acoustic quality score.

Analysis uses source gates/pitches before phrase reduction. No filename rules or
cross-device routing: speakers, DVD and HDD keep the Expressive allocation.
"""
from bisect import bisect_left, bisect_right
from collections import defaultdict

PRESET = 'adaptive_legato'


class Articulation:
    def __init__(self, pool, clock):
        self.protected = set()
        self.evidence = {}
        self.clock = clock
        parts = defaultdict(list)
        for group, events in pool.items():
            for event in events:
                parts[group, event.track, event.channel].append(event)
        for events in parts.values():
            events.sort(key=lambda e: (e.start, e.id))
            times = [e.start for e in events]
            for event in events:
                beat = clock.beat(event.start)
                # Two beats either side: bounded local evidence, not whole-song
                # labels. Same logical voice/part only; chords do not vote.
                local = events[bisect_left(times, event.start-2*beat):
                               bisect_right(times, event.start+2*beat)]
                pairs = [(a, b) for a, b in zip(local, local[1:])
                         if 1e-9 < b.start-a.start <= beat]
                detached = sum(a.duration <= .8*(b.start-a.start) for a,b in pairs)
                repeated = sum(a.note == b.note for a,b in pairs)
                short = event.duration <= .6*beat
                rhythmic = short and len(pairs) >= 2 and (
                    detached/len(pairs) >= .5 or repeated/len(pairs) >= .5)
                if rhythmic:
                    self.protected.add(event.id)
                self.evidence[event.id] = 'rhythmic' if rhythmic else 'flowing'

    def gap(self, event):
        # Audible separation experiment; never shorten the physical tone floor.
        return min(.060, max(.030, self.clock.beat(event.start)*.08))

    def is_protected(self, event):
        return event.id in self.protected

    def report(self):
        return {'version': 1, 'protectedSourceAttacks': len(self.protected),
                'flowingSourceAttacks': len(self.evidence)-len(self.protected),
                'scope': 'local MIDI heuristics; not recognition or acoustic measurement'}
