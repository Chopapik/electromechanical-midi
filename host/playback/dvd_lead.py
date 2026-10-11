"""DVD-led experimental strategy; costs reuse the physical FDD model."""
from pitch import midi_to_hz
from .fdd_quality import diagnostics as fdd_diagnostics

PRESET = 'dvd_lead_low_fdd'

def enabled(policy):
    return policy.get('arrangementPreset') == PRESET


def fdd_pitch(note, minimum, maximum):
    """One explicit octave only, then original pitch. Never fold or clamp."""
    lower = midi_to_hz(note - 12)
    if minimum <= lower <= maximum:
        return note - 12, lower, True
    return note, midi_to_hz(note), False


def diagnostics(plan):
    result = fdd_diagnostics(plan)
    played = [e for e in plan.events if e.played]
    fdd = [e for e in played if e.device_type == 'FDD']
    dvd = [e for e in played if e.device_type == 'DVD_SLED']
    result.update(dvdNotes=len(dvd), dvdSeconds=round(sum(e.actual_duration for e in dvd), 3),
        octaveLowered=sum(e.hardware.get('selection', {}).get('lowFdd', {}).get('lowered', False) for e in fdd),
        octaveRangeFallback=sum(e.hardware.get('selection', {}).get('lowFdd', {}).get('rangeFallback', False) for e in fdd),
        shortenedNotes=sum(e.played and e.actual_duration < e.duration - 1e-8 for e in plan.events),
        fddFrequenciesHz=sorted(e.played_hz for e in fdd),
        importantDropped=sum(not e.played and e.role in ('lead', 'bass') for e in plan.events))
    return result
