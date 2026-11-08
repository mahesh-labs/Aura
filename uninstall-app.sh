#!/usr/bin/env bash
# Remove Aura (service, launcher, menu entry, app files). Your chats, settings and models are kept unless you pass --purge.
set -uo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/aura"
UNITDIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now aura.service 2>/dev/null || true
fi
[ -x "$HOME/.local/bin/aura" ] && "$HOME/.local/bin/aura" quit >/dev/null 2>&1 || true
rm -f "$UNITDIR/aura.service" "$HOME/.local/bin/aura" \
      "$HOME/.local/share/applications/aura.desktop" "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/aura.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/aura.svg"
command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload || true
rm -rf "$DATA/app"
if [ "${1:-}" = "--purge" ]; then
  rm -rf "$DATA" "${XDG_CONFIG_HOME:-$HOME/.config}/aura"
  echo "Removed everything, including chats, settings, models and the Python environment."
else
  echo "Removed the app. Kept: $DATA (chats, models, python environment) and ~/.config/aura (settings). Use --purge to delete those too."
fi
