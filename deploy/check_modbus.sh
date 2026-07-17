#!/usr/bin/env bash
# Check RS485 Modbus RTU link to the VFD (uses settings.json).
set -euo pipefail

VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GPIOZERO_PIN_FACTORY="${GPIOZERO_PIN_FACTORY:-lgpio}"

echo "=== Brakovka Modbus check ==="
echo "python: $PYTHON"
echo "root:   $ROOT"
echo "user:   $(id -un)  groups=$(id -Gn)"
echo "serial devices:"
ls -l /dev/ttyUSB* /dev/ttyACM* /dev/serial/by-id/* 2>/dev/null | head -20 || true
ls -l /dev/serial0 /dev/ttyAMA0 2>/dev/null || true
if [[ -L /dev/serial0 ]]; then
  echo "serial0 -> $(readlink -f /dev/serial0)"
fi
echo

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: python not found: $PYTHON"
  exit 1
fi

cd "$ROOT"
"$PYTHON" - <<'PY'
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")
os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

import brakovka_pi.modbus_rs485 as modbus_mod
print("modbus module file:", getattr(modbus_mod, "__file__", "?"))
print("DE_CONTROL_VERSION:", getattr(modbus_mod, "DE_CONTROL_VERSION", "OLD FILE"))
if not hasattr(modbus_mod, "DE_CONTROL_VERSION"):
    print("ERROR: старый modbus_rs485.py на Pi")
    sys.exit(5)

from brakovka_pi.config import load_runtime_config
from brakovka_pi.modbus_rs485 import Rs485Vfd, VfdCommand

emu, gpio_cfg, serial_cfg, vfd_cfg, *_rest = load_runtime_config()
use_gpio = serial_cfg.rs485_de is not None
de_label = f"GPIO{serial_cfg.rs485_de} software" if use_gpio else "USB/auto (rs485_de=null)"

print("settings emulator flag:", emu)
print(
    f"serial: port={serial_cfg.port} baud={serial_cfg.baudrate} "
    f"unit_id={serial_cfg.unit_id} DE={de_label}"
)
print(
    f"vfd regs (fixed CP2000): profile={vfd_cfg.profile} status={vfd_cfg.reg_status} "
    f"fault={vfd_cfg.reg_fault}"
)

port = Path(serial_cfg.port)
if not port.exists():
    print(f"FAIL: port not found: {serial_cfg.port}")
    print("Run: bash deploy/list_serial_ports.sh")
    sys.exit(2)

async def main() -> int:
    vfd = Rs485Vfd(serial_cfg, vfd_cfg)
    print(f"\nDE ok={vfd.de_ok} error={vfd.de_error or '(none)'}")
    if use_gpio and not vfd.de_ok:
        print("CRITICAL: GPIO DE not ready — pkill -f run_brakovka")

    print("\n1) connect ...")
    await vfd.connect()
    if not vfd._connected:
        print("FAIL: Modbus connect() did not open the port")
        return 3
    print("OK: port open")

    print("\n2) read status ...")
    st = await vfd.read_status()
    if not st:
        print("FAIL: no response from slave")
        print("Checklist: port, A/B, GND, baud, unit_id; one master on bus")
        await vfd.close()
        return 4

    print(
        f"OK: status_word=0x{st['status_word']:04X} "
        f"error_code={st['error_code']} fault={st['fault']}"
    )

    print("\n3) write STOP + freq=0 (safe) ...")
    await vfd.write_command(VfdCommand(run=False, reverse=False, speed_setpoint_hz=0.0))
    await asyncio.sleep(0.2)
    print("after STOP:", await vfd.read_status() or "no response")

    await vfd.close()
    print("\nSUCCESS: Modbus RTU path looks alive")
    return 0

raise SystemExit(asyncio.run(main()))
PY
