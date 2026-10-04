"""Lokalny web player: FastAPI (REST + WebSocket) nad wspolnym silnikiem.

Podzial odpowiedzialnosci:

* **REST** - rzeczy bezstanowe: lista plikow MIDI, metadane trackow,
  lista portow szeregowych.
* **WebSocket** - stan odtwarzania w czasie rzeczywistym + sterowanie
  (play/pause/resume/stop/seek/zmiana tracku/transpozycji/reconnect).

Arduino nadal jest tylko kontrolerem wykonawczym: seek, pauza i progress
bar istnieja wylacznie po stronie hosta. Z punktu widzenia Arduino seek
to najwyzej ``STOP`` + ``PLAY <hz>``.

Uruchomienie:

    python -m host.web.server            # http://127.0.0.1:8000
    python -m host.web.server --no-hardware
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import sys
import time
from pathlib import Path

# --- bootstrap sciezek: ten plik musi dzialac i jako skrypt, i jako modul ---
HOST_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HOST_DIR.parent

if str(HOST_DIR) not in sys.path:
    sys.path.insert(0, str(HOST_DIR))

import mido  # noqa: E402
from fastapi import (  # noqa: E402
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.websockets import (  # noqa: E402
    WebSocketDisconnected,
    WebSocketState,
)

from floppy_link import SerialLinkError, describe_ports, scan_ports  # noqa: E402
from midi_source import MidiSource, MidiSourceError  # noqa: E402
from pitch import COMFORT_MAX_HZ, COMFORT_MIN_HZ, FOLD_MODES  # noqa: E402
from playback.engine import EngineError, PlaybackEngine  # noqa: E402
from playback.arrangement import ArrangementError, ArrangementMismatch  # noqa: E402

# Jak czesto backend publikuje autorytatywny stan (frontend interpoluje
# plynnie miedzy tymi wiadomosciami przez requestAnimationFrame).
STATE_INTERVAL_S = 0.15
HEARTBEAT_S = 1.0

MIDI_SUFFIXES = (".mid", ".midi")

# Upload z przegladarki: pliki MIDI sa malutkie, wiec 5 MB to i tak duzo.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


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


def create_app(
    *,
    midi_dir: Path,
    engine: PlaybackEngine,
    serial_port: str | None = None,
    connect_on_start: bool = True,
    web_dist: Path | None = None,
) -> FastAPI:
    library = MidiLibrary(midi_dir)

    clients: set[WebSocket] = set()
    connect_lock = asyncio.Lock()

    # --------------------------------------------------------
    # WebSocket: wysylka stanu
    # --------------------------------------------------------

    async def send_state(websocket: WebSocket) -> None:
        if websocket.client_state is not WebSocketState.CONNECTED:
            return

        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"type": "state", "state": await asyncio.to_thread(engine.snapshot)}
            )

    async def broadcast(payload: dict) -> None:
        for websocket in list(clients):
            try:
                await websocket.send_json(payload)
            except Exception:
                clients.discard(websocket)

    async def broadcast_loop() -> None:
        last_payload: str | None = None
        last_sent = 0.0

        while True:
            try:
                # snapshot() bierze lock silnika; connect()/home() trzymaja go
                # podczas homingu, wiec MUSI isc w watek - inaczej blokujemy
                # petle zdarzen i WebSocket przestaje nadawac (UI zglasza
                # "brak polaczenia z backendem").
                payload = {
                    "type": "state",
                    "state": await asyncio.to_thread(engine.snapshot),
                }
                encoded = json.dumps(payload, sort_keys=True)
                now = time.monotonic()

                if encoded != last_payload or now - last_sent >= HEARTBEAT_S:
                    await broadcast(payload)
                    last_payload, last_sent = encoded, now
            except Exception:
                pass

            await asyncio.sleep(STATE_INTERVAL_S)

    # --------------------------------------------------------
    # Hardware
    # --------------------------------------------------------

    async def connect_hardware(port: str | None = None) -> None:
        """Podlaczenie jest blokujace (czeka na READY), wiec idzie w watek."""
        if connect_lock.locked():
            return

        async with connect_lock:
            await asyncio.to_thread(engine.connect, port)

    # --------------------------------------------------------
    # Sterowanie
    # --------------------------------------------------------

    async def load_file(name: str, track: int | None = None) -> None:
        path = library.resolve(name)
        await asyncio.to_thread(engine.load_file, path, track)

    async def handle_command(websocket: WebSocket, message: dict) -> None:
        action = str(message.get("action") or "")

        if action == "play":
            await asyncio.to_thread(engine.play)
        elif action == "set_virtual":
            await asyncio.to_thread(engine.configure_virtual, message.get('config') or {})
        elif action == "pause":
            await asyncio.to_thread(engine.pause)
        elif action == "resume":
            await asyncio.to_thread(engine.resume)
        elif action == "stop":
            await asyncio.to_thread(engine.stop)
        elif action == "seek":
            await asyncio.to_thread(engine.seek, float(message.get("position", 0.0)))
        elif action == "set_track":
            await asyncio.to_thread(engine.set_track, int(message.get("track", 0)))
        elif action == "set_file":
            await load_file(str(message.get("file")), message.get("track"))
        elif action == "set_transpose":
            await asyncio.to_thread(engine.set_transpose, str(message.get("mode")))
        elif action == "set_strategy":
            await asyncio.to_thread(engine.set_strategy, str(message.get("strategy")))
        elif action == "reconnect":
            asyncio.create_task(connect_hardware(message.get("port")))
        elif action == "home":
            await asyncio.to_thread(engine.home)
        elif action == "disconnect":
            await asyncio.to_thread(engine.disconnect)
        elif action == "set_drum":
            await asyncio.to_thread(engine.set_drum, int(message.get("value", 0)))
        elif action == "start_drum":
            await asyncio.to_thread(engine.start_drum)
        elif action == "stop_drum":
            await asyncio.to_thread(engine.stop_drum)
        elif action == "set_drum_tone":
            await asyncio.to_thread(engine.set_drum_tone, float(message.get("hz", 0)))
        elif action == "set_drum_track":
            track = message.get("track", None)
            await asyncio.to_thread(
                engine.set_drum_track, None if track is None else int(track)
            )
        elif action == "set_drum_transpose":
            await asyncio.to_thread(engine.set_drum_transpose, str(message.get("mode")))
        elif action == "set_drum_strategy":
            await asyncio.to_thread(engine.set_drum_strategy, str(message.get("strategy")))
        elif action == "set_hdd_track":
            track = message.get("track", None)
            await asyncio.to_thread(
                engine.set_hdd_track, None if track is None else int(track)
            )
        elif action == "set_hdd_note":
            note = message.get("note", None)
            await asyncio.to_thread(
                engine.set_hdd_note, None if note is None else int(note)
            )
        elif action == "set_hdd_rate":
            rate = message.get("rate", None)
            await asyncio.to_thread(
                engine.set_hdd_rate, None if rate is None else float(rate)
            )
        elif action == "snapshot":
            pass
        else:
            raise EngineError(f"nieznana akcja {action!r}")

    # --------------------------------------------------------
    # Start / stop
    # --------------------------------------------------------

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        engine.start()
        task = asyncio.create_task(broadcast_loop())

        if connect_on_start:
            asyncio.create_task(connect_hardware(serial_port))

        try:
            yield
        finally:
            task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await task

            engine.shutdown()

    # --------------------------------------------------------
    # REST
    # --------------------------------------------------------

    app = FastAPI(
        title="Electromechanical MIDI",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.get("/api/state")
    def api_state() -> dict:
        return engine.snapshot()

    @app.get("/api/files")
    def api_files() -> dict:
        return {"files": library.list_files(), "directory": str(midi_dir)}

    @app.get("/api/files/{name}")
    def api_file(name: str) -> dict:
        return library.metadata(name)

    @app.post("/api/files")
    async def api_upload(file: UploadFile = File(...)) -> dict:
        """Wgranie pliku MIDI z przegladarki do katalogu midi/."""
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        path = library.save_upload(file.filename or "", data)

        return {
            "name": path.name,
            "size": len(data),
            "files": library.list_files(),
        }

    @app.get("/api/ports")
    def api_ports() -> dict:
        ports = [
            {
                "device": candidate.device,
                "label": candidate.label,
                "usbId": candidate.usb_id,
                "score": candidate.score,
            }
            for candidate in scan_ports()
        ]

        snapshot = engine.snapshot()

        return {
            "ports": ports,
            "current": snapshot["hardware"]["port"],
            "connected": snapshot["hardware"]["connected"],
        }

    @app.get("/api/config")
    def api_config() -> dict:
        return {
            "midiDir": str(midi_dir),
            "transposeModes": list(FOLD_MODES),
            "strategies": ["highest", "lowest", "last"],
            "range": {"minHz": COMFORT_MIN_HZ, "maxHz": COMFORT_MAX_HZ},
        }

    preset_path = midi_dir / '.virtual-orchestra-presets.json'

    def read_presets() -> dict:
        if not preset_path.exists():
            return {}
        try:
            data = json.loads(preset_path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @app.get('/api/virtual/presets')
    def api_virtual_presets() -> dict:
        return {'presets': read_presets()}

    @app.put('/api/virtual/presets/{name}')
    def api_save_virtual_preset(name: str, config: dict) -> dict:
        if not name or len(name) > 100 or '/' in name or '\\' in name:
            raise HTTPException(status_code=400, detail='invalid preset name')
        # Use the same parser as playback, so saved presets are always loadable.
        from playback.virtual import VirtualOrchestra
        checked = VirtualOrchestra()
        try:
            checked.set_config(config)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        presets = read_presets()
        presets[name] = checked.config()
        midi_dir.mkdir(parents=True, exist_ok=True)
        temporary = preset_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(presets, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(preset_path)
        return {'presets': presets}

    @app.delete('/api/virtual/presets/{name}')
    def api_delete_virtual_preset(name: str) -> dict:
        presets = read_presets()
        presets.pop(name, None)
        preset_path.write_text(json.dumps(presets, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'presets': presets}

    @app.get('/api/mechanical')
    def api_mechanical() -> dict:
        return engine.mechanical_view()

    @app.get('/api/arrangement')
    def api_arrangement() -> dict:
        return engine.arrangement_view()

    @app.post('/api/arrangement/initialize')
    def api_initialize_arrangement() -> dict:
        """Auto Arranger: MIDI + orkiestra -> plan. Zapisany JSON jest tylko
        opcjonalnym overridem i wczytuje sie razem z plikiem MIDI."""
        try:
            engine.initialize_arrangement()
        except ArrangementMismatch as exc:
            raise HTTPException(status_code=409, detail={'mismatches': exc.mismatches}) from exc
        except (ArrangementError, ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EngineError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return engine.arrangement_view()

    @app.get('/api/orchestra')
    def api_orchestra() -> dict:
        view = engine.arrangement_view()

        return {'orchestra': view['orchestra'],
                'report': view['report'],
                'origin': view['arrangement']['origin'] if view['arrangement'] else None}

    @app.put('/api/orchestra')
    def api_set_orchestra(payload: dict) -> dict:
        try:
            engine.set_orchestra(payload)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EngineError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return engine.arrangement_view()

    @app.get('/api/report')
    def api_report() -> dict:
        return engine.arrangement_view()['report'] or {}

    @app.put('/api/arrangement')
    def api_update_arrangement(document: dict) -> dict:
        try:
            engine.set_arrangement(document)
        except ArrangementMismatch as exc:
            raise HTTPException(status_code=409, detail={'mismatches': exc.mismatches}) from exc
        except (ArrangementError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EngineError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return engine.arrangement_view()

    def arrangement_path() -> Path:
        source = engine.source
        if source is None:
            raise HTTPException(status_code=409, detail='load MIDI first')
        return midi_dir / f'{source.path.stem}.orchestra.json'

    @app.post('/api/arrangement/save')
    def api_save_arrangement() -> dict:
        document = engine.arrangement_view()['arrangement']
        if document is None:
            raise HTTPException(status_code=409, detail='no arrangement to save')
        path = arrangement_path()
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
        return {'file': path.name}

    @app.get('/api/arrangement/saved')
    def api_load_arrangement() -> dict:
        path = arrangement_path()
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f'{path.name} not found')
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {'file': path.name, 'arrangement': document}

    # --------------------------------------------------------
    # WebSocket
    # --------------------------------------------------------

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        clients.add(websocket)

        try:
            await send_state(websocket)

            while True:
                raw = await websocket.receive_text()

                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json(
                        {"type": "error", "message": "niepoprawny JSON"}
                    )
                    continue

                try:
                    await handle_command(websocket, message)
                except (EngineError, MidiSourceError, SerialLinkError, ValueError) as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                except HTTPException as exc:
                    await websocket.send_json({"type": "error", "message": str(exc.detail)})
                except Exception as exc:  # pragma: no cover - bezpiecznik
                    await websocket.send_json({"type": "error", "message": str(exc)})

                await send_state(websocket)
        except (WebSocketDisconnect, WebSocketDisconnected):
            # Starlette potrafi rzucic oba warianty: WebSocketDisconnect (klient
            # przyslal disconnect) i WebSocketDisconnected (stan gniazda).
            # Bez tego rozlaczenie karty leci do logu jako "Exception in ASGI
            # application".
            pass
        finally:
            clients.discard(websocket)

    # Zbudowany frontend (npm run build) serwowany z tego samego portu.
    dist = web_dist or (REPO_ROOT / "web" / "dist")

    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        def missing_frontend() -> str:
            return (
                "<h1>Electromechanical MIDI</h1>"
                "<p>Brak zbudowanego frontendu (<code>web/dist</code>).</p>"
                "<p>Zbuduj go: <code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>,"
                " albo uruchom tryb dev: <code>npm run dev</code> (port 5173).</p>"
                "<p>API dziala: <a href='/api/state'>/api/state</a>, "
                "<a href='/api/files'>/api/files</a>, <a href='/api/ports'>/api/ports</a></p>"
            )

    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m host.web.server",
        description="Lokalny web player dla stacji dyskietek (FastAPI + WebSocket).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1", help="adres nasluchu")
    parser.add_argument("--port", type=int, default=8000, help="port HTTP")
    parser.add_argument(
        "--midi-dir",
        type=Path,
        default=REPO_ROOT / "midi",
        help="katalog z plikami .mid",
    )
    parser.add_argument("--serial-port", default=None, help="port Arduino (domyslnie autodetekcja)")
    parser.add_argument(
        "--no-hardware",
        action="store_true",
        help="nie laczy sie z Arduino (UI dziala, ale PLAY zglosi brak polaczenia)",
    )
    parser.add_argument(
        "--fake-hardware",
        action="store_true",
        help="bez Serial, ale silnik gra na atrapie - demo UI i testy bez Arduino",
    )
    parser.add_argument("--min-hz", type=float, default=COMFORT_MIN_HZ)
    parser.add_argument("--max-hz", type=float, default=COMFORT_MAX_HZ)
    parser.add_argument("--transpose", choices=FOLD_MODES, default="auto")
    parser.add_argument(
        "--drum-transpose",
        choices=FOLD_MODES,
        default="low",
        help="tryb skladania oktawowego bebna (low = bez skokow)",
    )
    parser.add_argument(
        "--drum-strategy",
        choices=("highest", "lowest", "last"),
        default="highest",
        help="strategia monofonizacji bebna (lowest = linia basowa)",
    )
    parser.add_argument(
        "--strategy", choices=("highest", "lowest", "last"), default="highest"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    args = build_parser().parse_args(argv)

    connect_fn = None

    if args.fake_hardware:
        from floppy_link import DryRunLink

        def connect_fn(_port: str | None):
            link = DryRunLink()
            link.label = "dry-run (bez sprzętu)"
            return link

    engine = PlaybackEngine(
        # GUI: MIDI -> Auto Arranger -> plan -> orkiestra. Bez JSON-a.
        auto_arrange=True,
        connect_fn=connect_fn,
        min_hz=args.min_hz,
        max_hz=args.max_hz,
        transpose=args.transpose,
        strategy=args.strategy,
        drum_transpose=args.drum_transpose,
        drum_strategy=args.drum_strategy,
    )

    app = create_app(
        midi_dir=args.midi_dir,
        engine=engine,
        serial_port=args.serial_port,
        connect_on_start=args.fake_hardware or not args.no_hardware,
    )

    print(f"Electromechanical MIDI web player: http://{args.host}:{args.port}")
    print(f"Katalog MIDI: {args.midi_dir}")

    if args.fake_hardware:
        print("Tryb: FAKE hardware (atrapa - nic nie idzie po Serial)")
    elif args.no_hardware:
        print("Tryb: bez sprzetu (PLAY zglosi brak polaczenia)")
    else:
        print("Porty szeregowe:")
        print(describe_ports(scan_ports()))

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

    return 0


if __name__ == "__main__":
    sys.exit(main())
