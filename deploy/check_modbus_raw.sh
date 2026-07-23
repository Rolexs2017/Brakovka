#!/usr/bin/env bash
# Raw Modbus RTU over USB RS485 adapter (settings.json).
set -euo pipefail
VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT"
"$PYTHON" - <<'PY'
import os
import sys
import time

sys.path.insert(0, ".")

import serial

from brakovka_pi.config import load_runtime_config


def modbus_crc(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_read_holding(unit_id: int, address: int, count: int = 1) -> bytes:
    pdu = bytes(
        [
            unit_id & 0xFF,
            0x03,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ]
    )
    crc = modbus_crc(pdu)
    return pdu + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def check_crc(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    got = frame[-2] | (frame[-1] << 8)
    return modbus_crc(frame[:-2]) == got


_, _, sc, vc, *_ = load_runtime_config()
reg = int(vc.reg_status)

print(f"port={sc.port} baud={sc.baudrate} unit={sc.unit_id}")
print(f"read reg=0x{reg:04X} ({reg}) profile={vc.profile}")
print("DE=USB adapter (auto)")

ser = serial.Serial(sc.port, sc.baudrate, bytesize=8, parity="N", stopbits=1, timeout=1.0)
ser.rtscts = False
ser.reset_input_buffer()
print("idle RX")

req = build_read_holding(int(sc.unit_id), reg, 1)
print(f"TX {req.hex(' ')}")

ser.reset_input_buffer()
ser.write(req)
ser.flush()
frame_s = len(req) * 10 / float(sc.baudrate)
time.sleep(max(0.05, frame_s + 0.02))

print("after TX")
time.sleep(0.05)

rx = ser.read(64)
print(f"RX ({len(rx)} bytes): {rx.hex(' ') if rx else '(empty)'}")
if not rx:
    print("Нет RX. Проверьте port, A/B, GND, unit_id, baud; ls /dev/ttyUSB*")
elif check_crc(rx):
    print("OK: CRC valid")
else:
    print("CRC ERROR")

ser.close()
PY
