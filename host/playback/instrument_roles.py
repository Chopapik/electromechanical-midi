"""Optional timbre allocation: moving riffs on FDD, sustained beds on DVD."""
import statistics
from collections import defaultdict

PRESET = 'instrument_roles'
PRESETS = (PRESET, 'instrument_roles_unison', 'instrument_roles_duet')
# Musical gate for a long note that must fall back to FDD; not a safety rating.
FDD_MAX_HOLD_S = .4
FDD_SHADOW_HOLD_S = .08


def enabled(policy):
    return policy.get('arrangementPreset') in PRESETS


def contexts(notes, window):
    """Follow non-overlapping melodic voices within each track/channel.

    A stationary inner voice must not inherit the motion of its upper riff.
    Match closest pitches at each onset, using each voice at most once.
    """
    lanes = defaultdict(lambda: defaultdict(list))
    for item in notes:
        if item['role'] != 'percussion':
            lanes[item['track'], item['span'].channel][item['span'].start].append(item)
    result = {}
    for groups in lanes.values():
        voices = []
        for start in sorted(groups):
            group = sorted(groups[start], key=lambda i: (i['span'].note, i['order']))
            pairs = sorted((abs(item['span'].note-voice[-1]['span'].note), v, n)
                           for v, voice in enumerate(voices)
                           if voice[-1]['span'].end <= start+1e-9
                           for n, item in enumerate(group))
            used_voices, used_notes = set(), set()
            for _, v, n in pairs:
                if v not in used_voices and n not in used_notes:
                    voices[v].append(group[n])
                    used_voices.add(v)
                    used_notes.add(n)
            voices.extend([item] for n, item in enumerate(group) if n not in used_notes)
        for voice_id, voice in enumerate(voices):
            for index, item in enumerate(voice):
                start = item['span'].start
                nearby = [i for i in voice[max(0, index-2):index+3]
                          if abs(i['span'].start-start) <= window]
                transitions = list(zip(nearby, nearby[1:]))
                changed = sum(a['span'].note != b['span'].note for a, b in transitions)
                change_rate = changed / (nearby[-1]['span'].start-nearby[0]['span'].start) if transitions else 0.
                repeats = 1-changed/len(transitions) if transitions else 0.
                mean = statistics.fmean(i['span'].duration for i in nearby)
                duration = item['span'].duration
                clamp = lambda x: max(-1., min(1., x))
                sustain = clamp(.7*clamp((duration-.35)/.45)
                                + .3*clamp((mean-.4)/.6) - .9*min(1., change_rate/4.))
                if duration >= .65:
                    sustain = max(.7, sustain)
                elif duration <= .3 or change_rate >= 2. and duration <= .6:
                    sustain = min(-.65, sustain)
                elif duration < .45:
                    # Leave DVD lanes for actual beds, even for repeated keys.
                    sustain = min(-.35, sustain)
                elif repeats >= .8:
                    sustain = max(.65, sustain)
                result[item['id']] = {'sustainAffinity': sustain,
                    'voiceId': voice_id,
                    'pitchChangesPerSecond': round(change_rate, 3),
                    'preferredType': 'DVD_SLED' if sustain >= 0 else 'FDD'}
    return result


def prioritize(notes, context, fx_tracks=(), pins=None):
    """At a shared pitch/attack, reserve DVD for the longest background layer.

    Only accompaniment positions are reordered. Vocal/FX, percussion and
    explicit manual rules retain their positions and independent pools.
    """
    result = list(notes)
    attacks = defaultdict(list)
    for index, item in enumerate(notes):
        if (item['role'] in ('bass', 'harmony') and item['track'] not in fx_tracks
                and item['id'] not in (pins or {})):
            attacks[item['span'].start, item['role'], item['span'].note].append(index)
    for indices in attacks.values():
        def key(item):
            background = context[item['id']]['preferredType'] == 'DVD_SLED'
            duration = item['span'].duration
            return (not background, -duration if background else duration,
                    item['track'], item['order'])
        ordered = sorted((notes[i] for i in indices), key=key)
        for index, item in zip(indices, ordered):
            result[index] = item
    return result


def preference(profile, context, covered=False):
    if profile.name not in ('FDD', 'DVD_SLED'):
        return 0., None
    if covered:
        bonus = 3. if profile.name == 'FDD' else -3.
        return bonus, {**context, 'coveredByDvd': True, 'preferredType': 'FDD',
            'preferenceScore': bonus, 'reason': 'FDD attack over an existing DVD sustain'}
    bonus = 3.*context['sustainAffinity']*(1 if profile.name == 'DVD_SLED' else -1)
    return bonus, {**context, 'preferenceScore': round(bonus, 4),
        'reason': 'FDD riffs + DVD tło: ' + ('sustained background' if context['sustainAffinity'] >= 0
                                           else 'short notes / changing pitches')}


def held_background(span, events):
    return any(e.played and e.device_type == 'DVD_SLED' and e.note == span.note
               and e.actual_start <= span.start+1e-9 and e.end >= span.end-1e-9
               for e in events)


def fdd_gate(duration, covered):
    """A duplicate attack need not hold a voice already sustained on DVD."""
    if covered:
        return min(duration, FDD_SHADOW_HOLD_S)
    return min(duration, FDD_MAX_HOLD_S)
