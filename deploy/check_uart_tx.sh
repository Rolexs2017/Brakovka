#!/usr/bin/env bash
# Low-level UART TX + software GPIO DE test.
set -euo pipefail

VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GPIOZERO_PIN_FACTORY="${GPIOZERO_PIN_FACTORY:-lgpio}"

cd "$ROOT"
echo "=== UART TX + GPIO DE smoke test ==="
echo "Probe: GPIO14 (TX), GPIO15 (RX), GPIO17 (DE), GND"
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
active_high = bool(serial_cfg.rs485_active_high)
before = float(serial_cfg.de_delay_before_tx_s)
after = float(serial_cfg.de_turnaround_s)

print(f"port={port} baud={baud} DE=GPIO{de_pin} software")
_configure_pin_factory(probe_pin=23)
de = DigitalOutputDevice(de_pin, active_high=active_high, initial_value=False)
ser = serial.Serial(port=port, baudrate=baud, bytesize=8, parity="N", stopbits=1, timeout=0.2)
try:
    ser.rs485_mode = None
except Exception:
    pass
de.off()
print("DE opened OK")

n = 0
try:
    while True:
        n += 1
        payload = bytes([0x55, 0xAA, n & 0xFF, 0x01, 0x03, 0x20, 0x00])
        de.on()
        time.sleep(before)
        ser.write(payload)
        ser.flush()
        time.sleep(len(payload) * 10 / baud + after)
        de.off()
        print(f"[{n}] TX {payload.hex(' ')}  (DE pulsed)")
        time.sleep(1.0)
except KeyboardInterrupt:
    print("\nstop")
finally:
    de.off()
    ser.close()
PY
