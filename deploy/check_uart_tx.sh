#!/usr/bin/env bash
# Low-level UART TX test: GPIO14 (TX) + GPIO17 (RTS0 soft DE).
set -euo pipefail

VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT"
echo "=== UART TX smoke test (RTS0 soft DE) ==="
echo "Probe: GPIO14 (TX/DI), GPIO17 (RTS0/DE), GND"
echo "serial0 -> $(readlink -f /dev/serial0 2>/dev/null || echo missing)"
echo "Ctrl+C to stop"
echo

"$PYTHON" - <<'PY'
import sys, time
sys.path.insert(0, ".")

import serial
from brakovka_pi.config import RS485_RTS0_GPIO, load_runtime_config

_emu, gpio_cfg, serial_cfg, *_ = load_runtime_config()
port = serial_cfg.port
baud = serial_cfg.baudrate
tx = bool(serial_cfg.rs485_active_high)
rx = not tx
before = float(serial_cfg.de_delay_before_tx_s)
after = float(serial_cfg.de_turnaround_s)

print(f"port={port} baud={baud} DE=GPIO{RS485_RTS0_GPIO} soft RTS0 tx={int(tx)} rx={int(rx)}")
ser = serial.Serial(port=port, baudrate=baud, bytesize=8, parity="N", stopbits=1, timeout=0.2)
ser.rtscts = False
try:
    ser.rs485_mode = None
except Exception:
    pass
ser.rts = rx
print(f"idle RTS={int(ser.rts)}")

n = 0
try:
    while True:
        n += 1
        payload = bytes([0x55, 0xAA, n & 0xFF, 0x01, 0x03, 0x20, 0x00])
        ser.rts = tx
        time.sleep(before)
        ser.write(payload)
        ser.flush()
        time.sleep(len(payload) * 10 / baud + after)
        ser.rts = rx
        print(f"[{n}] TX {payload.hex(' ')}  RTS after={int(ser.rts)} (expect {int(rx)})")
        time.sleep(1.0)
except KeyboardInterrupt:
    print("\nstop")
finally:
    ser.rts = rx
    print(f"final RTS={int(ser.rts)}")
    ser.close()
PY
