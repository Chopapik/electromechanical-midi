#!/usr/bin/env python3
"""Odtwarzacz MIDI na mechanicznej stacji dyskietek 3.5" (Arduino Uno).

    plik .mid -> ten program -> USB Serial -> Arduino -> STEP/DIR -> FDD

Podstawowe uzycie:

    python host/player.py midi/test.mid
    python host/player.py midi/test.mid --track 2
    python host/player.py midi/test.mid --dry-run

Caly timing muzyczny liczy ten program (a konkretnie wspolny silnik z
``host/playback``). Arduino dostaje tylko "PLAY <hz>" i "STOP" i ma je
wykonac natychmiast.

Timing opiera sie na zegarze monotonicznym i BEZWZGLEDNYM czasie startu
odtwarzania, dlatego opoznienia Serial nie kumuluja sie w trakcie utworu.
Ten sam silnik obsluguje web player (``host/web/server.py``), wiec seek,
pauza i zmiana tracku dzialaja identycznie w obu trybach.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from floppy_link import (
    BAUD,
    DryRunLink,
    FloppyLink,
    SerialLinkError,
    describe_ports,
    resolve_port,
    scan_ports,
)
from midi_source import STRATEGIES, MidiSource, MidiSourceError
from pitch import COMFORT_MAX_HZ, COMFORT_MIN_HZ, FOLD_MODES
from playback.engine import (
    SPIN_MARGIN_S,
    EngineError,
    PlaybackEngine,
    PlaybackState,
)

# Re-eksport dla kompatybilnosci (CLI i testy uzywaly tych nazw z player.py).
from playback.timeline import (  # noqa: F401
    ARTICULATION_S,
    MIN_NOTE_S,
    SAME_HZ_EPS,
    TIME_EPS,
    Command,
    ScheduleStats,
    Timeline,
    build_schedule,
    make_timeline,
)

__all__ = [
    "ARTICULATION_S",
    "MIN_NOTE_S",
    "Command",
    "ScheduleStats",
    "Timeline",
    "build_schedule",
    "main",
    "make_timeline",
]


# ============================================================
# INTERFEJS
# ============================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="player.py",
        description="Odtwarza track z pliku MIDI na stacji dyskietek (Arduino Uno).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("midi_file", type=Path, help="sciezka do pliku .mid")
    parser.add_argument(
        "--track",
        type=int,
        default=None,
        help="numer tracku do odtworzenia (bez tego zapyta interaktywnie)",
    )
    parser.add_argument(
        "--list-tracks", action="store_true", help="wypisz tracki i zakoncz"
    )
    parser.add_argument(
        "--list-ports", action="store_true", help="wypisz porty szeregowe i zakoncz"
    )

    parser.add_argument("--port", default=None, help="port szeregowy (np. /dev/cu.usbmodem14101)")
    parser.add_argument("--baud", type=int, default=BAUD, help="predkosc Serial")

    parser.add_argument("--min-hz", type=float, default=COMFORT_MIN_HZ, help="dolna granica zakresu")
    parser.add_argument("--max-hz", type=float, default=COMFORT_MAX_HZ, help="gorna granica zakresu")
    parser.add_argument(
        "--transpose",
        choices=FOLD_MODES,
        default="auto",
        help=(
            "auto = nuta zostaje, jesli sie miesci (moga byc skoki oktawowe); "
            "low/high = zawsze ta sama oktawa, melodia bez skokow"
        ),
    )
    parser.add_argument(
        "--strategy",
        choices=sorted(STRATEGIES),
        default="highest",
        help="co zrobic z akordem (highest = najwyzsza nuta)",
    )
    parser.add_argument(
        "--gate",
        type=float,
        default=1.0,
        help="jaka czesc zapisanej dlugosci nuty zagrac (1.0 = cala, 0.5 = staccato)",
    )

    parser.add_argument("--loop", action="store_true", help="powtarzaj w nieskonczonosc")
    parser.add_argument(
        "--dry-run", action="store_true", help="bez sprzetu: wypisz harmonogram i odtworz go na sucho"
    )
    parser.add_argument(
        "--print-schedule", action="store_true", help="wypisz harmonogram przed odtwarzaniem"
    )
    parser.add_argument(
        "--no-wait", action="store_true", help="nie czekaj na czas (razem z --dry-run)"
    )
    parser.add_argument(
        "--no-busy-wait", action="store_true", help="mniej dokladny, ale nie zajmuje CPU"
    )
    parser.add_argument(
        "--no-handshake",
        action="store_true",
        help="nie czekaj na READY po resecie Arduino",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="nie czekaj na ENTER")
    parser.add_argument("-v", "--verbose", action="store_true", help="pokaz kazda komende")

    return parser


def print_tracks(source: MidiSource) -> None:
    print("Tracks:")

    for track in source.tracks:
        suffix = "" if track.note_count else "  (brak nut)"
        print(f"[{track.index}] {track.label}{suffix}")


def prompt_track(source: MidiSource) -> int:
    playable = {track.index for track in source.tracks if track.note_count}

    while True:
        try:
            raw = input("Select track: ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise SystemExit("\nPrzerwano wybor tracku.") from exc

        if raw.isdigit() and int(raw) in playable:
            return int(raw)

        if raw.isdigit():
            print("  ? Ten track nie istnieje albo nie ma nut.")
            continue

        print("  ? Podaj numer tracku z listy.")


def wait_for_enter() -> None:
    try:
        input("\nPress ENTER to play\nPress Ctrl+C to stop\n")
    except (EOFError, KeyboardInterrupt) as exc:
        raise SystemExit("\nPrzerwano.") from exc


# ============================================================
# MAIN
# ============================================================


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_ports:
        print("Porty szeregowe:")
        print(describe_ports(scan_ports()))
        return 0

    if args.min_hz <= 0.0 or args.max_hz <= args.min_hz:
        print(
            f"BLAD: zly zakres --min-hz {args.min_hz} --max-hz {args.max_hz}",
            file=sys.stderr,
        )
        return 2

    if not 0.0 < args.gate <= 1.0:
        print(f"BLAD: --gate musi byc w (0, 1], jest {args.gate}", file=sys.stderr)
        return 2

    if args.no_wait and not args.dry_run:
        print(
            "BLAD: --no-wait wysyla caly utwor bez czekania na czas - "
            "to ma sens tylko z --dry-run (bez sprzetu).",
            file=sys.stderr,
        )
        return 2

    # ---------- MIDI ----------
    try:
        source = MidiSource(args.midi_file)
    except MidiSourceError as exc:
        print(f"BLAD: {exc}", file=sys.stderr)
        return 2

    print(f"MIDI: {args.midi_file.name}")
    print()
    print_tracks(source)

    if args.list_tracks:
        return 0

    print()

    if args.track is None:
        track_index = prompt_track(source)
    else:
        track_index = args.track

        if not 0 <= track_index < len(source.tracks):
            print(
                f"BLAD: track {track_index} nie istnieje "
                f"(plik ma {len(source.tracks)} trackow)",
                file=sys.stderr,
            )
            return 2

        if not source.tracks[track_index].note_count:
            print(f"BLAD: track {track_index} nie ma nut", file=sys.stderr)
            return 2

    # ---------- port ----------
    candidate = None

    if args.dry_run:
        print("Serial:")
        print("(dry-run - sprzet nietkniety)")

        def connect_fn(port, _args=args):
            return DryRunLink()
    else:
        try:
            candidate = resolve_port(args.port, interactive=sys.stdin.isatty())
        except SerialLinkError as exc:
            print(f"BLAD: {exc}", file=sys.stderr)
            return 2

        print("Serial:")
        print(f"{candidate.label} @ {candidate.device}")

        def connect_fn(port, _args=args, _candidate=candidate):
            link = FloppyLink(_candidate.device, _args.baud)
            link.label = _candidate.label
            return link

    # ---------- silnik ----------
    def on_command(command):
        if args.verbose:
            print(f"   {command.time:8.3f}s  {command.text}", flush=True)

    engine = PlaybackEngine(
        connect_fn=connect_fn,
        min_hz=args.min_hz,
        max_hz=args.max_hz,
        transpose=args.transpose,
        strategy=args.strategy,
        gate=args.gate,
        spin_margin=0.0 if args.no_busy_wait else SPIN_MARGIN_S,
        on_command=on_command,
        on_handshake=lambda line: print(f"  arduino: {line}", flush=True),
        wait_ready=not args.no_handshake and not args.dry_run,
        realtime=not args.no_wait,
    )

    try:
        engine.load_file(args.midi_file, track_index)
    except (EngineError, MidiSourceError) as exc:
        print(f"BLAD: {exc}", file=sys.stderr)
        return 2

    timeline = make_timeline(
        source,
        track_index,
        strategy=args.strategy,
        min_hz=args.min_hz,
        max_hz=args.max_hz,
        mode=args.transpose,
        gate=args.gate,
    )
    stats = timeline.stats

    if not timeline.commands:
        print("BLAD: ten track nie daje sie zagrac (brak nut o sensownej dlugosci).", file=sys.stderr)
        return 2

    # ---------- podsumowanie ----------
    print()
    print("Transpose mode:")
    print(args.transpose.upper())
    print()
    print("Range:")
    print(f"{args.min_hz:g}-{args.max_hz:g} Hz")

    if args.strategy != "highest":
        print()
        print("Chord strategy:")
        print(args.strategy.upper())

    tempo_note = ""

    if source.tempo.change_count:
        tempo_note = f" ({source.tempo.change_count} zmian tempa z pliku MIDI)"

    print()
    print(f"Utwor: {stats.duration:.2f} s{tempo_note}")
    print(f"Nut: {stats.notes} (zlozone oktawowo: {stats.folded}, pominiete: {stats.skipped})")

    if stats.out_of_range:
        print(f"UWAGA: {stats.out_of_range} nut nie miesci sie w zakresie - gram najblizsza oktave.")

    print()

    if args.print_schedule:
        print("Schedule:")

        for command in timeline.commands[:400]:
            print(f"  {command.time:9.3f}s  {command.text}")

        if len(timeline.commands) > 400:
            print(f"  ... i {len(timeline.commands) - 400} wiecej")

        print()

    # ---------- sprzet ----------
    print("Lacze z Arduino...", flush=True)
    connected = engine.connect(candidate.device if candidate else None)

    if not connected and not args.dry_run:
        snapshot = engine.snapshot()
        print(
            f"BLAD: {snapshot['hardware']['error'] or 'brak polaczenia'}",
            file=sys.stderr,
        )
        engine.shutdown()
        return 2

    if not args.dry_run and sys.stdin.isatty() and not args.yes and not args.no_wait:
        wait_for_enter()

    # ---------- odtwarzanie ----------
    engine.start()
    planned = timeline.duration
    print("Gram. Ctrl+C przerywa.", flush=True)

    exit_code = 0

    try:
        while True:
            started = time.monotonic()

            try:
                engine.play()
            except EngineError as exc:
                print(f"BLAD: {exc}", file=sys.stderr)
                exit_code = 2
                break

            if engine.state is not PlaybackState.PLAYING:
                snapshot = engine.snapshot()
                print(
                    f"BLAD: nie udalo sie wystartowac "
                    f"({snapshot['hardware']['error'] or 'nieznany powod'})",
                    file=sys.stderr,
                )
                exit_code = 3
                break

            while engine.state is PlaybackState.PLAYING:
                time.sleep(0.05)

            actual = time.monotonic() - started
            print(f"Koniec utworu. Zaplanowane {planned:.3f} s, realnie {actual:.3f} s.")

            if not args.loop:
                break

            print("--loop: powtarzam.")

    except KeyboardInterrupt:
        print("\nPrzerwano z klawiatury.")

    finally:
        engine.shutdown()

    snapshot = engine.snapshot()

    if snapshot["hardware"]["error"]:
        print(f"UWAGA sprzet: {snapshot['hardware']['error']}", file=sys.stderr)

    print(f"Podsumowanie: {stats.summary()}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
