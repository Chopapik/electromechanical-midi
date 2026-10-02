"""Warstwa Serial: wykrywanie Arduino, wysylanie komend, handshake.

Protokol (patrz firmware/floppy/src/main.cpp):

    PING      -> PONG
    PLAY <hz> -> cisza (celowo, zeby nie zapchac bufora TX Arduino)
    STOP      -> cisza
    HOME      -> OK, po dojechaniu READY
    STATUS    -> STATUS track=... dir=... homed=... playing=... track0=... hz=...

Czytanie portu jest NIEBLOKUJACE (timeout=0). W trakcie grania host
zerka na linie z Arduino tylko wtedy, gdy sam chce - zaden odczyt nie
moze opoznic wysylki kolejnych komend.
"""

from __future__ import annotations

import dataclasses
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError as exc:  # pragma: no cover - zalezy od srodowiska
    raise SystemExit(
        "Brakuje pyserial. Zainstaluj zaleznosci hosta:\n"
        "    python -m pip install -r host/requirements.txt"
    ) from exc

BAUD = 115200

# VID producentow plytek Arduino / zgodnych klonow.
ARDUINO_VIDS = {0x2341, 0x2A03, 0x1B4F, 0x239A, 0x16C0, 0x03EB}
# VID popularnych mostkow USB<->UART.
USB_SERIAL_VIDS = {0x1A86, 0x0403, 0x10C4, 0x0483, 0x067B, 0x04D8}

ARDUINO_HINTS = ("arduino", "genuino", "usbmodem", "wchusbserial", "usbserial-14")
USB_SERIAL_HINTS = (
    "ch340",
    "ch341",
    "wch",
    "ft232",
    "ftdi",
    "cp210",
    "silabs",
    "usb serial",
    "usb-serial",
    "usb2.0-serial",
)

# Opisy, ktore nic nie mowia (macOS czesto zwraca wlasnie takie).
GENERIC_LABELS = {
    "",
    "n/a",
    "usb serial",
    "usbserial",
    "iousbhostdevice",
    "serial",
    "generic cdc",
}


class SerialLinkError(Exception):
    """Nie udalo sie otworzyc / wybrac portu."""


@dataclasses.dataclass(frozen=True)
class PortCandidate:
    device: str
    label: str
    score: int = 0
    vid: int | None = None
    pid: int | None = None

    @property
    def usb_id(self) -> str:
        if self.vid is None:
            return ""

        return f"{self.vid:04x}:{self.pid or 0:04x}"

    def __str__(self) -> str:
        return f"{self.label} @ {self.device}"


def _label(port) -> str:
    """Czytelna nazwa portu, nawet gdy system zwraca 'IOUSBHostDevice'."""
    for candidate in (port.description, port.product, port.manufacturer):
        text = (candidate or "").strip()

        if text and text.lower() not in GENERIC_LABELS:
            return text

    if port.vid in ARDUINO_VIDS:
        return "Arduino (USB Serial)"

    if port.vid in USB_SERIAL_VIDS:
        return "USB Serial"

    return "Serial"


def _score(port) -> int:
    score = 0

    haystack = " ".join(
        filter(None, (port.description, port.manufacturer, port.product, port.device))
    ).lower()

    if port.vid in ARDUINO_VIDS:
        score += 100

    if any(hint in haystack for hint in ARDUINO_HINTS):
        score += 90

    if port.vid in USB_SERIAL_VIDS:
        score += 60

    if any(hint in haystack for hint in USB_SERIAL_HINTS):
        score += 40

    # Na macOS /dev/cu.* nie czeka na linie DCD - wolelibysmy je od /dev/tty.*
    if port.device.startswith("/dev/cu."):
        score += 5

    return score


def scan_ports() -> list[PortCandidate]:
    """Wszystkie porty szeregowe, najlepiej pasujace na poczatku."""
    candidates = []

    for port in list_ports.comports():
        if not port.device:
            continue

        candidates.append(
            PortCandidate(
                device=port.device,
                label=_label(port),
                score=_score(port),
                vid=port.vid,
                pid=port.pid,
            )
        )

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.device))

    return candidates


def describe_ports(candidates: list[PortCandidate]) -> str:
    if not candidates:
        return "  (brak jakichkolwiek portow szeregowych)"

    lines = []

    for index, candidate in enumerate(candidates):
        usb_id = f" [{candidate.usb_id}]" if candidate.usb_id else ""
        lines.append(f"  [{index}] {candidate.device}  ({candidate.label}{usb_id})")

    return "\n".join(lines)


def _ask_for_port(candidates: list[PortCandidate]) -> PortCandidate:
    if not sys.stdin.isatty():
        raise SerialLinkError(
            "wykrylem kilka mozliwych portow, a nie moge zapytac (brak terminala).\n"
            "Podaj port jawnie, np. --port /dev/cu.usbmodem14101\n"
            + describe_ports(candidates)
        )

    print("Nie moge jednoznacznie wybrac portu. Dostepne porty:")
    print(describe_ports(candidates))

    while True:
        try:
            raw = input("Wybierz numer portu (albo Enter, aby przerwac): ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise SerialLinkError("przerwano wybor portu") from exc

        if not raw:
            raise SerialLinkError("nie wybrano portu")

        if raw.isdigit() and 0 <= int(raw) < len(candidates):
            return candidates[int(raw)]

        print("  ? Podaj numer z listy.")


def resolve_port(explicit: str | None = None, interactive: bool = True) -> PortCandidate:
    """Ustala port: jawny --port albo automatyczne wykrywanie Arduino."""
    candidates = scan_ports()

    if explicit:
        for candidate in candidates:
            if candidate.device == explicit:
                return candidate

        return PortCandidate(device=explicit, label="Serial (podany recznie)")

    if not candidates:
        raise SerialLinkError(
            "nie widze zadnego portu szeregowego.\n"
            "Sprawdz, czy Arduino jest podlaczone i czy nie korzysta z niego "
            "inny program (Serial Monitor / PlatformIO)."
        )

    best_score = candidates[0].score
    best = [candidate for candidate in candidates if candidate.score == best_score]

    if len(best) == 1:
        return best[0]

    # Kilka portow o tym samym wyniku: przy jedynym porcie w systemie
    # wybor jest oczywisty, inaczej pytamy.
    if len(candidates) == 1:
        return candidates[0]

    if not interactive:
        raise SerialLinkError(
            "wykrylem kilka rownorzędnych portow.\n"
            "Podaj port jawnie, np. --port /dev/cu.usbmodem14101\n"
            + describe_ports(candidates)
        )

    return _ask_for_port(candidates)


class FloppyLink:
    """Polaczenie z kontrolerem FDD. PLAY/STOP nie czekaja na odpowiedz."""

    def __init__(self, port: str, baud: int = BAUD):
        self.port = port
        self.baud = baud
        self._buffer = ""

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baud,
                timeout=0,          # czytanie nigdy nie blokuje
                write_timeout=1.0,
            )
        except serial.SerialException as exc:
            raise SerialLinkError(
                f"nie moge otworzyc {port}: {exc}\n"
                "Jesli port jest zajety, zamknij Serial Monitor w Arduino IDE "
                "albo `pio device monitor`."
            ) from exc

    # ---------- wysylanie ----------

    def send(self, command: str) -> None:
        try:
            self._serial.write((command + "\n").encode("ascii"))
        except (serial.SerialException, serial.SerialTimeoutException) as exc:
            raise SerialLinkError(f"blad zapisu do {self.port}: {exc}") from exc

    def play(self, hz: float) -> None:
        self.send(f"PLAY {hz:.2f}")

    def stop(self) -> None:
        self.send("STOP")

    def home(self) -> None:
        self.send("HOME")

    def ping(self) -> None:
        self.send("PING")

    def status(self) -> None:
        self.send("STATUS")

    # ---------- odbior (nieblokujacy) ----------

    def poll_lines(self) -> list[str]:
        """Pelne linie, ktore juz przyszly z Arduino. Nigdy nie czeka."""
        waiting = getattr(self._serial, "in_waiting", 0)

        if not waiting:
            return []

        chunk = self._serial.read(waiting)

        if not chunk:
            return []

        self._buffer += chunk.decode("ascii", errors="replace")

        lines = []

        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()

            if line:
                lines.append(line)

        return lines

    def wait_for(self, prefixes, timeout: float = 5.0) -> str | None:
        """Czeka na linie zaczynajaca sie od jednego z prefiksow.

        Zwraca linie albo None przy przekroczeniu timeoutu. Linie ERR
        zwraca od razu - decyzja nalezy do wywolujacego.
        """
        if isinstance(prefixes, str):
            prefixes = (prefixes,)

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            for line in self.poll_lines():
                if line.startswith("ERR"):
                    return line

                if line.startswith(tuple(prefixes)):
                    return line

            time.sleep(0.005)

        return None

    def wait_ready(self, timeout: float = 10.0, echo=print) -> bool:
        """Czeka az kontroler po resecie zrobi homing i zglosi READY.

        ``echo`` dostaje surowe linie z Arduino - formatowanie nalezy do
        wywolujacego (CLI dodaje prefiks, web player wrzuca je do logu).
        """
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            for line in self.poll_lines():
                echo(line)

                if line.startswith("ERR"):
                    raise SerialLinkError(f"Arduino zgloszil blad: {line}")

                if line.startswith("READY"):
                    return True

            time.sleep(0.005)

        return False

    def drain(self, echo=print) -> list[str]:
        """Oproznij bufor i pokaz, co Arduino mial do powiedzenia."""
        lines = self.poll_lines()

        for line in lines:
            echo(f"  arduino: {line}")

        return lines

    # ---------- zamkniecie ----------

    def close(self) -> None:
        try:
            if self._serial.is_open:
                self._serial.close()
        except Exception:  # pragma: no cover - zamkniecie nie moze wywalic programu
            pass

    def __enter__(self) -> "FloppyLink":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class DryRunLink:
    """Atrapa FloppyLink do --dry-run: nic nie wysyla, tylko zbiera komendy."""

    def __init__(self, **_kwargs):
        self.port = "(dry-run)"
        self.sent: list[str] = []

    def send(self, command: str) -> None:
        self.sent.append(command)

    def play(self, hz: float) -> None:
        self.send(f"PLAY {hz:.2f}")

    def stop(self) -> None:
        self.send("STOP")

    def home(self) -> None:
        self.send("HOME")

    def ping(self) -> None:
        self.send("PING")

    def poll_lines(self) -> list[str]:
        return []

    def drain(self, echo=print) -> list[str]:
        return []

    def close(self) -> None:
        pass

    def __enter__(self) -> "DryRunLink":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
