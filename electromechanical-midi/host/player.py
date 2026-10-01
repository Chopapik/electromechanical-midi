#!/usr/bin/env python3
"""Odtwarzacz MIDI na mechanicznej stacji dyskietek 3.5" (Arduino Uno).

    plik .mid -> ten program -> USB Serial -> Arduino -> STEP/DIR -> FDD

Podstawowe uzycie:

    python host/player.py midi/test.mid
    python host/player.py midi/test.mid --track 2
    python host/player.py midi/test.mid --dry-run

Caly timing muzyczny liczy ten program. Arduino dostaje tylko
"PLAY <hz>" i "STOP" i ma je wykonac natychmiast.

Timing opiera sie na zegarze monotonicznym i BEZWZGLEDNYM czasie
startu odtwarzania, dlatego opoznienia Serial nie kumuluja sie
w trakcie utworu (brak narastajacego dryfu).
"""

from __future__ import annotations

import argparse
import dataclasses
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
from midi_source import STRATEGIES, MidiSource, MidiSourceError, NoteSpan
from pitch import (
    COMFORT_MAX_HZ,
    COMFORT_MIN_HZ,
    FOLD_MODES,
    fold_note,
)

# ------------------------------------------------------------
# Strojenie harmonogramu
# ------------------------------------------------------------

TIME_EPS = 1e-4        # 0.1 ms - ponizej tego traktujemy czasy jako rowne
SAME_HZ_EPS = 0.01     # ponizej tego to ta sama wysokosc dzwieku
MIN_NOTE_S = 0.010     # krotszych nut mechanika i tak nie zagra

# Powtorka tej samej nuty musi miec realna przerwe. Samo STOP+PLAY w tej
# samej chwili nic nie daje: obie komendy dochodza do Arduino razem, wiec
# glowica nie zdazy sie zatrzymac i slychac jedna ciagla nuta. Dlatego
# STOP leci ARTICULATION_S przed poczatkiem powtorki.
ARTICULATION_S = 0.012

SPIN_MARGIN_S = 0.0015  # ostatnie 1.5 ms czekamy aktywnie, nie przez sleep

# Bledy Arduino, po ktorych przerywamy utwor: stan mechaniki wymaga homingu.
FATAL_ERRORS = ("ERR NOT_HOMED", "ERR POS_LOST", "ERR HOME_FAILED", "ERR HOST_TIMEOUT")

# Co ile sekund wysylamy PING, gdy do nastepnej komendy jest daleko.
# Arduino ma watchdog: bez komend przez dluzsza chwile zatrzymuje kroki.
KEEPALIVE_S = 1.0


class ArduinoFault(RuntimeError):
    """Kontroler zglosil blad, po ktorym dalsze granie nie ma sensu."""


# ============================================================
# HARMONOGRAM
# ============================================================


@dataclasses.dataclass(frozen=True)
class Command:
    """Jedna komenda do Arduino w absolutnym czasie odtwarzania."""

    time: float
    kind: str                      # "play" | "stop"
    hz: float | None = None
    note: int | None = None

    @property
    def text(self) -> str:
        if self.kind == "play":
            return f"PLAY {self.hz:.2f}"

        return "STOP"


@dataclasses.dataclass
class ScheduleStats:
    """Co sie stalo z nutami przy budowaniu harmonogramu."""

    notes: int = 0
    skipped: int = 0
    folded: int = 0
    out_of_range: int = 0
    play_commands: int = 0
    stop_commands: int = 0
    duration: float = 0.0
    min_hz: float = 0.0
    max_hz: float = 0.0

    def summary(self) -> str:
        range_text = ""

        if self.notes:
            range_text = f", wyslane {self.min_hz:.1f}-{self.max_hz:.1f} Hz"

        return (
            f"nut: {self.notes} "
            f"(zlozone oktawowo: {self.folded}, pominiete: {self.skipped}"
            f"{range_text})\n"
            f"   komendy: {self.play_commands} PLAY / {self.stop_commands} STOP\n"
            f"   dlugosc utworu: {self.duration:.2f} s"
        )


def build_schedule(
    spans: list[NoteSpan],
    *,
    min_hz: float = COMFORT_MIN_HZ,
    max_hz: float = COMFORT_MAX_HZ,
    mode: str = "auto",
    gate: float = 1.0,
) -> tuple[list[Command], ScheduleStats]:
    """Zamienia nuty (juz monofoniczne) na liste komend PLAY/STOP.

    Zasady:
      * kazda nuta -> PLAY <hz> zlozone oktawowo do [min_hz, max_hz],
      * przerwa w zapisie -> STOP na koncu poprzedniej nuty,
      * nuty stykajace sie -> tylko PLAY (legato, bez sztucznej przerwy),
      * powtorka tej samej wysokosci -> STOP ARTICULATION_S przed powtorka
        i PLAY w jej poczatku, bo inaczej mechanika zagralaby jedna
        ciagla nuta zamiast dwoch.
    """
    commands: list[Command] = []
    stats = ScheduleStats()

    current_hz: float | None = None
    current_start = 0.0
    last_end = 0.0

    for span in spans:
        start = max(0.0, span.start, last_end)
        end = start + span.duration * gate

        if (end - start) < MIN_NOTE_S:
            stats.skipped += 1
            continue

        folded = fold_note(span.note, min_hz, max_hz, mode)

        stats.notes += 1

        if folded.octave_shift:
            stats.folded += 1

        if not folded.in_range:
            stats.out_of_range += 1

        if stats.min_hz == 0.0 or folded.hz < stats.min_hz:
            stats.min_hz = folded.hz

        if folded.hz > stats.max_hz:
            stats.max_hz = folded.hz

        if current_hz is not None and start > last_end + TIME_EPS:
            commands.append(Command(last_end, "stop"))
            current_hz = None

        if current_hz is not None and abs(folded.hz - current_hz) <= SAME_HZ_EPS:
            # Powtorka tej samej wysokosci wymaga realnej przerwy, ale nie
            # mozemy przy tym skrocic poprzedniej nuty ponizej MIN_NOTE_S.
            gap_start = min(
                start,
                max(start - ARTICULATION_S, current_start + MIN_NOTE_S),
            )

            commands.append(Command(gap_start, "stop"))
            current_hz = None

        commands.append(Command(start, "play", hz=folded.hz, note=span.note))

        current_hz = folded.hz
        current_start = start
        last_end = end

    if current_hz is not None:
        commands.append(Command(last_end, "stop"))

    stats.play_commands = sum(1 for command in commands if command.kind == "play")
    stats.stop_commands = len(commands) - stats.play_commands
    stats.duration = commands[-1].time if commands else 0.0

    return commands, stats


# ============================================================
# ZEGAR
# ============================================================


def wait_until(target: float, busy_wait: bool = True) -> None:
    """Czeka do BEZWZGLEDNEGO czasu (zegar monotoniczny).

    Dzieki temu, ze cel jest absolutny, kazde opoznienie (Serial, GIL,
    system) przesuwa tylko te jedna komende - nie kumuluje sie.
    """
    while True:
        remaining = target - time.monotonic()

        if remaining <= 0.0:
            return

        if busy_wait and remaining <= SPIN_MARGIN_S:
            while time.monotonic() < target:
                pass

            return

        time.sleep(remaining - SPIN_MARGIN_S if busy_wait else remaining)


def wait_with_keepalive(target: float, link, busy_wait: bool = True) -> int:
    """Czeka do celu, wysylajac PING gdy przerwa jest dluga.

    Arduino ma watchdog: jesli host zamilknie na dluzej niz kilka sekund
    (np. zawiesi sie albo ktos wyjmie USB), firmware sam zatrzymuje kroki.
    Dlatego przy dlugich nutach i przerwach podtrzymujemy lacze.

    Zwraca liczbe wyslanych PING.
    """
    pings = 0

    while True:
        remaining = target - time.monotonic()

        if remaining <= 0.0:
            return pings

        if remaining <= KEEPALIVE_S:
            wait_until(target, busy_wait=busy_wait)
            return pings

        time.sleep(KEEPALIVE_S)
        link.ping()
        link.poll_lines()  # PONG nie moze zapchac bufora TX Arduino
        pings += 1


def play_schedule(
    commands: list[Command],
    link,
    *,
    verbose: bool = False,
    busy_wait: bool = True,
    wait: bool = True,
    echo=print,
) -> tuple[float, float, int]:
    """Odtwarza harmonogram.

    Zwraca (czas zaplanowany, czas rzeczywisty, liczba bledow niekrytycznych).
    """
    origin = time.monotonic()
    warnings = 0

    for command in commands:
        target = origin + command.time

        if verbose:
            echo(f"   {command.time:8.3f}s  {command.text}")

        if wait:
            wait_with_keepalive(target, link, busy_wait=busy_wait)

        # Nieblokujacy przeglad odpowiedzi Arduino - nigdy nie opoznia PLAY.
        for line in link.poll_lines():
            if not line.startswith("ERR"):
                if verbose:
                    echo(f"   arduino: {line}")

                continue

            echo(f"   arduino: {line}")

            if line.startswith(FATAL_ERRORS):
                raise ArduinoFault(line)

            warnings += 1

        if command.kind == "play":
            link.play(command.hz)
        else:
            link.stop()

    return (
        commands[-1].time if commands else 0.0,
        time.monotonic() - origin,
        warnings,
    )


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

    # ---------- harmonogram ----------
    try:
        spans = source.selected_notes(track_index, args.strategy)
        commands, stats = build_schedule(
            spans,
            min_hz=args.min_hz,
            max_hz=args.max_hz,
            mode=args.transpose,
            gate=args.gate,
        )
    except (MidiSourceError, ValueError) as exc:
        print(f"BLAD: {exc}", file=sys.stderr)
        return 2

    if not commands:
        print("BLAD: ten track nie daje sie zagrac (brak nut o sensownej dlugosci).", file=sys.stderr)
        return 2

    # ---------- port ----------
    candidate = None

    if args.dry_run:
        print("Serial:")
        print("(dry-run - sprzet nietkniety)")
    else:
        try:
            candidate = resolve_port(args.port, interactive=sys.stdin.isatty())
        except SerialLinkError as exc:
            print(f"BLAD: {exc}", file=sys.stderr)
            return 2

        print("Serial:")
        print(f"{candidate.label} @ {candidate.device}")

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

    if args.print_schedule or args.dry_run:
        print("Schedule:")

        for command in commands[:400]:
            print(f"  {command.time:9.3f}s  {command.text}")

        if len(commands) > 400:
            print(f"  ... i {len(commands) - 400} wiecej")

        print()

    # ---------- sprzet ----------
    link = DryRunLink() if args.dry_run else None

    if not args.dry_run:
        try:
            link = FloppyLink(candidate.device, args.baud)
        except SerialLinkError as exc:
            print(f"BLAD: {exc}", file=sys.stderr)
            return 2

        # Otwarcie portu na Uno powoduje reset, po ktorym firmware sam
        # robi homing i wysyla READY. Czekamy na to, zanim zaczniemy grac.
        if not args.no_handshake:
            print("Czekam na READY po homingu...", flush=True)

            try:
                if not link.wait_ready(timeout=12.0, echo=lambda text: print(text, flush=True)):
                    print(
                        "UWAGA: brak READY - gram mimo to. "
                        "Sprawdz zasilanie stacji i czy TRACK0 jest podlaczony.",
                        file=sys.stderr,
                    )
            except SerialLinkError as exc:
                print(f"BLAD: {exc}", file=sys.stderr)
                link.close()
                return 2

    if not args.dry_run and sys.stdin.isatty() and not args.yes and not args.no_wait:
        wait_for_enter()

    # ---------- odtwarzanie ----------
    busy_wait = not args.no_busy_wait
    wait = not args.no_wait

    print("Gram. Ctrl+C przerywa.", flush=True)

    exit_code = 0
    started = time.monotonic()

    try:
        while True:
            planned, actual, warnings = play_schedule(
                commands,
                link,
                verbose=args.verbose,
                busy_wait=busy_wait,
                wait=wait,
            )

            print(f"Koniec utworu. Zaplanowane {planned:.3f} s, realnie {actual:.3f} s.")

            if warnings:
                print(
                    f"UWAGA: Arduino odrzucil {warnings} komend "
                    "(patrz linie 'arduino: ERR ...' powyzej).",
                    file=sys.stderr,
                )

            if not args.loop:
                break

            print("--loop: powtarzam.")

    except KeyboardInterrupt:
        print("\nPrzerwano z klawiatury.")

    except ArduinoFault as exc:
        print(f"\nPrzerwano: kontroler zgloszil {exc}.", file=sys.stderr)
        print("Robie ponowny homing...", file=sys.stderr)
        exit_code = 4

        # Zgodnie z zalozeniem: przy niepewnej pozycji wracamy do TRACK0,
        # zeby maszyna nie zostala w nieznanym stanie.
        try:
            link.home()

            if link.wait_ready(timeout=10.0, echo=lambda text: print(f"  {text}", file=sys.stderr)):
                print("Homing OK - pozycja pewna.", file=sys.stderr)
            else:
                print("UWAGA: homing nie potwierdzil gotowosci.", file=sys.stderr)
        except (SerialLinkError, ArduinoFault) as homing_error:
            print(f"UWAGA: nie udalo sie zrobic homingu: {homing_error}", file=sys.stderr)

    except SerialLinkError as exc:
        print(f"BLAD Serial: {exc}", file=sys.stderr)
        exit_code = 3

    finally:
        try:
            link.stop()
        except Exception:
            pass

        link.close()

    print(f"Podsumowanie: {stats.summary()}")
    print(f"Razem z uzbrojeniem sprzetu: {time.monotonic() - started:.2f} s")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
