#!/usr/bin/env bash
# Raw Modbus RTU request with manual RSE — diagnoses RX path vs pymodbus.
# PC emulator should show the request; this script prints any RX bytes.
set -euo pipefail
VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GPIOZERO_PIN_FACTORY="${GPIOZERO_PIN_FACTORY:-lgpio}"
# Optional: INVERT_RSE=1 bash deploy/check_modbus_raw.sh
INVERT_RSE="${INVERT_RSE:-0}"

cd "$ROOT"
"$PYTHON" - <<PY
import os, sys, time
sys.path.insert(0, ".")
os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

import serial
from gpiozero import DigitalOutputDevice
from brakovka_pi.config import load_runtime_config
from brakovka_pi.gpio_io import _configure_pin_factory

_, _, sc, vc, *_ = load_runtime_config()
invert = os.getenv("INVERT_RSE", "0") == "1"
active_high = (not invert) if invert else bool(getattr(sc, "rs485_active_high", True))
# If INVERT_RSE=1 force opposite of normal True
if invert:
    active_high = False

print(f"port={sc.port} baud={sc.baudrate} unit={sc.unit_id}")
print(f"RSE=GPIO{sc.rs485_de} active_high={active_high} (INVERT_RSE={invert})")
print("Щуп: RSE должен уйти в RX (низкий для active_high=True) ДО ответа эмулятора")

_configure_pin_factory(probe_pin=23)
rse = DigitalOutputDevice(sc.rs485_de, active_high=active_high, initial_value=False)
ser = serial.Serial(sc.port, sc.baudrate, bytesize=8, parity="N", stopbits=1, timeout=1.0)

# Modbus RTU: read holding reg 0x2002 count 1, unit 1 — same as check_modbus
# CRC already in known good frame from logs:
req = bytes.fromhex("01 03 20 02 00 01 2e 0a")
print(f"TX {req.hex(' ')}")

ser.reset_input_buffer()
rse.on()   # TX
time.sleep(0.002)
ser.write(req)
ser.flush()
time.sleep(len(req) * 10 / sc.baudrate + 0.005)
rse.off()  # RX — must be LOW before PC replies
print("RSE -> RX, waiting 1.0s ...")
time.sleep(0.05)
rx = ser.read(64)
print(f"RX ({len(rx)} bytes): {rx.hex(' ') if rx else '(empty)'}")
if not rx:
    print("Нет RX на Pi при том что ПК отвечает:")
    print("  1) щуп на RO — есть ли импульсы ответа?")
    print("  2) RO -> pin10 (GPIO15)?")
    print("  3) попробуйте: INVERT_RSE=1 bash deploy/check_modbus_raw.sh")
    print("  4) на осциллографе: RSE уже LOW, когда ПК шлёт ответ?")
rse.off()
ser.close()
PY
