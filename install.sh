#!/usr/bin/env bash
# Usage: ./install.sh 1|2|3     (each part includes the previous ones)
# Keep this folder where it is after installing (e.g. ~/aura): the launchers point into it.
set -euo pipefail
PART="${1:-}"; [[ "$PART" =~ ^[123]$ ]] || { echo "usage: $0 1|2|3"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/aura"
VENV="$DATA/venv"
mkdir -p "$DATA/models" "$HOME/.local/bin"

echo "==> system packages (pacman)"
PKGS=(python uv)
[ "$PART" -ge 2 ] && PKGS+=(portaudio pipewire-alsa pipewire-pulse libpulse alsa-utils espeak-ng playerctl wl-clipboard libnotify)
[ "$PART" -ge 3 ] && PKGS+=(spectacle tesseract tesseract-data-eng)
sudo pacman -S --needed --noconfirm "${PKGS[@]}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "==> creating venv (Python 3.12 via uv, avoids wheel gaps on very new Pythons)"
  uv venv --python 3.12 "$VENV"
fi
echo "==> python packages for part $PART"
uv pip install --python "$VENV/bin/python" -r "$HERE/requirements-part$PART.txt"

if [ "$PART" -ge 2 ]; then
  echo "==> Kokoro voice model (~340 MB)"
  base=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
  for f in kokoro-v1.0.onnx voices-v1.0.bin; do
    [ -s "$DATA/models/$f" ] || curl -L --fail -o "$DATA/models/$f" "$base/$f" || echo "!! could not download $f - TTS will fall back to espeak-ng"
  done
  echo "==> Whisper model (small.en)"
  "$VENV/bin/python" -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8')" || echo "!! whisper download failed; it will retry on first use"
fi

if [ "$PART" -ge 3 ]; then
  echo "==> launcher, desktop entry, autostart"
  cat > "$HOME/.local/bin/aura" <<LAUNCH
#!/usr/bin/env bash
export PYTHONPATH="$HERE\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$VENV/bin/python" -m aura "\$@"
LAUNCH
  chmod +x "$HOME/.local/bin/aura"
  mkdir -p "$HOME/.local/share/applications" "$HOME/.config/autostart"
  cat > "$HOME/.local/share/applications/aura.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Aura
Comment=Local voice and text assistant
Exec=$HOME/.local/bin/aura show
Icon=audio-input-microphone
Categories=Utility;
Terminal=false
DESK
  cat > "$HOME/.config/autostart/aura.desktop" <<AUTO
[Desktop Entry]
Type=Application
Name=Aura (background)
Exec=$HOME/.local/bin/aura --background
X-KDE-autostart-after=panel
Terminal=false
AUTO
  echo "Launcher: ~/.local/bin/aura  (make sure ~/.local/bin is in PATH)"
fi
echo "==> done. Next: ./run.sh $( [ "$PART" = 1 ] && echo chat || ([ "$PART" = 2 ] && echo voice || echo app) )"

if [ "$PART" -ge 3 ]; then
  echo "==> permissions for Meta-key hold and mouse/keyboard control (needs sudo once)"
  if ! id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
    sudo usermod -aG input "$USER" && echo "   added you to the 'input' group: LOG OUT AND BACK IN for it to apply"
  fi
  if [ ! -e /etc/udev/rules.d/99-uinput.rules ]; then
    echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null
    echo uinput | sudo tee /etc/modules-load.d/uinput.conf >/dev/null
    sudo modprobe uinput || true
    sudo udevadm control --reload && sudo udevadm trigger || true
  fi
  echo "   vision model for screen help:  ollama pull gemma3:12b   (any model that lists 'vision' works)"
fi
