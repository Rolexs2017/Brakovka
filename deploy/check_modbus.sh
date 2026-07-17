#!/usr/bin/env bash
# Check RS485 Modbus RTU link to the VFD (uses settings.json).
set -euo pipefail

VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Brakovka Modbus check ==="
echo "python: $PYTHON"
echo "root:   $ROOT"
echo "user:   $(id -un)  groups=$(id -Gn)"
echo "serial devices:"
ls -l /dev/serial0 /dev/ttyAMA0 /dev/ttyS0 2>/dev/null || true
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

# Avoid stale .pyc from an older modbus_rs485.py
import brakovka_pi.modbus_rs485 as modbus_mod
print("modbus module file:", getattr(modbus_mod, "__file__", "?"))
print("DE_CONTROL_VERSION:", getattr(modbus_mod, "DE_CONTROL_VERSION", "OLD FILE — update modbus_rs485.py"))
if not hasattr(modbus_mod, "DE_CONTROL_VERSION"):
    print("ERROR: на Pi старый modbus_rs485.py (нет DE_CONTROL_VERSION). Скопируйте файл с ПК.")
    sys.exit(5)

from brakovka_pi.config import RS485_RTS0_GPIO, load_runtime_config
from brakovka_pi.modbus_rs485 import Rs485Vfd, VfdCommand

emu, gpio_cfg, serial_cfg, vfd_cfg, *_rest = load_runtime_config()

print("settings emulator flag:", emu)
print(
    f"serial: port={serial_cfg.port} baud={serial_cfg.baudrate} "
    f"parity={serial_cfg.parity} stop={serial_cfg.stopbits} "
    f"unit_id={serial_cfg.unit_id} DE=UART RTS0 soft GPIO{RS485_RTS0_GPIO} "
    f"active_high={serial_cfg.rs485_active_high}"
)
print(
    f"vfd regs (fixed CP2000): profile={vfd_cfg.profile} cmd={vfd_cfg.reg_cmd} "
    f"freq={vfd_cfg.reg_freq} status={vfd_cfg.reg_status} fault={vfd_cfg.reg_fault} "
    f"freq_out={vfd_cfg.reg_freq_out} scale={vfd_cfg.freq_scale}"
)

port = Path(serial_cfg.port)
if port.is_symlink():
    target = port.resolve()
    print(f"port symlink: {port} -> {target}")
    if target.name == "ttyS0":
        print(
            "WARNING: serial0 is mini-UART (ttyS0). For stable 115200 Modbus on GPIO14/15 "
            "prefer PL011 (ttyAMA0):\n"
            "  sudo raspi-config → Interface Options → Serial → login No, port Yes\n"
            "  In /boot/firmware/config.txt (or /boot/config.txt):\n"
            "    enable_uart=1\n"
            "    dtparam=uart0=on\n"
            "    dtoverlay=disable-bt\n"
            "    gpio=17=a3\n"
            "  Then: sudo reboot\n"
            "  Expect: /dev/serial0 -> ttyAMA0"
        )

if not port.exists():
    print(f"FAIL: port not found: {serial_cfg.port}")
    sys.exit(2)

async def main() -> int:
    vfd = Rs485Vfd(serial_cfg, vfd_cfg)
    de_ok = getattr(vfd, "de_ok", None)
    de_err = getattr(vfd, "de_error", "")
    if de_ok is None:
        print(
            "ERROR: Rs485Vfd has no de_ok — на Pi старый brakovka_pi/modbus_rs485.py.\n"
            "Скопируйте обновлённый файл с ПК и удалите кэш:\n"
            "  rm -f brakovka_pi/__pycache__/modbus_rs485*.pyc"
        )
        return 5

    print(f"\nDE: UART RTS0 soft GPIO{RS485_RTS0_GPIO} ok={de_ok} error={de_err or '(none)'}")
    if not de_ok:
        print("CRITICAL: RTS control not ready.")
        print("  Ensure gpio=17=a3 in config.txt and DE wired to GPIO17.")

    print("\n1) connect ...")
    await vfd.connect()
    if not vfd._connected:
        print("FAIL: Modbus connect() did not open the port")
        return 3
    print("OK: port open")
    print(f"DE soft RTS ready: {getattr(vfd, 'de_patched', False)}")
    if not getattr(vfd, "de_patched", False):
        print("WARN: RTS control failed — RX likely broken")
        print("  Check: gpio=17=a3, DE on GPIO17, pinctrl get 17 → RTS0")
    # Idle must be RX (RTS=0 when active_high TX).
    ser = vfd._get_pyserial()
    if ser is not None:
        print(f"idle RTS={int(bool(ser.rts))} (expect 0 if active_high TX)")

    print("\n2) read status/fault holding registers ...")
    st = await vfd.read_status()
    if not st:
        print("FAIL: no response from slave")
        print("Checklist: swap A/B, GND, VFD baud/addr/RTU, RTS idle=RX, not ttyS0")
        if ser is not None:
            print(f"RTS after fail={int(bool(ser.rts))}")
        await vfd.close()
        return 4

    print(
        f"OK: status_word=0x{st['status_word']:04X} "
        f"error_code={st['error_code']} fault={st['fault']} warning={st['warning']}"
    )

    print("\n3) write STOP + freq=0 (safe) ...")
    await vfd.write_command(VfdCommand(run=False, reverse=False, speed_setpoint_hz=0.0))
    await asyncio.sleep(0.2)
    st2 = await vfd.read_status()
    print("after STOP:", st2 or "no response")

    await vfd.close()
    if ser is not None:
        try:
            print(f"final RTS after close attempt (port closed)")
        except Exception:
            pass
    print("\nSUCCESS: Modbus RTU path looks alive")
    return 0

raise SystemExit(asyncio.run(main()))
PY
