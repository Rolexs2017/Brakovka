#!/usr/bin/env bash
# Raw Modbus RTU with soft UART RTS0 (GPIO17) — diagnoses RX path.
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
tx_level = active_high
rx_level = not active_high
before_s = float(sc.de_delay_before_tx_s)
after_s = float(sc.de_turnaround_s)
reg = int(vc.reg_status)

print(f"port={sc.port} baud={sc.baudrate} unit={sc.unit_id}")
print(f"read reg=0x{reg:04X} ({reg}) profile={vc.profile}")
print(
    f"DE=UART RTS0 soft GPIO{RS485_RTS0_GPIO} "
    f"tx={int(tx_level)} rx={int(rx_level)} (INVERT_RSE={invert})"
)

ser = serial.Serial(sc.port, sc.baudrate, bytesize=8, parity="N", stopbits=1, timeout=1.0)
ser.rtscts = False
try:
    ser.rs485_mode = None
except Exception:
    pass

ser.rts = rx_level
print(f"idle RTS={int(ser.rts)} (expect RX={int(rx_level)})")

req = build_read_holding(int(sc.unit_id), reg, 1)
print(f"TX {req.hex(' ')}")

ser.reset_input_buffer()
ser.rts = tx_level
time.sleep(before_s)
ser.write(req)
ser.flush()
time.sleep(len(req) * 10 / float(sc.baudrate) + after_s)
ser.rts = rx_level
print(f"after TX RTS={int(ser.rts)} (must be RX={int(rx_level)})")
time.sleep(0.05)

rx = ser.read(64)
print(f"RX ({len(rx)} bytes): {rx.hex(' ') if rx else '(empty)'}")
if not rx:
    print("Нет RX. Проверьте:")
    print(f"  1) DE -> GPIO{RS485_RTS0_GPIO}, pinctrl get 17 → RTS0")
    print("  2) после TX RTS должен быть 0 (если active_high TX)")
    print("  3) INVERT_RSE=1 bash deploy/check_modbus_raw.sh")
    print("  4) A/B, GND, один мастер")
else:
    print("OK: ответ от ПЧ получен")

ser.rts = rx_level
print(f"final RTS={int(ser.rts)}")
ser.close()
PY
