"""Experimental rhythmic gates and optional two-drive attack envelopes.

Musical planning only: no GPIO, generated notes, weakened physical limits or
random onset shifts. The second drive reinforces an existing source attack.
"""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import replace
from statistics import median
from types import SimpleNamespace

from .hardware_profiles import min_note_ms
from .instrument_roles import contexts

PRESET = 'fdd_expressive'


class Phrases:
    def __init__(self, events, source, policy):
        from .fdd_quality import musical_values
        from .mechanical_arrangement import phrase_context
        items = [{'id': e.id, 'track': e.track, 'role': e.role, 'order': i,
                  'span': SimpleNamespace(start=e.start, end=e.start+e.duration,
                      duration=e.duration, note=e.note, channel=e.channel, velocity=e.velocity)}
                 for i, e in enumerate(events)]
        window = policy['mechanicalPhraseWindowMs']/1000.
        voices = contexts(items, window)
        self.accents = musical_values(items, phrase_context(items, window), source)
        self.tempos = getattr(source, 'source', source).tempo._segments
        self.times = [s.seconds for s in self.tempos]
        self.next = {}
        velocities = defaultdict(list)
        lines = defaultdict(list)
        for e in events:
            velocities[e.track, e.channel].append(e.velocity)
            lines[e.track, e.channel, voices[e.id]['voiceId']].append(e)
        self.levels = {part: median(values) for part, values in velocities.items()}
        for line in lines.values():
            line.sort(key=lambda e: (e.start, e.id))
            for a, b in zip(line, line[1:]):
                self.next[a.id] = b.start

    def accent(self, event):
        a = self.accents[event.id]
        return event.velocity >= 64 and (a['phraseEntry'] or a['downBeat'] or
            event.velocity >= self.levels[event.track, event.channel]+10)

    def gate(self, event, hz, profile, minimum, covered, release):
        beat = self.tempos[max(0, bisect_right(self.times, event.start)-1)].tempo/1e6
        floor = max(minimum, (min_note_ms(profile, hz) or 0)/1000., 6./hz)
        following = self.next.get(event.id, float('inf'))-event.start
        room = following-release
        if room < floor-1e-9:
            return None
        # Fit the source articulation and cadence; short gates may need enough
        # cycles to form a tone. Long sustained bodies belong on DVD.
        gate = max(floor, min(event.duration, .18, beat*.45, following*.8))
        if covered:
            gate = min(gate, max(floor, .08))
        return min(gate, room)

    @staticmethod
    def accent_gate(primary, profile, minimum):
        floor = max(minimum, (min_note_ms(profile, primary.played_hz) or 0)/1000.,
                    4./primary.played_hz)
        if floor > primary.actual_duration+1e-9:
            return None
        return min(primary.actual_duration, max(floor, primary.actual_duration*.55))


def finalize(plan):
    """A rejected optional copy never rejects the primary; orphans cannot play."""
    report = plan.hardware.get('fddExpressive')
    if report is None:
        return
    sources = {e.id: e for e in plan.events}
    extras, articulation = [], {k: v for k, v in plan.execution_articulation.items()
                                if not k.startswith('extra:')}
    for index, extra in enumerate(plan.reinforcements):
        if extra.kind == 'FDD_ACCENT':
            source = sources.get(extra.source_id)
            if (not source or not source.played or source.device_type != 'FDD'
                    or abs(source.actual_start-extra.start) > 1e-9
                    or abs(source.played_hz-extra.hz) > 1e-6):
                continue
            extra = replace(extra, duration=min(extra.duration, source.actual_duration))
        art = plan.execution_articulation.get('extra:'+str(index))
        if art is not None:
            articulation['extra:'+str(len(extras))] = ({**art, 'gate': extra.duration}
                if extra.kind == 'FDD_ACCENT' else art)
        extras.append(extra)
    plan.reinforcements = extras
    plan.execution_articulation = articulation
    primaries = [e for e in plan.events if e.played and e.device_type == 'FDD']
    accents = [e for e in extras if e.kind == 'FDD_ACCENT']
    report.update(primaryNotes=len(primaries), accentCopies=len(accents),
        singleDriveNotes=len(primaries)-len(accents),
        gateRangeMs=[min((e.actual_duration for e in primaries), default=0)*1000,
                     max((e.actual_duration for e in primaries), default=0)*1000])
