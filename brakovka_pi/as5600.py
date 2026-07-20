from __future__ import annotations

from dataclasses import dataclass
from time import sleep

try:
    from smbus2 import SMBus  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    SMBus = None


AS5600_ADDR = 0x36

REG_STATUS = 0x0B
REG_RAW_ANGLE_H = 0x0C
REG_RAW_ANGLE_L = 0x0D

# STATUS bit 5 (0x20) = MD — magnet detected
STATUS_MD = 0x20


@dataclass
class As5600Sample:
    raw: int  # 0..4095
    status: int = 0


class As5600:
    def __init__(
        self,
        bus: int = 1,
        address: int = AS5600_ADDR,
        *,
        retries: int = 2,
        retry_delay_s: float = 0.0005,
    ) -> None:
        self._bus_num = bus
        self._addr = address
        self._retries = max(0, int(retries))
        self._retry_delay_s = max(0.0, float(retry_delay_s))
        self._bus = None

    def open(self) -> None:
        if SMBus is None:
            raise RuntimeError("smbus2 is not installed (AS5600 I2C unavailable on this host)")
        if self._bus is None:
            self._bus = SMBus(self._bus_num)

    def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:
                pass
            self._bus = None

    def read(self) -> As5600Sample:
        if self._bus is None:
            self.open()

        assert self._bus is not None
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                # STATUS (0x0B) + RAW_ANGLE H/L (0x0C/0x0D) in one I2C transaction.
                block = self._bus.read_i2c_block_data(self._addr, REG_STATUS, 3)
                status = int(block[0]) & 0xFF
                raw = ((int(block[1]) << 8) | int(block[2])) & 0x0FFF
                return As5600Sample(raw=raw, status=status)
            except Exception as exc:
                last_exc = exc
                if attempt < self._retries and self._retry_delay_s > 0.0:
                    sleep(self._retry_delay_s)
        assert last_exc is not None
        raise last_exc
