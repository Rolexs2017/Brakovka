#!/usr/bin/env bash
# List serial ports useful for Modbus (USB RS485, onboard UART).
set -euo pipefail

echo "=== USB / ACM ==="
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "(none)"

echo
echo "=== by-id (stable path for settings.json) ==="
ls -l /dev/serial/by-id/ 2>/dev/null || echo "(none — install adapter or check udev)"

echo
echo "=== onboard UART ==="
ls -l /dev/serial0 /dev/ttyAMA0 2>/dev/null || true
if [[ -L /dev/serial0 ]]; then
  echo "serial0 -> $(readlink -f /dev/serial0)"
fi

echo
echo "Tip: use by-id in settings.json, e.g.:"
echo '  "port": "/dev/serial/by-id/usb-XXXX-if00-port0"'
echo '  "rs485_de": null'
