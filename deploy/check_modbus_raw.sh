#!/usr/bin/env bash
# Raw Modbus RTU with hardware UART RTS0 (GPIO17 / RS485Settings).
set -euo pipefail
VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INVERT_RSE="${INVERT_RSE:-0}"

cd "$ROOT"
"$PYTHON" - <<'PY'
import os
import sys
import time

sys.path.insert(0, ".")

import serial
from serial.rs485 import RS485Settings

from brakovka_pi.config import RS485_RTS0_GPIO, load_runtime_config


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
invert = os.getenv("INVERT_RSE", "0") == "1"
active_high = False if invert else bool(sc.rs485_active_high)
before_s = float(sc.de_delay_before_tx_s)
after_s = float(sc.de_turnaround_s)
reg = int(vc.reg_status)

print(f"port={sc.port} baud={sc.baudrate} unit={sc.unit_id}")
print(f"read reg=0x{reg:04X} ({reg}) profile={vc.profile}")
print(
    f"DE=UART RTS0 HARDWARE GPIO{RS485_RTS0_GPIO} "
    f"active_high={active_high} (INVERT_RSE={invert})"
)

ser = serial.Serial(sc.port, sc.baudrate, bytesize=8, parity="N", stopbits=1, timeout=1.0)
ser.rtscts = False
try:
    ser.rs485_mode = RS485Settings(
        rts_level_for_tx=active_high,
        rts_level_for_rx=not active_high,
        loopback=False,
        delay_before_tx=before_s if before_s > 0 else None,
        delay_before_rx=after_s if after_s > 0 else None,
    )
    print("hardware rs485_mode ON (kernel toggles RTS0)")
except Exception as exc:
    print(f"FAIL: rs485_mode: {type(exc).__name__}: {exc}")
    print("  Check: gpio=17=a3 in /boot/firmware/config.txt, then reboot")
    ser.close()
    raise SystemExit(2)

try:
    ser.rts = not active_high
except Exception:
    pass
print(f"idle RTS={int(bool(ser.rts))} (expect RX={int(not active_high)})")

req = build_read_holding(int(sc.unit_id), reg, 1)
print(f"TX {req.hex(' ')}")

ser.reset_input_buffer()
ser.write(req)
ser.flush()
time.sleep(0.15)
print(f"after TX RTS={int(bool(ser.rts))} (expect RX={int(not active_high)})")

rx = ser.read(64)
print(f"RX ({len(rx)} bytes): {rx.hex(' ') if rx else '(empty)'}")
if not rx:
    print("Нет RX. Если RTS после TX = 1 — ядро не опустило DE (типичный баг PL011).")
    print("  Проверьте pinctrl get 17 → RTS0, A/B, GND")
    print("  INVERT_RSE=1 bash deploy/check_modbus_raw.sh")
elif check_crc(rx):
    print("OK: CRC valid")
else:
    print("CRC ERROR")

try:
    ser.rts = not active_high
except Exception:
    pass
print(f"final RTS={int(bool(ser.rts))}")
ser.close()
PY
