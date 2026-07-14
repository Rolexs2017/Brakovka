#!/usr/bin/env bash
# Launch Brakovka with a specific venv (edit paths below).
set -euo pipefail

VENV_PATH="${VENV_PATH:-/home/rolexs/brk}"
SCRIPT_PATH="${SCRIPT_PATH:-/home/rolexs/rpi_python/run_brakovka.py}"
PYTHON="$VENV_PATH/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: venv python not found: $PYTHON" >&2
  echo "Create with: python3 -m venv --system-site-packages \"$VENV_PATH\"" >&2
  exit 1
fi

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "ERROR: script not found: $SCRIPT_PATH" >&2
  exit 1
fi

# Debian 13 (Trixie): pigpiod usually missing — use lgpio.
export GPIOZERO_PIN_FACTORY="${GPIOZERO_PIN_FACTORY:-lgpio}"
export QT_IM_MODULE="${QT_IM_MODULE:-none}"
export GTK_IM_MODULE="${GTK_IM_MODULE:-none}"
export XMODIFIERS="${XMODIFIERS:-@im=none}"

cd "$(dirname "$SCRIPT_PATH")"
exec "$PYTHON" "$SCRIPT_PATH" "$@"
