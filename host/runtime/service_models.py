"""Service operation contracts; mutable state remains owned by DeviceService."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Literal, NotRequired, Protocol, TypedDict


class ServiceOperation(StrEnum):
    HOME = 'home'
    FIRMWARE_USB = 'firmware'
    FIRMWARE_BLE = 'firmware_ble'
    POWER_ON = 'power_on'
    POWER_OFF = 'power_off'
    POWER_STATUS = 'power_status'

    @property
    def is_firmware(self):
        return self in (self.FIRMWARE_USB, self.FIRMWARE_BLE)

    @property
    def transport(self):
        return 'BLE' if self is self.FIRMWARE_BLE else 'USB'


class FirmwareStatus(TypedDict):
    stage: Literal['idle', 'prepare', 'power_off', 'build', 'upload', 'upload_ble',
                   'flash_confirmed', 'reboot_wait', 'ble_connect', 'ble_retry',
                   'ready', 'failed']
    flash: Literal['idle', 'running', 'success', 'failed']
    ble: Literal['idle', 'waiting', 'connecting', 'retrying', 'verified']
    progress: int | None
    error: str | None
    transport: NotRequired[Literal['USB', 'BLE']]


@dataclass(frozen=True)
class ServiceTicket:
    operation: ServiceOperation
    generation: int


class OtaLink(Protocol):
    def upload_firmware(self, image: bytes, key: bytes,
                        on_progress: Callable[[int], None]): ...
    def close(self): ...


@dataclass
class FirmwareSession:
    """Owns only an OTA link detached from RealOutput; never stores a private key."""

    operation: ServiceOperation
    link: OtaLink | None = None

    @property
    def is_ble(self):
        return self.operation is ServiceOperation.FIRMWARE_BLE

    def close(self):
        if self.link is not None:
            link, self.link = self.link, None
            try:
                link.close()
            except Exception:
                # Preserve the transfer outcome even when disconnect itself fails.
                pass
