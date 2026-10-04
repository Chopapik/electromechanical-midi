"""Vanilla VCM/chassis articulations. No drum samples or tuned resonators.

The classifier consumes source MIDI semantics; synthesis consumes its decision.
Durations/frequencies are schematic estimates, not hardware calibration values.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math

KINDS = ('SOFT_TAP', 'MEDIUM_HIT', 'HARD_HIT', 'DOUBLE_TAP', 'BUZZ_ROLL')
# Complete GM percussion 35..81. Mapping expresses movement, never a drum sample.
GM = {
    35:'HARD_HIT',36:'HARD_HIT',37:'DOUBLE_TAP',38:'DOUBLE_TAP',39:'DOUBLE_TAP',40:'DOUBLE_TAP',
    41:'MEDIUM_HIT',42:'SOFT_TAP',43:'MEDIUM_HIT',44:'SOFT_TAP',45:'MEDIUM_HIT',46:'MEDIUM_HIT',
    47:'MEDIUM_HIT',48:'MEDIUM_HIT',49:'HARD_HIT',50:'MEDIUM_HIT',51:'MEDIUM_HIT',52:'HARD_HIT',
    53:'BUZZ_ROLL',54:'DOUBLE_TAP',55:'BUZZ_ROLL',56:'MEDIUM_HIT',57:'HARD_HIT',58:'BUZZ_ROLL',
    59:'MEDIUM_HIT',60:'MEDIUM_HIT',61:'MEDIUM_HIT',62:'SOFT_TAP',63:'MEDIUM_HIT',64:'MEDIUM_HIT',
    65:'MEDIUM_HIT',66:'MEDIUM_HIT',67:'HARD_HIT',68:'MEDIUM_HIT',69:'BUZZ_ROLL',70:'SOFT_TAP',
    71:'SOFT_TAP',72:'SOFT_TAP',73:'BUZZ_ROLL',74:'BUZZ_ROLL',75:'SOFT_TAP',76:'MEDIUM_HIT',
    77:'HARD_HIT',78:'SOFT_TAP',79:'MEDIUM_HIT',80:'SOFT_TAP',81:'MEDIUM_HIT',
}
TOMS = {41, 43, 45, 47, 48, 50}
# duration, decay, chassis Hz, body, click, movement
_BASE = {
    'SOFT_TAP': (.020, .004, 420., .015, .65, .08),
    'MEDIUM_HIT': (.080, .017, 290., .18, .80, .14),
    'HARD_HIT': (.140, .032, 210., .48, 1., .22),
    'DOUBLE_TAP': (.095, .012, 340., .12, .85, .18),
    'BUZZ_ROLL': (.075, .006, 380., .06, .50, .25),
}

@dataclasses.dataclass(frozen=True)
class HDDArticulation:
    kind: str
    duration: float
    decay: float
    resonance: float
    body: float
    click: float
    movement: float
    impulses: tuple[float, ...]
    intensity: float
    pitch_band: str
    raw: bool = False

    def as_dict(self):
        return dataclasses.asdict(self)


def classify(note: int, channel: int, velocity: int, override: str | None = None) -> HDDArticulation:
    """Channel 10 is GM drums; melodic percussion retains a coarse pitch contour."""
    v = max(0, min(127, velocity)) / 127
    pitched = channel != 9
    band = ('LOW' if note < 48 else 'MID' if note < 56 else 'HIGH') if pitched else 'GM'
    if override in KINDS:
        kind = override
    elif override == 'DOUBLE_HIT':
        kind = 'DOUBLE_TAP'
    elif pitched:
        kind = 'HARD_HIT' if note < 48 and velocity >= 100 else 'MEDIUM_HIT'
    else:
        kind = GM.get(note, 'HARD_HIT' if velocity >= 110 else 'MEDIUM_HIT' if velocity >= 60 else 'SOFT_TAP')
        if note in TOMS and velocity >= (95 if note in (41, 43, 45) else 110):
            kind = 'HARD_HIT'
    duration, decay, resonance, body, click, movement = _BASE[kind]
    # Velocity changes impact shape/body as well as amplitude.
    duration *= .75 + .25 * v
    decay *= .65 + .35 * v
    body *= .35 + .65 * v * v
    movement *= .5 + .5 * v
    if pitched:
        resonance *= {'LOW': .78, 'MID': 1., 'HIGH': 1.22}[band]
        body *= {'LOW': 1.15, 'MID': 1., 'HIGH': .60}[band]
        decay *= {'LOW': 1.1, 'MID': 1., 'HIGH': .75}[band]
    if kind == 'DOUBLE_TAP':
        impulses = (0., .018 + .008 * v)
    elif kind == 'BUZZ_ROLL':
        span = .020 + .060 * v
        impulses = tuple(i * .009 for i in range(max(3, int(span / .009))))
        duration = span + .014
    else:
        impulses = (0.,)
    return HDDArticulation(kind, duration, decay, resonance, body, click, movement,
                           impulses, v ** .65, band)


def adapt(art: HDDArticulation, gap: float, raw: bool = False) -> HDDArticulation:
    if raw:
        return dataclasses.replace(art, duration=.009, decay=.0018, body=0., movement=0.,
                                   impulses=(0.,), raw=True)
    density = min(1., max(.35, gap / .22)) if math.isfinite(gap) else 1.
    return dataclasses.replace(art, duration=art.duration * (.65 + .35 * density),
                               decay=art.decay * density, body=art.body * density)


def sample(t, art: HDDArticulation, device_id: str, np=None):
    """Same procedural layers in scalar/Python and vector/NumPy paths."""
    exp, sin, maximum = (np.exp, np.sin, np.maximum) if np is not None else (math.exp, math.sin, max)
    seed = int.from_bytes(hashlib.sha256(device_id.encode()).digest()[:4], 'little')
    variation = ((seed % 1001) / 1000 - .5) * .06  # only +/-3% chassis variation
    phase = (seed % 97) * .065
    resonance = art.resonance * (1 + variation)
    result = t * 0 if np is not None else 0.
    for index, onset in enumerate(art.impulses):
        age = maximum(0., t - onset)
        mask = (t >= onset) if np is not None else float(t >= onset)
        polarity = 1 if index % 2 == 0 else -.85
        # Brief non-periodic-ish contact transient + short actuator movement.
        click = exp(-age / .0013) * (sin(age * 2 * math.pi * (2100 + seed % 250) + phase)
                 + .45 * sin(age * 2 * math.pi * 3713 + .7))
        if art.raw:
            layer = click * .75
        else:
            chassis = exp(-age / art.decay) * (sin(age * 2 * math.pi * resonance)
                      + .24 * sin(age * 2 * math.pi * resonance * 2.73))
            body = exp(-age / (art.decay * .75)) * sin(age * 2 * math.pi * (112 + variation * 80))
            movement = exp(-age / .004) * sin(age * 2 * math.pi * 877 + phase) * sin(age * 2 * math.pi * 1331)
            layer = art.click * click + art.body * (chassis + .35 * body) + art.movement * movement
        result = result + mask * polarity * layer / (1 + index * .15)
    # Bounded family gain; master-volume is applied by the host player afterwards.
    return result * art.intensity * .8
