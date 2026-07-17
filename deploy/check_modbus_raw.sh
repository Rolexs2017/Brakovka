#!/usr/bin/env bash
# Raw Modbus RTU with soft UART RTS0 (GPIO17) — diagnoses RX / CRC / echo.
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


def check_crc(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    got = frame[-2] | (frame[-1] << 8)
    return modbus_crc(frame[:-2]) == got


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
ser.reset_input_buffer()
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
# Discard possible TX echo (main CRC cause on half-duplex)
time.sleep(0.002)
echo_n = ser.in_waiting
if echo_n:
    echo = ser.read(echo_n)
    print(f"echo/garbage discarded ({len(echo)}): {echo.hex(' ')}")
    if echo == req:
        print("NOTE: full TX echo on RX — RE may be always on; discard is required")
print(f"after TX RTS={int(ser.rts)} (must be RX={int(rx_level)})")
time.sleep(0.05)

rx = ser.read(64)
print(f"RX ({len(rx)} bytes): {rx.hex(' ') if rx else '(empty)'}")
if not rx:
    print("Нет RX. Проверьте DE/RTS0, A/B, GND, baud/addr")
elif check_crc(rx):
    print("OK: CRC valid")
    if len(rx) >= 5 and rx[1] == 0x03:
        print(f"  data={rx[3:-2].hex(' ')}")
else:
    print("CRC ERROR on received frame")
    if rx.startswith(req[:1]) or req[:4] in rx:
        print("  Looks like TX mixed with RX — increase de_turnaround_s or check echo")
    print("  Try: INVERT_RSE=1  or  larger de_turnaround_s in settings.json")

ser.rts = rx_level
print(f"final RTS={int(ser.rts)}")
ser.close()
PY
