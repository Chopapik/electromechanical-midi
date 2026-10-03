"""Wiazanie instancji aranzacji z fizycznymi liniami sprzetu.

Ten modul jest jedynym miejscem, ktore tlumaczy zaakceptowane zdarzenia
mechaniczne (``VirtualOrchestra.events``) na komendy linii Serial:
FDD (PLAY/STOP), VHS drum (DRUM/DRUMF) i HDD (HIT).

Kluczowa wlasciwosc: komendy sprzetowe powstaja z **tych samych** zdarzen,
ktore widzi symulacja. Dzięki temu jeden dokument aranzacji opisuje
jednoczesnie wirtualizacje i realny sprzet - nie ma drugiego modelu
mechaniki, ktory moglby sie rozjechac z podgladem.

Sprzet ma dokladnie jedna linie kazdego rodzaju, wiec dla kazdej linii
wybierana jest pierwsza instancja z trybem 'real'/'hybrid'. Pozostale
takie instancje trafiaja do listy ``unmapped`` (widocznej w UI) zamiast
byc po cichu ignorowane.
"""
from __future__ import annotations

from .timeline import (
    ARTICULATION_S,
    MIN_NOTE_S,
    SAME_HZ_EPS,
    TIME_EPS,
    Command,
    LANE_DRUM,
    LANE_FDD,
    LANE_HDD,
)
from .virtual import VirtualDeviceInstance, VirtualOrchestra

# Ktory typ instrumentu obsluguje ktora linia Serial.
LANE_FOR_TYPE = {
    'FDD': LANE_FDD,
    'DVD_SLED': LANE_FDD,
    'STEPPER_FREE': LANE_FDD,
    'VHS': LANE_DRUM,
    'HDD_VCM': LANE_HDD,
    'SOLENOID_RESONATOR': LANE_HDD,
}

# Linie, ktore wysylaja jedna nute naraz (monofoniczne). HDD jest
# one-shotem, wiec nie ma stanu do podtrzymania ani przerwy miedzy
# uderzeniami.
MONOPHONIC_LANES = (LANE_FDD, LANE_DRUM)


def bind_devices(devices: list[VirtualDeviceInstance]) -> tuple[dict[str, VirtualDeviceInstance], list[dict]]:
    """Przypisuje instancje sprzetowe do linii.

    Zwraca ``(lane -> instancja, lista nieprzypisanych)``. Instancje
    wirtualne nie trafiaja na liste nieprzypisanych - one po prostu nie
    dotykaja sprzetu.
    """
    bound: dict[str, VirtualDeviceInstance] = {}
    unmapped: list[dict] = []

    for device in devices:
        if not device.drives_hardware:
            continue

        lane = LANE_FOR_TYPE.get(device.type)

        if lane is None:
            unmapped.append({'deviceId': device.id, 'name': device.name, 'type': device.type,
                             'reason': 'NO_HARDWARE_LANE'})
            continue

        if lane in bound:
            unmapped.append({'deviceId': device.id, 'name': device.name, 'type': device.type,
                             'reason': 'LANE_TAKEN', 'lane': lane,
                             'boundTo': bound[lane].id})
            continue

        bound[lane] = device

    return bound, unmapped


def _tone_commands(events, lane: str) -> list[Command]:
    """Nuty linii monofonicznej: PLAY/STOP z legato i artykulacja powtorek.

    Ta sama logika co ``timeline.build_schedule``, ale wejściem sa juz
    zaakceptowane zdarzenia (po transpozycji i zlozeniu oktawowym), wiec
    sprzet gra dokladnie to, co pokazuje symulacja.
    """
    commands: list[Command] = []
    current_hz: float | None = None
    current_start = 0.0
    last_end = 0.0

    for event in sorted(events, key=lambda item: item.time):
        start = max(0.0, event.time, last_end)
        end = start + event.duration

        if (end - start) < MIN_NOTE_S:
            continue

        if current_hz is not None and start > last_end + TIME_EPS:
            commands.append(Command(last_end, 'stop', lane=lane))
            current_hz = None

        if current_hz is not None and abs(event.hz - current_hz) <= SAME_HZ_EPS:
            # Powtorka tej samej wysokosci wymaga realnej przerwy, inaczej
            # glowica nie zdazy sie zatrzymac i slychac jedna ciagla nuta.
            gap_start = min(start, max(start - ARTICULATION_S, current_start + MIN_NOTE_S))
            commands.append(Command(gap_start, 'stop', lane=lane))
            current_hz = None

        commands.append(Command(start, 'play', hz=event.hz, lane=lane))
        current_hz = event.hz
        current_start = start
        last_end = end

    if current_hz is not None:
        commands.append(Command(last_end, 'stop', lane=lane))

    return commands


def _drum_commands(events) -> list[Command]:
    """Nuty bebna VHS: DRUM/DRUMF. Stykajace sie nuty graja legato."""
    commands: list[Command] = []
    last_end = 0.0
    last_hz: float | None = None

    for event in sorted(events, key=lambda item: item.time):
        start = max(0.0, event.time, last_end)
        end = start + event.duration

        if (end - start) < MIN_NOTE_S:
            continue

        touching = last_hz is not None and start <= last_end + TIME_EPS
        same_pitch = touching and abs((last_hz or 0.0) - event.hz) <= SAME_HZ_EPS

        if touching and not same_pitch:
            # Zmiana wysokosci bez przerwy: dispatcher wysle sam DRUMF.
            pass
        elif last_hz is not None and not touching:
            commands.append(Command(last_end, 'drum_off', lane=LANE_DRUM))

        if not same_pitch:
            commands.append(Command(start, 'drum_on', hz=event.hz, lane=LANE_DRUM))

        last_hz = event.hz
        last_end = end

    if last_hz is not None:
        commands.append(Command(last_end, 'drum_off', lane=LANE_DRUM))

    return commands


def _hit_commands(events) -> list[Command]:
    """Uderzenia HDD/solenoidu: one-shot, bez stanu do wznowienia."""
    return [Command(event.time, 'hit', lane=LANE_HDD)
            for event in sorted(events, key=lambda item: item.time)]


def build_commands(orchestra: VirtualOrchestra,
                   bound: dict[str, VirtualDeviceInstance]) -> list[Command]:
    """Komendy sprzetowe dla instancji przypisanych do linii.

    Bierze ``orchestra.events`` (czyli tylko zdarzenia zaakceptowane przez
    model mechaniki i nie wyciszone przez mute/solo), wiec sprzet nie zagra
    niczego, czego symulacja nie pokazuje jako ACCEPTED/FOLDED/DELAYED.
    """
    if not bound:
        return []

    device_lane = {device.id: lane for lane, device in bound.items()}
    per_lane: dict[str, list] = {lane: [] for lane in device_lane.values()}

    for event in orchestra.events:
        lane = device_lane.get(event.device)

        if lane is not None:
            per_lane[lane].append(event)

    commands: list[Command] = []

    for lane, events in per_lane.items():
        if not events:
            continue

        if lane == LANE_HDD:
            commands.extend(_hit_commands(events))
        elif lane == LANE_DRUM:
            commands.extend(_drum_commands(events))
        else:
            commands.extend(_tone_commands(events, lane))

    return commands
