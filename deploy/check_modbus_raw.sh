#!/usr/bin/env bash
# Raw Modbus RTU request with manual RSE — diagnoses RX path vs pymodbus.
set -euo pipefail
VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GPIOZERO_PIN_FACTORY="${GPIOZERO_PIN_FACTORY:-lgpio}"
# Optional: INVERT_RSE=1 bash deploy/check_modbus_raw.sh
INVERT_RSE="${INVERT_RSE:-0}"

cd "$ROOT"
"$PYTHON" - <<'PY'
import os
import sys
import time

sys.path.insert(0, ".")
os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

import serial
from gpiozero import DigitalOutputDevice

from brakovka_pi.config import load_runtime_config
from brakovka_pi.gpio_io import _configure_pin_factory


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
active_high = False if invert else bool(getattr(sc, "rs485_active_high", True))
before_s = float(sc.de_delay_before_tx_s)
after_s = float(sc.de_turnaround_s)
reg = int(vc.reg_status)

print(f"port={sc.port} baud={sc.baudrate} unit={sc.unit_id}")
print(f"read reg=0x{reg:04X} ({reg}) profile={vc.profile}")
print(f"RSE=GPIO{sc.rs485_de} active_high={active_high} (INVERT_RSE={invert})")
print(f"DE delay before TX={before_s:.3f}s turnaround={after_s:.3f}s")

_configure_pin_factory(probe_pin=23)
rse = DigitalOutputDevice(sc.rs485_de, active_high=active_high, initial_value=False)
ser = serial.Serial(sc.port, sc.baudrate, bytesize=8, parity="N", stopbits=1, timeout=1.0)

req = build_read_holding(int(sc.unit_id), reg, 1)
print(f"TX {req.hex(' ')}")

ser.reset_input_buffer()
rse.on()
time.sleep(before_s)
ser.write(req)
ser.flush()
time.sleep(len(req) * 10 / float(sc.baudrate) + after_s)
rse.off()
print("RSE -> RX, waiting ...")
time.sleep(0.1)
rx = ser.read(64)
print(f"RX ({len(rx)} bytes): {rx.hex(' ') if rx else '(empty)'}")
if not rx:
    print("Нет RX от ПЧ. Проверьте:")
    print("  1) A/B (поменять местами), общий GND Pi <-> ПЧ")
    print("  2) RO -> GPIO15, DI -> GPIO14, DE -> GPIO16")
    print("  3) на шине только один мастер (отключить OPC/ПК-адаптер)")
    print("  4) INVERT_RSE=1 bash deploy/check_modbus_raw.sh")
    print("  5) увеличить de_turnaround_s в settings.json (например 0.015)")
else:
    print("OK: ответ от ПЧ получен")

rse.off()
ser.close()
PY
