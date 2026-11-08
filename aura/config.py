"""Paths and persistent settings (JSON in ~/.config/aura/config.json)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

APP = "aura"
HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / APP
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share") / APP
MODELS_DIR = DATA_DIR / "models"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/aura-{os.getuid()}")
SOCKET_PATH = RUNTIME_DIR / "aura.sock"
LOCK_PATH = RUNTIME_DIR / "aura.lock"
CONFIG_PATH = CONFIG_DIR / "config.json"
DB_PATH = DATA_DIR / "aura.db"
LOG_PATH = DATA_DIR / "aura.log"

DEFAULTS: dict = {
    # --- LLM (Ollama) ---
    "ollama_url": "http://localhost:11434",
    "model": "qwen3-coder:30b",
    "num_ctx": 32768,
    "temperature": 0.3,
    "keep_alive": "30m",
    "max_steps": 8,
    "user_name": "",
    "extra_instructions": "",
    # --- screen reading (needs a vision-capable Ollama model; empty = auto-detect gemma3 / llava / qwen-vl ...) ---
    "vision_model": "",
    "screen_target": "",           # monitor to look at (e.g. DP-1); empty = the monitor under the mouse
    "pointer_seconds": 3.0,
    "type_method": "paste",        # paste = clipboard + Ctrl+V (any keyboard layout, any language); keys = key presses (US layout)        # how long the highlight stays on screen
    # --- MCP servers (stdio): {"name": {"command": "npx", "args": [...], "env": {...}}} ---
    "mcp_servers": {},
    # --- tools ---
    "disabled_tools": [],
    "ask_overrides": {},          # tool name -> True/False (ask before running)
    # --- speech to text (faster-whisper) ---
    "stt_model": "small.en",
    "stt_device": "cpu",          # cpu | cuda | auto
    "stt_compute": "int8",        # int8 (cpu) | float16 (cuda)
    "stt_language": "en",
    "input_device": "",
    # --- text to speech ---
    "tts_engine": "kokoro",       # kokoro | espeak
    "tts_voice": "af_sarah",
    "tts_speed": 1.0,
    "output_device": "",
    "audio_backend": "auto",      # auto | pulse | portaudio. auto = parec/pacat when installed (safer than PortAudio)
    # --- sounds ---
    "sounds_enabled": True,       # chimes for voice start/stop, approval requests, warnings and errors
    "sounds_volume": 0.5,
    # --- voice behaviour ---
    "silence_ms": 900,
    "wake_enabled": False,        # listen for the wake phrase (mic stays open; all local)
    "wake_phrases": "hey aura, ok aura, okay aura, aura",   # comma separated; aliases help Whisper mishearing
    "wake_stt_model": "base.en",  # small, fast model used only for wake-word detection
    "followup_seconds": 6,        # keep listening this long after a reply (0 = one-shot)
    "vad_min_level": 0.012,
    "barge_in": False,            # talk over Aura to interrupt it. Best with headphones (speakers make it hear itself)
    "barge_in_level": 0.06,       # how loud you must be (higher = harder to trigger by accident)
    # --- Meta key: tap = KDE launcher (unchanged), hold = voice mode (needs the 'input' group) ---
    "meta_hold_enabled": True,
    "meta_hold_seconds": 1.0,
    # --- blob overlay ---
    "blob_corner": "top-right",   # legacy preset name; blob_fx/blob_fy are what is used now
    "blob_fx": 1.0,               # horizontal position 0 (left) .. 1 (right) inside the screen's free area
    "blob_fy": 0.0,               # vertical position 0 (top) .. 1 (bottom)
    "blob_screen": "",            # monitor name (e.g. DP-1); empty = the screen that is active when it appears
    "blob_margin": 24,
    "blob_clickable": False,      # experimental: let the blob's message pill be clicked (uses an input mask; restart)
    # --- main window ---
    "custom_titlebar": False,     # draw our own title bar instead of KDE's (restart Aura to apply)
    "preload_models": True,
}


class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data: dict = json.loads(json.dumps(DEFAULTS))
        self.load()

    def load(self) -> None:
        with self._lock:
            try:
                saved = json.loads(self.path.read_text())
                if isinstance(saved, dict):
                    self._data.update(saved)
            except FileNotFoundError:
                pass
            except Exception:
                # corrupt file: try the last good copy, else defaults (never crash the daemon)
                try:
                    saved = json.loads(self.path.with_suffix(".bak").read_text())
                    if isinstance(saved, dict):
                        self._data.update(saved)
                except Exception:
                    pass

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if self.path.exists():
                    self.path.with_suffix(".bak").write_bytes(self.path.read_bytes())
            except Exception:
                pass
            tmp = self.path.with_suffix(".tmp")
            # only what differs from the defaults, so settings you never touched follow future updates
            tmp.write_text(json.dumps({k: v for k, v in self._data.items() if k not in DEFAULTS or DEFAULTS[k] != v}, indent=2))
            tmp.replace(self.path)

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key, default))

    def __getitem__(self, key: str):
        return self.get(key)

    def set(self, key: str, value, save: bool = True) -> None:
        with self._lock:
            self._data[key] = value
            if save:
                self.save()


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, MODELS_DIR, RUNTIME_DIR):
        d.mkdir(parents=True, exist_ok=True)
