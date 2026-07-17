#!/usr/bin/env bash
# Raw Modbus RTU: USB auto-DE or GPIO software DE (settings.json).
set -euo pipefail
VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GPIOZERO_PIN_FACTORY="${GPIOZERO_PIN_FACTORY:-lgpio}"
INVERT_RSE="${INVERT_RSE:-0}"

cd "$ROOT"
"$PYTHON" - <<'PY'
import os
import sys
import time

sys.path.insert(0, ".")
os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

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
invert = os.getenv("INVERT_RSE", "0") == "1"
before_s = float(sc.de_delay_before_tx_s)
after_s = float(sc.de_turnaround_s)
reg = int(vc.reg_status)
de_pin = sc.rs485_de
use_gpio = de_pin is not None and int(de_pin) > 0

print(f"port={sc.port} baud={sc.baudrate} unit={sc.unit_id}")
print(f"read reg=0x{reg:04X} ({reg}) profile={vc.profile}")

de = None
if use_gpio:
    from gpiozero import DigitalOutputDevice
    from brakovka_pi.gpio_io import _configure_pin_factory

    active_high = False if invert else bool(sc.rs485_active_high)
    print(f"DE=GPIO{de_pin} software active_high={active_high} (INVERT_RSE={invert})")
    _configure_pin_factory(probe_pin=23)
    de = DigitalOutputDevice(int(de_pin), active_high=active_high, initial_value=False)
else:
    print("DE=USB adapter (auto, rs485_de=null)")

ser = serial.Serial(sc.port, sc.baudrate, bytesize=8, parity="N", stopbits=1, timeout=1.0)
ser.rtscts = False
try:
    ser.rs485_mode = None
except Exception:
    pass

if de is not None:
    de.off()
ser.reset_input_buffer()
print("idle RX")

req = build_read_holding(int(sc.unit_id), reg, 1)
print(f"TX {req.hex(' ')}")

ser.reset_input_buffer()
if de is not None:
    de.on()
    if before_s > 0:
        time.sleep(before_s)
ser.write(req)
ser.flush()
frame_s = len(req) * 10 / float(sc.baudrate)
if de is not None:
    time.sleep(frame_s + after_s)
    de.off()
    time.sleep(0.002)
    echo_n = ser.in_waiting
    if echo_n:
        echo = ser.read(min(echo_n, len(req)))
        print(f"echo discarded ({len(echo)}): {echo.hex(' ')}")
else:
    time.sleep(max(0.05, frame_s + 0.02))

print("after TX")
time.sleep(0.05)

rx = ser.read(64)
print(f"RX ({len(rx)} bytes): {rx.hex(' ') if rx else '(empty)'}")
if not rx:
    if use_gpio:
        print(f"Нет RX. A/B, GND, unit_id; pinctrl get {de_pin}; INVERT_RSE=1")
    else:
        print("Нет RX. Проверьте port, A/B, GND, unit_id, baud; ls /dev/ttyUSB*")
elif check_crc(rx):
    print("OK: CRC valid")
else:
    print("CRC ERROR")

if de is not None:
    de.off()
ser.close()
PY
