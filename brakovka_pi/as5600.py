from __future__ import annotations

from dataclasses import dataclass

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
    def __init__(self, bus: int = 1, address: int = AS5600_ADDR) -> None:
        self._bus_num = bus
        self._addr = address
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
        # STATUS (0x0B) + RAW_ANGLE H/L (0x0C/0x0D) in one I2C transaction.
        block = self._bus.read_i2c_block_data(self._addr, REG_STATUS, 3)
        status = int(block[0]) & 0xFF
        raw = ((int(block[1]) << 8) | int(block[2])) & 0x0FFF
        return As5600Sample(raw=raw, status=status)
