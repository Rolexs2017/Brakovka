#!/usr/bin/env bash
# List USB serial ports useful for Modbus RS485.
set -euo pipefail

echo "=== USB / ACM ==="
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "(none)"

echo
echo "=== by-id (stable path for settings.json) ==="
ls -l /dev/serial/by-id/ 2>/dev/null || echo "(none — install adapter or check udev)"

echo
echo "Tip: use by-id in settings.json, e.g.:"
echo '  "port": "/dev/serial/by-id/usb-XXXX-if00-port0"'
