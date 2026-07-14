#!/usr/bin/env bash
# Low-level UART TX test (GPIO14) + RSE (GPIO16) for Waveshare SP3485.
# Watch with scope/LA: TX=GPIO14, RSE=GPIO16. Expect bursts every second.
set -euo pipefail

VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GPIOZERO_PIN_FACTORY="${GPIOZERO_PIN_FACTORY:-lgpio}"

cd "$ROOT"
echo "=== UART TX smoke test ==="
echo "Probe: GPIO14 (TX/DI), GPIO16 (RSE), GND"
echo "serial0 -> $(readlink -f /dev/serial0 2>/dev/null || echo missing)"
echo "Ctrl+C to stop"
echo

"$PYTHON" - <<'PY'
import os, sys, time
sys.path.insert(0, ".")
os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

import serial
from gpiozero import DigitalOutputDevice
from brakovka_pi.config import load_runtime_config
from brakovka_pi.gpio_io import _configure_pin_factory

_emu, gpio_cfg, serial_cfg, *_ = load_runtime_config()
port = serial_cfg.port
baud = serial_cfg.baudrate
de_pin = int(serial_cfg.rs485_de)

print(f"port={port} baud={baud} RSE=GPIO{de_pin}")
_configure_pin_factory(probe_pin=23)

rse = DigitalOutputDevice(de_pin, active_high=True, initial_value=False)
print("RSE opened OK")

ser = serial.Serial(port=port, baudrate=baud, bytesize=8, parity="N", stopbits=1, timeout=0.2)
print("serial opened OK, sending 0x55 pattern ...")

n = 0
try:
    while True:
        n += 1
        payload = bytes([0x55, 0xAA, n & 0xFF, 0x01, 0x03, 0x20, 0x02])
        rse.on()  # TX
        time.sleep(0.002)
        ser.write(payload)
        ser.flush()
        # 8N1: 10 bit/byte
        time.sleep(len(payload) * 10 / baud + 0.003)
        rse.off()  # RX
        print(f"[{n}] TX {payload.hex(' ')}  (RSE pulsed)")
        time.sleep(1.0)
except KeyboardInterrupt:
    print("\nstop")
finally:
    rse.off()
    ser.close()
PY
