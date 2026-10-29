"""Checked WebSocket command boundary; no runtime, transport or musical decisions.

Validation preserves valid dictionaries and optional/default fields unchanged.
Unknown extension fields remain compatible. Runtime services own range, state,
session, Origin and hardware checks.
"""
from __future__ import annotations

import math
from typing import Literal, NotRequired, TypedDict, cast

from arrangement_presets import is_preset


class Request(TypedDict):
    requestId: NotRequired[str | None]


class SimpleCommand(Request):
    action: Literal['play', 'pause', 'stop', 'lab_enter', 'lab_leave']


class FileCommand(Request):
    action: Literal['set_file']
    file: str


class PresetCommand(Request):
    action: Literal['arrangement_preset']
    preset: str


class SeekCommand(Request):
    action: Literal['seek']
    position: float


class OutputCommand(Request):
    action: Literal['output']
    mode: Literal['REAL', 'VIRTUAL']


class MuteCommand(Request):
    action: Literal['mute']
    deviceId: str
    muted: bool


class MuteGroupCommand(Request):
    action: Literal['mute_group']
    deviceIds: list[str]
    muted: bool


class WaveformCommand(Request):
    action: Literal['speaker_waveform']
    deviceId: str
    waveform: Literal['pulse']


class VolumeCommand(Request):
    action: Literal['speaker_volume']
    deviceId: str
    output: Literal['REAL', 'VIRTUAL']
    value: float


class Modulation(TypedDict, total=False):
    mode: Literal['off', 'sine', 'triangle']
    depth: float
    period: float


class LabCommand(Request):
    action: Literal['lab_test', 'lab_update']
    deviceId: str
    hz: NotRequired[float]
    duration: NotRequired[float | None]
    modulation: NotRequired[Modulation | None]


class LabStopCommand(Request):
    action: Literal['lab_stop']
    deviceId: str


class ServiceCommand(Request):
    action: Literal['service']
    operation: Literal['home', 'firmware', 'firmware_ble', 'power_on', 'power_off', 'power_status', 'reset']
    confirmed: NotRequired[bool]


class AudioErrorCommand(Request):
    action: Literal['audio_error']
    epoch: int
    message: NotRequired[str]


class ClientErrorCommand(Request):
    action: Literal['client_error']
    kind: str
    message: str
    stack: NotRequired[str]
    occurredAt: NotRequired[str]


class AudioAckCommand(Request):
    action: Literal['audio_ack']
    token: str


class SyncCommand(Request):
    action: Literal['sync']
    sent: float


ClientCommand = (SimpleCommand | FileCommand | PresetCommand | SeekCommand |
                 OutputCommand | MuteCommand | MuteGroupCommand | WaveformCommand | VolumeCommand |
                 LabCommand | LabStopCommand | ServiceCommand | AudioErrorCommand |
                 AudioAckCommand | SyncCommand | ClientErrorCommand)

COMMAND_ACTIONS = frozenset((
    'play', 'pause', 'stop', 'lab_enter', 'lab_leave', 'set_file',
    'arrangement_preset', 'seek', 'output', 'mute', 'mute_group', 'speaker_waveform',
    'speaker_volume', 'lab_test', 'lab_update', 'lab_stop', 'service',
    'audio_error', 'audio_ack', 'sync', 'client_error',
))


def _number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _field(message, name, check, label, error=None):
    if name not in message:
        raise ValueError(str(KeyError(name)))
    if not check(message[name]):
        raise ValueError(error or f'Invalid {label}')


def validate_command(raw: object) -> ClientCommand:
    if not isinstance(raw, dict):
        raise ValueError('Command must be a JSON object')
    if raw.get('requestId') is not None and not isinstance(raw['requestId'], str):
        raise ValueError('Invalid requestId')
    action = raw.get('action')
    if not isinstance(action, str) or action not in COMMAND_ACTIONS:
        raise ValueError('Unknown action')
    if action in ('set_file', 'arrangement_preset'):
        key = 'file' if action == 'set_file' else 'preset'
        _field(raw, key, lambda value:isinstance(value, str), key,
               'Unknown arrangement preset' if key=='preset' else None)
        if action == 'arrangement_preset' and not is_preset(raw['preset']):
            raise ValueError('Unknown arrangement preset')
    if action in ('mute', 'speaker_waveform', 'speaker_volume', 'lab_test', 'lab_update', 'lab_stop'):
        _field(raw, 'deviceId', lambda value:isinstance(value, str), 'deviceId')
    if action == 'seek':
        _field(raw, 'position', _number, 'position')
    elif action == 'output':
        _field(raw, 'mode', lambda value:isinstance(value, str) and value in ('REAL', 'VIRTUAL'), 'output', 'Unknown output')
    elif action == 'mute_group':
        _field(raw, 'deviceIds', lambda value:isinstance(value,list) and 0<len(value)<=32 and all(isinstance(item,str) for item in value), 'deviceIds')
        _field(raw, 'muted', lambda value:isinstance(value,bool), 'mute', 'mute must be boolean')
    elif action == 'mute':
        _field(raw, 'muted', lambda value:isinstance(value, bool), 'mute', 'mute must be boolean')
    elif action == 'speaker_waveform':
        _field(raw, 'waveform', lambda value:value == 'pulse', 'speaker waveform')
    elif action == 'speaker_volume':
        _field(raw, 'output', lambda value:isinstance(value, str) and value in ('REAL', 'VIRTUAL'), 'speaker volume')
        _field(raw, 'value', _number, 'speaker volume')
    elif action in ('lab_test', 'lab_update'):
        if 'hz' in raw:
            _field(raw, 'hz', _number, 'frequency')
        if 'duration' in raw and raw['duration'] is not None:
            _field(raw, 'duration', _number, 'duration')
        modulation = raw.get('modulation')
        if modulation is not None:
            if not isinstance(modulation, dict):
                raise ValueError('Nieprawidłowa modulacja')
            if 'mode' in modulation:
                _field(modulation, 'mode', lambda value:isinstance(value, str) and value in ('off', 'sine', 'triangle'), 'modulation mode', 'Nieznana modulacja częstotliwości')
            for name in ('depth', 'period'):
                if name in modulation:
                    _field(modulation, name, _number, 'modulation '+name)
    elif action == 'service':
        _field(raw, 'operation', lambda value:isinstance(value, str) and value in (
            'home', 'firmware', 'firmware_ble', 'power_on', 'power_off', 'power_status', 'reset'), 'maintenance operation', 'Unknown maintenance operation')
        if 'confirmed' in raw:
            _field(raw, 'confirmed', lambda value:isinstance(value, bool), 'confirmation')
    elif action == 'audio_error':
        _field(raw, 'epoch', lambda value:isinstance(value, int) and not isinstance(value, bool), 'epoch')
        if 'message' in raw:
            _field(raw, 'message', lambda value:isinstance(value, str), 'audio error')
    elif action == 'client_error':
        for field in ('kind','message'):
            _field(raw,field,lambda value:isinstance(value,str) and len(value)<=4000,field)
        if 'occurredAt' in raw:_field(raw,'occurredAt',lambda value:isinstance(value,str) and len(value)<=100,'occurredAt')
        if 'stack' in raw:_field(raw,'stack',lambda value:isinstance(value,str) and len(value)<=4000,'stack')
    elif action == 'audio_ack':
        _field(raw, 'token', lambda value:isinstance(value, str), 'audio token')
    elif action == 'sync':
        _field(raw, 'sent', _number, 'sync time')
    return cast(ClientCommand, raw)
