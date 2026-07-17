#!/usr/bin/env bash
# Raw Modbus RTU with UART RTS0 (GPIO17) — diagnoses RX path.
set -euo pipefail
VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Optional: INVERT_RSE=1 bash deploy/check_modbus_raw.sh
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


_, _, sc, vc, *_ = load_runtime_config()
invert = os.getenv("INVERT_RSE", "0") == "1"
active_high = False if invert else bool(sc.rs485_active_high)
before_s = float(sc.de_delay_before_tx_s)
after_s = float(sc.de_turnaround_s)
reg = int(vc.reg_status)

print(f"port={sc.port} baud={sc.baudrate} unit={sc.unit_id}")
print(f"read reg=0x{reg:04X} ({reg}) profile={vc.profile}")
print(
    f"DE=UART RTS0 GPIO{RS485_RTS0_GPIO} active_high={active_high} "
    f"(INVERT_RSE={invert})"
)
print(f"DE delay before TX={before_s:.3f}s turnaround={after_s:.3f}s")

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
    print("UART RTS0 RS485 mode ON")
except Exception as exc:
    print(f"FAIL: rs485_mode: {type(exc).__name__}: {exc}")
    print("  Check: gpio=17=a3 in /boot/firmware/config.txt, then reboot")
    ser.close()
    raise SystemExit(2)

req = build_read_holding(int(sc.unit_id), reg, 1)
print(f"TX {req.hex(' ')}")

ser.reset_input_buffer()
ser.write(req)
ser.flush()
time.sleep(0.1)
print("RTS auto RX, waiting ...")

rx = ser.read(64)
print(f"RX ({len(rx)} bytes): {rx.hex(' ') if rx else '(empty)'}")
if not rx:
    print("Нет RX от ПЧ. Проверьте:")
    print(f"  1) DE/RE -> GPIO{RS485_RTS0_GPIO} (RTS0)")
    print("  2) pinctrl get 17  →  func=RTS0")
    print("  3) A/B, GND Pi <-> ПЧ, один мастер на шине")
    print("  4) INVERT_RSE=1 bash deploy/check_modbus_raw.sh")
    print("  5) config.txt: gpio=17=a3 + enable_uart=1 + dtoverlay=disable-bt")
else:
    print("OK: ответ от ПЧ получен")

ser.close()
PY
