"""MIDI library and bounded import metadata."""
from pathlib import Path
from fastapi import HTTPException
from midi_source import MidiSource, MidiSourceError
MIDI_SUFFIXES=(".mid", ".midi")
def _is_polyphonic(notes) -> bool:
    """Czy w tracku cokolwiek brzmi jednoczesnie (dwie nuty na raz)."""
    last_end = -1.0

    for span in sorted(notes, key=lambda item: (item.start, item.end)):
        if span.start < last_end - 1e-6:
            return True

        last_end = max(last_end, span.end)

    return False


class MidiLibrary:
    """Lista plikow MIDI z katalogu + metadane (z cache po mtime/size)."""

    def __init__(self, directory: Path):
        self.directory = directory
        self._cache: dict[Path, tuple[float, int, dict]] = {}

    def resolve(self, name: str) -> Path:
        """Bezpieczne rozwiazanie nazwy pliku (bez wyjscia z katalogu)."""
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise HTTPException(status_code=400, detail="niepoprawna nazwa pliku")

        path = (self.directory / name).resolve()
        root = self.directory.resolve()

        if path != root and root not in path.parents:
            raise HTTPException(status_code=400, detail="plik poza katalogiem midi/")

        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"nie ma pliku {name}")

        return path

    def save_upload(self, filename: str, data: bytes) -> Path:
        """Zapisuje wgrany plik MIDI do katalogu biblioteki.

        Nazwa jest czyszczona (bez sciezek), a przy kolizji dokladamy
        " (2)", " (3)"... - nigdy nie nadpisujemy istniejacego utworu.
        """
        name = Path(filename or "").name.strip()

        if not name or name.startswith("."):
            raise HTTPException(status_code=400, detail="niepoprawna nazwa pliku")

        suffix = Path(name).suffix.lower()

        if suffix not in MIDI_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"dozwolone rozszerzenia: {', '.join(MIDI_SUFFIXES)}",
            )

        if not data:
            raise HTTPException(status_code=400, detail="pusty plik")

        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"plik wiekszy niz {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            )

        # Walidacja: plik musi byc czytelnym MIDI (zanim cokolwiek zapiszemy).
        try:
            mido.MidiFile(file=io.BytesIO(data))
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"to nie wyglada na plik MIDI: {exc}"
            ) from exc

        self.directory.mkdir(parents=True, exist_ok=True)

        target = self.directory / name
        stem, index = Path(name).stem, 2

        while target.exists():
            target = self.directory / f"{stem} ({index}){suffix}"
            index += 1

        target.write_bytes(data)

        return target

    def list_files(self) -> list[dict]:
        if not self.directory.is_dir():
            return []

        files = []

        for path in sorted(self.directory.iterdir()):
            if path.suffix.lower() not in MIDI_SUFFIXES or not path.is_file():
                continue

            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )

        return files

    def metadata(self, name: str) -> dict:
        path = self.resolve(name)
        stat = path.stat()
        cached = self._cache.get(path)

        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]

        try:
            source = MidiSource(path)
        except MidiSourceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        tracks = []

        for track in source.tracks:
            polyphonic = False

            if track.note_count:
                polyphonic = _is_polyphonic(source.notes(track.index))

            tracks.append(
                {
                    "index": track.index,
                    "name": track.name,
                    "label": track.label,
                    "noteCount": track.note_count,
                    "channels": list(track.channels),
                    "isDrums": track.is_drums,
                    "polyphonic": polyphonic,
                    "programs": list(source.programs(track.index)),
                }
            )

        data = {
            "name": path.name,
            "duration": round(source.duration, 3),
            "tempoChanges": source.tempo.change_count,
            "type": source.file_type,
            "ticksPerBeat": source.ticks_per_beat,
            "tracks": tracks,
        }

        self._cache[path] = (stat.st_mtime, stat.st_size, data)

        return data
