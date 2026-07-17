#!/usr/bin/env bash
# Raw Modbus RTU with UART RTS0 (GPIO17) or GPIO DE — diagnoses RX path.
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
from serial.rs485 import RS485Settings

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
de_mode = str(getattr(sc, "de_mode", "uart_rts") or "uart_rts").lower()
use_rts = de_mode in ("uart_rts", "rts", "rts0")

print(f"port={sc.port} baud={sc.baudrate} unit={sc.unit_id}")
print(f"read reg=0x{reg:04X} ({reg}) profile={vc.profile}")
print(f"de_mode={de_mode} DE=GPIO{sc.rs485_de} active_high={active_high} (INVERT_RSE={invert})")
print(f"DE delay before TX={before_s:.3f}s turnaround={after_s:.3f}s")

ser = serial.Serial(sc.port, sc.baudrate, bytesize=8, parity="N", stopbits=1, timeout=1.0)
ser.rtscts = False

gpio_de = None
if use_rts:
    try:
        ser.rs485_mode = RS485Settings(
            rts_level_for_tx=active_high,
            rts_level_for_rx=not active_high,
            loopback=False,
            delay_before_tx=before_s if before_s > 0 else None,
            delay_before_rx=after_s if after_s > 0 else None,
        )
        print("UART RTS0 RS485 mode ON (GPIO17 must be ALT3 RTS0)")
    except Exception as exc:
        print(f"FAIL: rs485_mode: {type(exc).__name__}: {exc}")
        print("  Check: gpio=17=a3 in /boot/firmware/config.txt, then reboot")
        ser.close()
        raise SystemExit(2)
else:
    from gpiozero import DigitalOutputDevice

    _configure_pin_factory(probe_pin=23)
    gpio_de = DigitalOutputDevice(sc.rs485_de, active_high=active_high, initial_value=False)
    print(f"GPIO DE mode on pin {sc.rs485_de}")

req = build_read_holding(int(sc.unit_id), reg, 1)
print(f"TX {req.hex(' ')}")

ser.reset_input_buffer()
if gpio_de is not None:
    gpio_de.on()
    time.sleep(before_s)
ser.write(req)
ser.flush()
if gpio_de is not None:
    time.sleep(len(req) * 10 / float(sc.baudrate) + after_s)
    gpio_de.off()
    print("RSE -> RX, waiting ...")
else:
    # Kernel/pyserial releases RTS after TX; give slave time to answer.
    time.sleep(0.1)
    print("RTS auto RX, waiting ...")

rx = ser.read(64)
print(f"RX ({len(rx)} bytes): {rx.hex(' ') if rx else '(empty)'}")
if not rx:
    print("Нет RX от ПЧ. Проверьте:")
    print("  1) DE/RE -> GPIO17 (RTS0), не GPIO16")
    print("  2) pinctrl get 17  →  func=RTS0")
    print("  3) A/B, GND Pi <-> ПЧ, один мастер на шине")
    print("  4) INVERT_RSE=1 bash deploy/check_modbus_raw.sh")
    print("  5) config.txt: gpio=17=a3 + enable_uart=1 + dtoverlay=disable-bt")
else:
    print("OK: ответ от ПЧ получен")

if gpio_de is not None:
    gpio_de.off()
ser.close()
PY
