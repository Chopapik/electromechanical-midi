"""MIDI library and bounded import metadata."""
from pathlib import Path
import tempfile
from midi_source import MidiSource, MidiSourceError
MIDI_SUFFIXES=(".mid", ".midi")
MAX_UPLOAD_BYTES=5*1024*1024


class MidiLibraryError(ValueError):
    """Library failure described without HTTP or another transport's statuses."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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
            raise MidiLibraryError('invalid_name', "niepoprawna nazwa pliku")

        path = (self.directory / name).resolve()
        root = self.directory.resolve()

        if path != root and root not in path.parents:
            raise MidiLibraryError('outside_library', "plik poza katalogiem midi/")

        if not path.is_file():
            raise MidiLibraryError('not_found', f"nie ma pliku {name}")

        return path

    def save_upload(self, filename: str, data: bytes) -> Path:
        """Validate with the playback parser and import without overwriting.

        Keep the established endpoint's basename and ``stem-N.mid`` collision
        convention. Exclusive creation also treats dangling symlinks as occupied.
        """
        name = Path(filename or '').name
        if not name or name.startswith('.') or Path(name).suffix.lower() not in MIDI_SUFFIXES:
            raise MidiLibraryError('invalid_upload_name', 'Wybierz plik MIDI')
        if len(data)>MAX_UPLOAD_BYTES:
            raise MidiLibraryError('upload_too_large', 'MIDI przekracza 5 MB')
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.directory, suffix='.mid') as temp:
            temp.write(data)
            temp.flush()
            try:
                MidiSource(Path(temp.name))
            except Exception as exc:
                raise MidiLibraryError('invalid_midi', str(exc)) from exc
        target = self.directory / name
        stem, index = target.stem, 1
        while True:
            try:
                output=target.open('xb')
            except FileExistsError:
                target=self.directory/f'{stem}-{index}.mid'
                index+=1
                continue
            try:
                with output:
                    output.write(data)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
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
            raise MidiLibraryError('invalid_midi', str(exc)) from exc

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
