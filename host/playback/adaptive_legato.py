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


PAIR_UNISON = 'FDD_PAIR_UNISON'


def pair_unison(plan, registry):
    """Mirror whole tones within a fixed pair, never adding an independent voice.

    Keep every primary unchanged. Missing partners and physical vetoes remain
    visible as single voices; they never trigger an alternative pitch or onset.
    """
    from collections import Counter
    from .capabilities import capabilities_for
    from .mechanical_arrangement import ChronologyCache
    from .performance import ReinforcementEvent
    from .planning_context import append_extra

    report = {'mode': 'fixed_pair_unison', 'copies': 0, 'unpairedPrimaryNotes': 0,
              'rejected': {}, 'primaryDropsAdded': 0}
    plan.hardware['adaptiveLegato']['pairUnison'] = report
    config = registry.configuration()
    primary = defaultdict(list)
    for event in plan.events:
        if event.played and event.device_type == 'FDD':
            primary[event.device_id].append(event)
    total = sum(map(len, primary.values()))
    if not config.policy['fddUnisonEnabled'] or config.policy['fddUnisonMaxVoices'] < 2:
        report.update(unpairedPrimaryNotes=total, rejected={'userDisabled': total})
        return
    caps = capabilities_for(config.instances())
    rejected = Counter()
    interval = plan.policy['fddMinAttackIntervalMs']/1000.
    for group in plan.internal_context.fdd_groups:
        if len(group) != 2:
            rejected['missingPartner'] += sum(len(primary[d]) for d in group)
            continue
        for target, source in (group, tuple(reversed(group))):
            events = sorted(primary[source], key=lambda e: (e.actual_start, e.id))
            chronology = ChronologyCache(registry.profile(target))
            extras = [e for e in plan.reinforcements if e.device_id == target]
            baseline = chronology.check(primary[target], extras)
            if baseline is None:
                raise ValueError('Adaptive Legato: invalid primary chronology '+target)
            scores = {e.id: baseline[e.id].score for e in primary[target]}
            copies = []
            for event in events:
                cap = caps[target]
                if not cap.min_hz <= event.played_hz <= cap.max_hz:
                    rejected['frequency'] += 1
                    continue
                copies.append(ReinforcementEvent(event.id, target, event.actual_start,
                    event.actual_duration, event.played_hz, event.velocity, kind=PAIR_UNISON,
                    source_device=source, reason='complete fixed-pair unison',
                    semantic_compatibility='identical pitch, onset, gate and source voice', role=event.role))

            def feasible(additions):
                attacks = sorted([e.actual_start for e in primary[target]]+
                                 [e.start for e in extras+additions])
                if any(b-a < interval-1e-9 for a,b in zip(attacks,attacks[1:])):
                    return False
                evaluation = chronology.check(primary[target], extras+additions)
                return evaluation is not None and all(
                    evaluation[ident].score+1e-9 >= score for ident,score in scores.items())

            if not feasible(copies):
                accepted = []
                for extra in copies:
                    if feasible(accepted+[extra]):
                        accepted.append(extra)
                    else:
                        rejected['physicalVeto'] += 1
                copies = accepted
            for extra in copies:
                append_extra(plan, extra, {
                    **plan.execution_articulation[extra.source_id], 'gate': extra.duration})
            report['copies'] += len(copies)
    report.update(unpairedPrimaryNotes=total-report['copies'], rejected=dict(rejected))
