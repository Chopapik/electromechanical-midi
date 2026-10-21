"""Source-derived rhythmic priorities and stable VCM roles, with shared limits.

Only routes existing MIDI hits. No generated strikes or stronger coil settings.
"""
from bisect import bisect_left
from collections import defaultdict


def family(note, channel):
    if channel != 9:
        return 'tom'
    if note in (35,36): return 'kick'
    if note in (37,38,39,40): return 'snare'
    if note in (42,44,46): return 'hat'
    if note in (49,51,52,55,57,59): return 'cymbal'
    return 'tom'


def priority(item):
    span=item['span']
    return ({'kick':0,'snare':1,'tom':2,'cymbal':3,'hat':4}[family(span.note,span.channel)],
            -span.velocity,item['track'],item['order'])


class Rhythm:
    def __init__(self, notes, devices, lanes):
        ordered=sorted(devices,key=lambda s:int(lanes[s.device.id].split(':')[-1]))
        self.roles={s.device.id: ('kick','snare','hat','tom')[i%4] for i,s in enumerate(ordered)}
        self.attacks=defaultdict(list)
        for item in notes:
            if item['role']=='percussion':
                span=item['span'];self.attacks[family(span.note,span.channel)].append(span.start)
        for starts in self.attacks.values():starts.sort()

    def cost(self, item, ident, arrival, ready_after):
        kind=family(item['span'].note,item['span'].channel)
        owner=self.roles.get(ident)
        cost=0. if kind==owner else .2
        if kind=='cymbal' and owner=='tom':cost=.05
        # Borrowing remains possible, but avoid consuming a lane just before
        # its kick/snare attack when another equally feasible lane exists.
        if owner in ('kick','snare') and kind!=owner:
            starts=self.attacks[owner];i=bisect_left(starts,arrival-1e-9)
            if i<len(starts) and starts[i]<ready_after-1e-9:cost+=1.
        return cost
