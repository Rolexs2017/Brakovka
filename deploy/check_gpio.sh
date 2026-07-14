#!/usr/bin/env bash
# Diagnose GPIO / gpiozero / lgpio for the Brakovka venv.
set -euo pipefail

VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
PYTHON="${PYTHON:-$VENV_PATH/bin/python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Brakovka GPIO check ==="
echo "python: $PYTHON"
echo "root:   $ROOT"
echo "user:   $(id -un)  uid=$(id -u)  groups=$(id -Gn)"
echo "chips:  $(ls -l /dev/gpiochip* 2>/dev/null || echo 'NONE')"
echo

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: python not found: $PYTHON"
  exit 1
fi

export GPIOZERO_PIN_FACTORY="${GPIOZERO_PIN_FACTORY:-lgpio}"
cd "$ROOT"

"$PYTHON" - <<'PY'
import os, sys, traceback
print("executable:", sys.executable)
print("version:", sys.version.replace("\n", " "))
print("GPIOZERO_PIN_FACTORY=", os.getenv("GPIOZERO_PIN_FACTORY"))

def try_import(name):
    try:
        m = __import__(name)
        print(f"OK import {name}:", getattr(m, "__file__", m))
        return True
    except Exception as e:
        print(f"FAIL import {name}: {type(e).__name__}: {e}")
        return False

ok_gz = try_import("gpiozero")
ok_lg = try_import("lgpio")
try_import("RPi.GPIO")

if not ok_gz:
    print("\nFix: sudo apt install -y python3-gpiozero")
    print("     recreate venv: python3 -m venv --system-site-packages /home/rolexs/brk")
    sys.exit(2)

if not ok_lg:
    print("\nFix: sudo apt install -y python3-lgpio python3-rpi-lgpio")
    print("     venv MUST use --system-site-packages so lgpio is visible")
    sys.exit(3)

from gpiozero import Device, Button
from gpiozero.pins.lgpio import LGPIOFactory
from pathlib import Path

chips = []
for p in sorted(Path("/dev").glob("gpiochip*")):
    s = p.name.replace("gpiochip", "")
    if s.isdigit():
        chips.append(int(s))
if not chips:
    chips = [0, 4]

last = None
for chip in chips:
    try:
        print(f"try LGPIOFactory(chip={chip}) ...")
        Device.pin_factory = LGPIOFactory(chip=chip)
        b = Button(23, pull_up=True)
        print("OK Button(23) is_pressed=", b.is_pressed, "factory=", Device.pin_factory)
        b.close()
        print("SUCCESS chip", chip)
        break
    except Exception as e:
        last = e
        print(f"FAIL chip {chip}: {type(e).__name__}: {e}")
else:
    print("\nAll chips failed.")
    if last:
        traceback.print_exception(type(last), last, last.__traceback__)
    print("\nIf PermissionError: sudo usermod -aG gpio $USER && re-login")
    sys.exit(4)

print("\nAlso testing brakovka_pi.gpio_io.GpioInputs ...")
sys.path.insert(0, ".")
from brakovka_pi.gpio_io import GpioInputs
g = GpioInputs()
print("available=", g.available, "factory=", g.pin_factory)
print("error=", g.error or "(none)")
print("levels=", g.read_levels())
sys.exit(0 if g.available else 5)
PY
