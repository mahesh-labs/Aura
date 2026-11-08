#!/usr/bin/env bash
# Install Aura as a standalone desktop app that starts at login and waits in the background for your commands.
#
#   ./install-app.sh            install / update (run it again from a newer folder to update)
#   ./install-app.sh --wake     also turn on the "hey aura" wake word
#   ./install-app.sh --no-deps  skip pacman / pip (only copy files and set up the service)
#
# After this you can delete the folder you unzipped: the app lives in ~/.local/share/aura/app.
set -euo pipefail
WAKE=0; DEPS=1
for a in "$@"; do case "$a" in --wake) WAKE=1;; --no-deps) DEPS=0;; -h|--help) sed -n 2,9p "$0"; exit 0;; *) echo "unknown option $a"; exit 1;; esac; done

HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/aura"
APP="$DATA/app"
VENV="$DATA/venv"
BIN="$HOME/.local/bin"
UNITDIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$APP" "$BIN" "$UNITDIR" "$DATA/models"

echo "==> stopping a running Aura (if any)"
if command -v systemctl >/dev/null 2>&1; then systemctl --user stop aura.service 2>/dev/null || true; fi
[ -x "$BIN/aura" ] && "$BIN/aura" quit >/dev/null 2>&1 || true

if [ "$HERE" != "$APP" ]; then
echo "==> copying the app to $APP"
rm -rf "$APP/aura"
mkdir -p "$APP"
tar -C "$HERE" --exclude='__pycache__' --exclude='tests' --exclude='*.pyc' -cf - aura install.sh install-app.sh uninstall-app.sh \
    requirements-part1.txt requirements-part2.txt requirements-part3.txt README.md 2>/dev/null | tar -C "$APP" -xf -
fi

if [ "$DEPS" = 1 ]; then
  echo "==> system and python packages (this can take a while the first time)"
  bash "$APP/install.sh" 3
fi

echo "==> launcher"
cat > "$BIN/aura" <<LAUNCH
#!/usr/bin/env bash
export PYTHONPATH="$APP\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$VENV/bin/python" -m aura "\$@"
LAUNCH
chmod +x "$BIN/aura"

echo "==> app menu entry, icon and login autostart"
PYTHONPATH="$APP" "$VENV/bin/python" -c "from aura.cli import main; main(['setup'])" >/dev/null 2>&1 || echo "   (could not write the menu entry; run: aura setup)"

echo "==> background service (starts at login, restarts itself if it crashes)"
cat > "$UNITDIR/aura.service" <<UNIT
[Unit]
Description=Aura local voice and text assistant
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=$BIN/aura --background
Restart=on-failure
RestartSec=4
# a crash loop should not hammer the GPU / mic: give up after 5 tries in a minute
StartLimitIntervalSec=60
StartLimitBurst=5

[Install]
WantedBy=graphical-session.target
UNIT

if [ "$WAKE" = 1 ]; then
  PYTHONPATH="$APP" "$VENV/bin/python" -c "from aura.config import Config; Config().set('wake_enabled', True)" && echo "==> wake word enabled"
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload
  systemctl --user enable aura.service >/dev/null 2>&1 || true
  if systemctl --user start aura.service 2>/dev/null; then
    sleep 2
    systemctl --user is-active --quiet aura.service && echo "==> Aura is running in the background (look for the tray icon)" \
      || echo "!! the service did not stay up: journalctl --user -u aura -n 40"
  else
    echo "   (service could not start right now, e.g. no desktop session; it will start at your next login)"
  fi
fi

cat <<DONE

Aura is installed.
  Start at login:   automatic (systemd user service + KDE autostart)
  Open the app:     'Aura' in the app menu, or  aura show
  Voice / quick chat from a keyboard shortcut:  aura voice   /   aura chat   (or hold the Meta key)
  Status and logs:  systemctl --user status aura      journalctl --user -u aura -f      ~/.local/share/aura/aura.log
  Check the setup:  aura doctor
  Update:           unzip the newer aura.zip and run ./install-app.sh again
  Uninstall:        $APP/uninstall-app.sh   (keeps your chats and settings)
First time only: log out and back in so the Meta-key and mouse-control permissions apply.
DONE
