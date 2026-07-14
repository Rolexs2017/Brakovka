#!/usr/bin/env bash
# Install Brakovka desktop launcher for the current user.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
DESKTOP_DIR="$HOME/Desktop"

mkdir -p "$APP_DIR" "$ICON_DIR" "$DESKTOP_DIR"

ICON_SRC="$DEPLOY/icons/brakovka.png"
ICON_DST="$ICON_DIR/brakovka.png"
if [[ -f "$ICON_SRC" ]]; then
  cp -f "$ICON_SRC" "$ICON_DST"
else
  ICON_DST=""
fi

RUN_SH="$DEPLOY/run_brakovka.sh"
chmod +x "$RUN_SH" 2>/dev/null || true

DESKTOP_FILE="$APP_DIR/brakovka.desktop"
{
  echo "[Desktop Entry]"
  echo "Version=1.0"
  echo "Type=Application"
  echo "Name=Brakovka"
  echo "Name[ru]=Браковка"
  echo "Comment=Brakovka controller + HMI"
  echo "Comment[ru]=Контроллер и панель оператора Браковка"
  echo "Exec=$RUN_SH"
  echo "Path=$ROOT"
  if [[ -n "$ICON_DST" ]]; then
    echo "Icon=$ICON_DST"
  else
    echo "Icon=applications-engineering"
  fi
  echo "Terminal=false"
  echo "Categories=Industrial;Engineering;Utility;"
  echo "StartupNotify=true"
  echo "Keywords=brakovka;gpio;hmi;"
} > "$DESKTOP_FILE"
chmod +x "$DESKTOP_FILE"

cp -f "$DESKTOP_FILE" "$DESKTOP_DIR/brakovka.desktop"
chmod +x "$DESKTOP_DIR/brakovka.desktop"

# Mark as trusted on GNOME/Pi desktop if gio is available
if command -v gio >/dev/null 2>&1; then
  gio set "$DESKTOP_DIR/brakovka.desktop" metadata::trusted true 2>/dev/null || true
fi

echo "Installed:"
echo "  $DESKTOP_FILE"
echo "  $DESKTOP_DIR/brakovka.desktop"
[[ -n "$ICON_DST" ]] && echo "  $ICON_DST"
echo "If the desktop icon is greyed out: right-click → Allow Launching"
