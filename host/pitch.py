"""Konwersja wysokosci dzwieku MIDI <-> Hz oraz skladanie oktawowe.

Domyslny zakres FDD to 130-410 Hz. Gorna granica jest skalibrowana
dla konkretnej stacji w docelowej orientacji; muzyczny dol pozostaje
dotychczasowym ustawieniem, nie nowym wynikiem pomiaru.
Ten modul sprowadza dowolna nuta MIDI do tego zakresu wylacznie przez
przesuniecie o cale oktawy - klasa wysokosci dzwieku nigdy sie nie zmienia.

Przyklady (zakres 130-410 Hz):

    C5 = 523.25 Hz  ->  C4 = 261.63 Hz   (shift -1)
    C2 =  65.41 Hz  ->  C3 = 130.81 Hz   (shift +1)
    A4 = 440.00 Hz  ->  A3 = 220.00 Hz   (shift -1)

Jesli zakres bylby wezszy niz oktawa (czego przy 130-410 Hz nie ma),
dla czesci nut nie istnieje oktawa mieszczaca sie w zakresie. Wtedy
zwracamy najblizsza czestotliwosc i ustawiamy ``in_range=False``.

UWAGA o skokach oktawowych (tryb ``auto``):
    Przy zakresie szerszym niz oktawa granica "zostaje / spada o oktave"
    wypada na 410 Hz. Melodia przechodzaca przez te granice (np. G4 =
    392.0 Hz zostaje, G#4 = 415.3 Hz spada do 207.7 Hz) dostanie skok
    o oktave w dol. Jest to nieuniknione przy skladaniu "o minimalna
    liczbe oktaw" i tak wlasnie dziala tryb ``auto``.

    Tryby ``low`` i ``high`` wybieraja dla KAZDEJ nuty zawsze ta sama
    oktave (najnizsza albo najwyzsza mieszczaca sie w zakresie). Dzieki
    temu zakres docelowy jest dokladnie jedno-oktawowy, kazda klasa
    wysokosci ma w nim dokladnie jedna reprezentacje i melodia NIE ma
    skokow oktawowych - jest tylko przesunieta w dol albo w gore.
"""

from __future__ import annotations

import dataclasses
import math

A4_MIDI = 69
A4_HZ = 440.0

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Profil tej konkretnej FDD w normalnej/docelowej orientacji.
# Stress-test na roznych pozycjach, delta krokow po powrocie do TRACK0:
# 410 Hz: 38/40; 411-423 Hz: graniczne/niestabilne; 424 i 425 Hz: 0/40 kazde.
# Mechanical minimum <= 5 Hz (5/5 bez utraty krokow), NIE muzyczny comfort min.
# Muzyczny dol nie zostal jeszcze ustalony; zachowujemy dotychczasowe 130 Hz.
# Metodologia i wyniki: README.md, "Fizyczna kalibracja FDD".
COMFORT_MIN_HZ = 130.0
COMFORT_MAX_HZ = 410.0

# Tryby skladania oktawowego:
#   auto - jak najmniejsza ingerencja: nuta zostaje, jesli sie miesci
#          (domyslne; C5 = 523 Hz -> C4 = 261.6 Hz)
#   low  - zawsze najnizsza oktawa z zakresu (130-260 Hz): bez skokow
#   high - zawsze najwyzsza oktawa z zakresu (205-410 Hz): bez skokow
FOLD_MODES = ("auto", "low", "high")

# Ile oktaw w gore/dol rozwazamy przy szukaniu miejsca w zakresie.
_MAX_OCTAVE_SHIFT = 10

_EPS = 1e-6


class PitchError(ValueError):
    """Bledne parametry konwersji wysokosci dzwieku."""


def midi_to_hz(note: float) -> float:
    """Nuta MIDI (0-127, moze byc ulamkowa) -> Hz (A4 = 440 Hz)."""
    return A4_HZ * (2.0 ** ((note - A4_MIDI) / 12.0))


def hz_to_midi(hz: float) -> float:
    """Hz -> nuta MIDI (ulamkowa)."""
    if hz <= 0.0:
        raise PitchError(f"czestotliwosc musi byc dodatnia, jest {hz!r}")

    return A4_MIDI + 12.0 * math.log2(hz / A4_HZ)


def note_name(note: int) -> str:
    """72 -> 'C5' (MIDI 60 == C4, tzw. middle C)."""
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


@dataclasses.dataclass(frozen=True)
class FoldedNote:
    """Wynik zlozenia jednej nuty do zakresu stacji."""

    midi_note: int        # nuta zapisana w pliku MIDI
    hz: float             # czestotliwosc do wyslania na Arduino
    octave_shift: int     # ile oktaw przesunieto (+ w gore, - w dol)
    in_range: bool        # czy trafila w [min_hz, max_hz]

    @property
    def name(self) -> str:
        """Nazwa nuty zapisanej w MIDI."""
        return note_name(self.midi_note)

    @property
    def played_midi_note(self) -> int:
        """Nuta, ktora faktycznie zagra (zapisana + przesuniecie oktawowe)."""
        return self.midi_note + 12 * self.octave_shift

    @property
    def played_name(self) -> str:
        return note_name(self.played_midi_note)

    def describe(self) -> str:
        shift = ""
        if self.octave_shift:
            sign = "+" if self.octave_shift > 0 else "-"
            shift = f" ({sign}{abs(self.octave_shift)} okt.)"
        flag = "" if self.in_range else " [POZA ZAKRESEM]"

        return (
            f"{self.name} -> {self.played_name} "
            f"{self.hz:7.2f} Hz{shift}{flag}"
        )


def _candidates(base_hz: float):
    """Pary (shift, hz) dla oktaw w okolicy zapisanej nuty."""
    return [
        (shift, base_hz * (2.0 ** shift))
        for shift in range(-_MAX_OCTAVE_SHIFT, _MAX_OCTAVE_SHIFT + 1)
    ]


def _distance_outside(hz: float, min_hz: float, max_hz: float) -> float:
    """0.0 gdy hz w zakresie, inaczej odleglosc do blizszej granicy."""
    if hz < min_hz:
        return min_hz - hz

    if hz > max_hz:
        return hz - max_hz

    return 0.0


def fold_note(
    note: int,
    min_hz: float = COMFORT_MIN_HZ,
    max_hz: float = COMFORT_MAX_HZ,
    mode: str = "auto",
) -> FoldedNote:
    """Sprowadza nuta MIDI do [min_hz, max_hz], przesuwajac ja o oktawy.

    Podniesienie/obnizenie o oktave nie zmienia klasy wysokosci dzwieku,
    wiec melodia zostaje rozpoznawalna.
    """
    if min_hz <= 0.0 or max_hz <= 0.0:
        raise PitchError("zakres czestotliwosci musi byc dodatni")

    if max_hz < min_hz:
        raise PitchError(
            f"max_hz ({max_hz}) musi byc >= min_hz ({min_hz})"
        )

    if mode not in FOLD_MODES:
        raise PitchError(
            f"nieznany tryb skladania {mode!r}, dostepne: {', '.join(FOLD_MODES)}"
        )

    base_hz = midi_to_hz(note)
    candidates = _candidates(base_hz)

    fitting = [
        (shift, hz)
        for shift, hz in candidates
        if min_hz - _EPS <= hz <= max_hz + _EPS
    ]

    if fitting:
        shift, hz = _pick(fitting, min_hz, max_hz, mode)
        return FoldedNote(note, hz, shift, True)

    # Zakres wezszy niz oktawa - nie ma idealnego rozwiazania.
    # Bierzemy oktave najblizsza zakresowi, a przy remisie blizsza srodka.
    centre = (min_hz + max_hz) / 2.0
    shift, hz = min(
        candidates,
        key=lambda item: (
            _distance_outside(item[1], min_hz, max_hz),
            abs(math.log2(item[1] / centre)),
        ),
    )

    return FoldedNote(note, hz, shift, False)


def _pick(fitting, min_hz: float, max_hz: float, mode: str):
    """Wybiera oktave sposrod kandydatow mieszczacych sie w zakresie.

    ``low``/``high`` biora zawsze skrajna oktave, wiec dla kazdej nuty
    wybieraja ta sama, jedno-oktawowa czesc zakresu - melodia nie ma
    wtedy skokow oktawowych.
    """
    if mode == "low":
        return min(fitting, key=lambda item: item[0])

    if mode == "high":
        return max(fitting, key=lambda item: item[0])

    # auto: mozliwie najmniejsza ingerencja w zapisana wysokosc,
    # przy remisie blizej srodka zakresu, a potem w dol.
    centre = (min_hz + max_hz) / 2.0

    return min(
        fitting,
        key=lambda item: (
            abs(item[0]),
            abs(math.log2(item[1] / centre)),
            item[0],
        ),
    )
