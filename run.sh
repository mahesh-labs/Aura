#!/usr/bin/env bash
# ./run.sh chat   -> Part 1 terminal chat
# ./run.sh voice  -> Part 2 terminal voice chat
# ./run.sh audio -> microphone/speaker diagnostic
# ./run.sh mic    -> which microphone delivers sound
# ./run.sh models -> finds which native library combination crashes
# ./run.sh kwin  -> blob placement diagnostic
# ./run.sh app    -> Part 3 background app (same as the `aura` launcher)
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${XDG_DATA_HOME:-$HOME/.local/share}/aura/venv/bin/python"
export PYTHONPATH="$HERE"
case "${1:-}" in
  chat)  exec "$PY" -m aura.cli_chat ;;
  voice) exec "$PY" -m aura.voice_cli ;;
  app)   shift; exec "$PY" -m aura "${@:-show}" ;;
  audio) exec "$PY" -m aura.audio_check ;;
  kwin)  exec "$PY" -m aura.kwin_debug ;;
  mic)   exec "$PY" -m aura.mic_check ;;
  vision) exec "$PY" -m aura.vision_check ;;
  meta)  exec "$PY" -m aura.meta_check ;;
  input) exec "$PY" -m aura.input_check ;;
  doctor) exec "$PY" -c "import sys; from aura.cli import main; sys.exit(main(['doctor']))" ;;
  models) exec "$PY" -m aura.model_check ;;
  test)  exec "$PY" "$HERE/tests/test_core.py" ;;
  *) echo "usage: $0 chat|voice|app|audio|mic|kwin|models|vision|meta|input|doctor|test"; exit 1 ;;
esac
