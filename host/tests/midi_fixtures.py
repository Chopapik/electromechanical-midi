import mido
from pathlib import Path
TPB=480
TEMPO=500000
TICKS_PER_SECOND=960
def write_midi(path: Path, notes, name: str = "Test") -> Path:
    midi = mido.MidiFile(type=1, ticks_per_beat=TPB)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(mido.MetaMessage("set_tempo", tempo=TEMPO, time=0))

    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name=name, time=0))

    events = []

    for start, end, note in notes:
        events.append((round(start * TICKS_PER_SECOND), 0, note))
        events.append((round(end * TICKS_PER_SECOND), 1, note))

    events.sort(key=lambda event: (event[0], event[1]))

    previous = 0

    for tick, kind, note in events:
        delta = tick - previous
        previous = tick
        track.append(
            mido.Message(
                "note_on" if kind == 0 else "note_off",
                note=note,
                velocity=100 if kind == 0 else 0,
                time=delta,
            )
        )

    midi.save(path)

    return path
