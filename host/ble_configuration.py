"""Bounded, non-musical setup before the playback clock starts."""
import re

MAX_CONFIGURATION = 4096
_COMMAND = re.compile(
    rb'(?:TRACKS (?:OFF|SET(?: -?\d+){4})'
    rb'|FDD [1-8] (?:PROFILE \d+ \d+ \d+|ENABLE [01])'
    rb'|SLED [1-4] (?:PROFILE [\d.]+ [\d.]+ [\d.]+|ENABLE [01]|DIR (?:FWD|REV))'
    rb'|HDD [1-4] (?:PROFILE \d+ \d+ \d+|ENABLE [01])'
    rb'|VHS2? (?:ENABLE [01]|WAVE pulse))'
)


def validate_configuration(data):
    """Reject the entire payload before sending; never accept motion or power."""
    if not 1 <= len(data) <= MAX_CONFIGURATION or not data.endswith(b'\n'):
        raise ValueError('Invalid BLE configuration size/framing')
    if any(len(line) > 95 or not _COMMAND.fullmatch(line) for line in data[:-1].split(b'\n')):
        raise ValueError('BLE configuration accepts only device setup commands')


def command_groups(data, capacity):
    """Preserve complete lines and ordering, with no extra SYNC-sized packet."""
    group = b''
    for line in data.splitlines(keepends=True):
        if group and len(group) + len(line) > capacity:
            yield group
            group = b''
        group += line
    if group:
        yield group
