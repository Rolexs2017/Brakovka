#!/usr/bin/env bash
# Low-level UART TX test: GPIO14 (TX) + GPIO17 (RTS0 / DE) for Waveshare SP3485.
# Watch with scope/LA: TX=GPIO14, DE=GPIO17. Expect bursts every second.
set -euo pipefail

VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GPIOZERO_PIN_FACTORY="${GPIOZERO_PIN_FACTORY:-lgpio}"

cd "$ROOT"
echo "=== UART TX smoke test (RTS0 DE) ==="
echo "Probe: GPIO14 (TX/DI), GPIO17 (RTS0/DE), GND"
echo "serial0 -> $(readlink -f /dev/serial0 2>/dev/null || echo missing)"
echo "Ctrl+C to stop"
echo

"$PYTHON" - <<'PY'
import os, sys, time
sys.path.insert(0, ".")
os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

import serial
from serial.rs485 import RS485Settings
from brakovka_pi.config import load_runtime_config

_emu, gpio_cfg, serial_cfg, *_ = load_runtime_config()
port = serial_cfg.port
baud = serial_cfg.baudrate
active_high = bool(serial_cfg.rs485_active_high)
before = float(serial_cfg.de_delay_before_tx_s)
after = float(serial_cfg.de_turnaround_s)

print(f"port={port} baud={baud} DE=GPIO{serial_cfg.rs485_de} (uart_rts)")
ser = serial.Serial(port=port, baudrate=baud, bytesize=8, parity="N", stopbits=1, timeout=0.2)
ser.rtscts = False
ser.rs485_mode = RS485Settings(
    rts_level_for_tx=active_high,
    rts_level_for_rx=not active_high,
    delay_before_tx=before if before > 0 else None,
    delay_before_rx=after if after > 0 else None,
)
print("serial + RS485 RTS0 OK, sending 0x55 pattern ...")

n = 0
try:
    while True:
        n += 1
        payload = bytes([0x55, 0xAA, n & 0xFF, 0x01, 0x03, 0x20, 0x00])
        ser.write(payload)
        ser.flush()
        print(f"[{n}] TX {payload.hex(' ')}  (RTS0 pulsed by driver)")
        time.sleep(1.0)
except KeyboardInterrupt:
    print("\nstop")
finally:
    ser.close()
PY
