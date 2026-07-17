#!/usr/bin/env bash
# Low-level UART TX test: GPIO14 + GPIO17 hardware RTS0 (RS485Settings).
set -euo pipefail

VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT"
echo "=== UART TX smoke test (RTS0 hardware DE) ==="
echo "Probe: GPIO14 (TX/DI), GPIO17 (RTS0/DE), GND"
echo "serial0 -> $(readlink -f /dev/serial0 2>/dev/null || echo missing)"
echo "Ctrl+C to stop"
echo

"$PYTHON" - <<'PY'
import sys, time
sys.path.insert(0, ".")

import serial
from serial.rs485 import RS485Settings
from brakovka_pi.config import RS485_RTS0_GPIO, load_runtime_config

_emu, gpio_cfg, serial_cfg, *_ = load_runtime_config()
port = serial_cfg.port
baud = serial_cfg.baudrate
active_high = bool(serial_cfg.rs485_active_high)
before = float(serial_cfg.de_delay_before_tx_s)
after = float(serial_cfg.de_turnaround_s)

print(f"port={port} baud={baud} DE=GPIO{RS485_RTS0_GPIO} hardware RTS0")
ser = serial.Serial(port=port, baudrate=baud, bytesize=8, parity="N", stopbits=1, timeout=0.2)
ser.rtscts = False
ser.rs485_mode = RS485Settings(
    rts_level_for_tx=active_high,
    rts_level_for_rx=not active_high,
    delay_before_tx=before if before > 0 else None,
    delay_before_rx=after if after > 0 else None,
)
ser.rts = not active_high
print(f"idle RTS={int(bool(ser.rts))}")

n = 0
try:
    while True:
        n += 1
        payload = bytes([0x55, 0xAA, n & 0xFF, 0x01, 0x03, 0x20, 0x00])
        ser.write(payload)
        ser.flush()
        time.sleep(0.05)
        print(f"[{n}] TX {payload.hex(' ')}  RTS after={int(bool(ser.rts))}")
        time.sleep(1.0)
except KeyboardInterrupt:
    print("\nstop")
finally:
    try:
        ser.rts = not active_high
    except Exception:
        pass
    print(f"final RTS={int(bool(ser.rts))}")
    ser.close()
PY
