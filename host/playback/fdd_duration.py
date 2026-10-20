"""Optional fixed FDD gate experiment shared by every arrangement preset."""
from dataclasses import replace


def apply(plan):
    milliseconds = float(plan.policy.get('fddFixedToneMs', 0))
    if milliseconds <= 0:
        plan.hardware['fddToneDuration'] = {'enabled': False}
        return 0
    duration = milliseconds / 1000.
    types = {device['id']: device['type'] for device in plan.devices}
    changed = 0
    events = []
    for event in plan.events:
        if event.played and event.device_type == 'FDD':
            changed += abs(event.actual_duration-duration) > 1e-9
            event = replace(event, actual_duration=duration,
                            sustain_added=event.sustain_added+duration-event.actual_duration)
        events.append(event)
    extras = []
    for extra in plan.reinforcements:
        if types.get(extra.device_id) == 'FDD':
            changed += abs(extra.duration-duration) > 1e-9
            extra = replace(extra, duration=duration)
        extras.append(extra)
    plan.events = events
    plan.reinforcements = extras
    plan.hardware['fddToneDuration'] = {
        'enabled': True, 'fixedMs': milliseconds, 'changedReservations': changed}
    return changed
