"""Software-only DVD tray accents; routing is fixed before the renderer runs."""
from __future__ import annotations

import bisect
import math
import zlib

from .performance import TrayEvent
from .virtual import VirtualDeviceInstance, effective_profile, PROFILES

def parameter(profile, key):
    value = profile.get(key)
    return PROFILES['DVD_TRAY_REFERENCE'].get(key) if value is None else value


GM_PRIORITY = {49: 3, 55: 3, 57: 3, 59: 2, 46: 1}


def motion_duration(profile, velocity: int) -> tuple[str, float]:
    if velocity >= 96:
        strength, fraction = 'STRONG', (velocity - 96) / 31
    elif velocity >= 64:
        strength, fraction = 'MEDIUM', (velocity - 64) / 31
    else:
        strength, fraction = 'SHORT', velocity / 63
    low = float(parameter(profile, f'{strength.lower()}MinMs'))
    high = float(parameter(profile, f'{strength.lower()}MaxMs'))
    return strength, (low + max(0, high - low) * fraction) / 1000


def add_reinforcement(plan) -> None:
    """Append tray-only copies of played GM accents; never edit normal events."""
    candidates = [event for event in plan.events
                  if event.channel == 9 and event.role == 'percussion' and event.note in GM_PRIORITY]
    candidates.sort(key=lambda event: (event.actual_start, -GM_PRIORITY[event.note], -event.velocity, event.id))
    trays = [VirtualDeviceInstance.parse(device) for device in plan.devices if device['type'] == 'DVD_TRAY']
    solo = any(device.get('solo') and not device.get('mute') for device in plan.devices)
    trays = [device for device in trays if not device.mute and (not solo or device.solo)]
    profiles = {device.id: effective_profile(device) for device in trays}
    busy = {device.id: float('-inf') for device in trays}
    last = {device.id: float('-inf') for device in trays}
    moves = {device.id: 0 for device in trays}
    high_times = sorted(event.actual_start for event in candidates if event.played and GM_PRIORITY[event.note] == 3)
    last_sample = {46: float('-inf'), 59: float('-inf')}
    report = {'candidates': len(candidates), 'played': 0, 'skippedBusyCooldown': 0,
              'skippedSampled': 0, 'skippedSourceDropped': 0, 'skippedDisabled': 0,
              'gmNotes': {}, 'devices': {device.id: {'events': 0, 'activeTime': 0.0} for device in trays}}
    plan.tray_events = []
    for event in candidates:
        if not event.played:
            report['skippedSourceDropped'] += 1
            continue
        if not plan.tray_enabled or not trays:
            report['skippedDisabled'] += 1
            continue
        time = event.actual_start
        priority = GM_PRIORITY[event.note]
        available = []
        sampled = False
        for device in sorted(trays, key=lambda device: (last[device.id], device.id)):
            profile = profiles[device.id]
            strength, duration = motion_duration(profile, event.velocity)
            cooldown = float(parameter(profile, 'cooldownMs')) / 1000
            # Sparse rides/hats only. Reserve an approaching crash instead of
            # occupying the motor with a low-priority accent just before it.
            if priority < 3:
                gap = float(parameter(profile, 'openHatGapMs' if event.note == 46 else 'rideGapMs')) / 1000
                threshold = float(parameter(profile, 'openHatMinVelocity' if event.note == 46 else 'rideMinVelocity'))
                upcoming = bisect.bisect_left(high_times, time)
                if (event.velocity < threshold or time - last_sample[event.note] < gap
                        or (upcoming < len(high_times) and high_times[upcoming] < time + duration + cooldown)):
                    sampled = True
                    continue
            if time >= busy[device.id] - 1e-9:
                available.append((device, strength, duration, cooldown))
        if not available:
            report['skippedSampled' if sampled else 'skippedBusyCooldown'] += 1
            continue
        device, strength, duration, cooldown = available[0]
        direction = 1 if moves[device.id] % 2 == 0 else -1
        plan.tray_events.append(TrayEvent(event.id, device.id, event.track, event.note,
                                         event.velocity, time, duration, cooldown,
                                         priority, strength, direction))
        busy[device.id] = time + duration + cooldown
        last[device.id] = time
        moves[device.id] += 1
        if priority < 3:
            last_sample[event.note] = time
        report['played'] += 1
        report['gmNotes'][str(event.note)] = report['gmNotes'].get(str(event.note), 0) + 1
        report['devices'][device.id]['events'] += 1
        report['devices'][device.id]['activeTime'] += duration
    for device_report in report['devices'].values():
        device_report['utilization'] = round(device_report['activeTime'] / plan.duration, 4) if plan.duration else 0
        device_report['activeTime'] = round(device_report['activeTime'], 3)
    plan.tray_report = report


def tray_sound(t, duration: float, velocity: int, profile, device_id: str, direction: int, xp=math):
    """Deterministic DC spin-up, belt/gear buzz and terminal plastic clack.

    Same expression for scalar math and numpy. Pitch is mechanical, not MIDI.
    """
    variant = .94 + (zlib.crc32(device_id.encode()) % 1000) / 1000 * .12
    base = float(profile.get('motorHz') or 120) * variant * (1 if direction > 0 else 1.025)
    resonance = float(profile.get('resonanceHz') or 1050) / variant
    gear = float(profile.get('gearHz') or 57) * variant
    motion_end = max(.01, duration - .022)
    phase = 2 * math.pi * base * (.75 * t + .25 * (t - .025 * (1 - xp.exp(-t / .025))))
    phase += .035 * xp.sin(2 * math.pi * 13 * t)
    attack = min(1, t / .012) if xp is math else xp.minimum(1, t / .012)
    release = max(0, min(1, (motion_end - t) / .025)) if xp is math else xp.clip((motion_end - t) / .025, 0, 1)
    irregular = xp.sin(2 * math.pi * 3431 * t + .7 * xp.sin(2 * math.pi * 631 * t))
    motor = (.50 * xp.sin(phase) + .15 * xp.sin(phase * 5) + .12 * irregular)
    motor *= attack * release * (.82 + .18 * xp.sin(2 * math.pi * gear * t))
    clack_t = max(0, t - motion_end) if xp is math else xp.maximum(0, t - motion_end)
    clack = xp.exp(-clack_t * 140) * (xp.sin(2 * math.pi * resonance * clack_t) + .25 * irregular)
    clack *= (t >= motion_end) * (.35 + .65 * velocity / 127)
    return (motor + clack) * (velocity / 127) ** .7
