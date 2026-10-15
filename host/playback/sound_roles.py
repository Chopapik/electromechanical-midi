"""Conservative GM noise semantics; note number is a trigger, not harmony.

Do not reject the Synth Effects family, melodic percussion, bird tweet or
telephone ring: those can carry an intentional pitch. Unsupported noise is
reported explicitly instead of being approximated by an arbitrary motor tone.
"""

UNPITCHED_EFFECT = 'unpitched_effect'
UNSUPPORTED_EFFECT = 'UNPITCHED_EFFECT_UNSUPPORTED'
GM_NOISE = {
    119: 'Reverse Cymbal', 120: 'Guitar Fret Noise', 121: 'Breath Noise',
    122: 'Seashore', 125: 'Helicopter', 126: 'Applause', 127: 'Gunshot',
}


def source_effects(source) -> dict[str, str]:
    """Classify original NOTE_ONs, also after duplicate normalization."""
    raw = getattr(source, 'source', source)
    programs = raw.note_programs()
    return {f'{track.index}:{span.order}': GM_NOISE[program]
            for track in source.tracks for span in source.notes(track.index)
            if span.channel != 9
            and (program := programs.get((track.index, span.order))) in GM_NOISE}
