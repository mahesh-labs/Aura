# Aura — local voice + text desktop assistant (Ollama, fully open source)

Built for: CachyOS/Arch, KDE Plasma (Wayland), Ollama + `qwen3-coder:30b`, RTX 4080 Super.
Build it in **three independent parts**. Each part works on its own; don't start the next until the
previous one behaves.

| Part | What you get | Needs |
|---|---|---|
| 1 | Agent that controls your PC by text, in the terminal | Ollama only |
| 2 | Same agent by voice, in the terminal (mic → Whisper → agent → Kokoro voice) | Part 1 + audio libs |
| 3 | Background app: tray icon, hotkey blob (voice), hotkey quick chat box, full window with chats/activity/settings | Part 2 + PySide6 |

Put this folder somewhere permanent (e.g. `~/aura`) — launchers point into it.

---------------------------------------------------------------------------------------------
## Part 1 — the agent (terminal)

```bash
cd ~/aura
./install.sh 1
ollama pull qwen3-coder:30b        # if not already pulled
./run.sh chat
```
Try: `what time is it`, `open firefox`, `set volume to 30`, `what is using my GPU`,
`create a file ~/test.txt containing hello` (it will ask before writing),
`run: ls ~/Downloads` (asks before running shell commands).

* Anything that changes your system asks `allow? [y/N]` first (run_shell, write_text_file,
  move_to_trash, power_action). Safe tools (open app, volume, info, read files) run directly.
* Settings live in `~/.config/aura/config.json` (created on first run; keys are listed in `aura/config.py`).
  Most useful: `model`, `num_ctx` (32768), `ollama_url`.
* Add your own tools in `aura/tools.py` with the `@tool(...)` decorator.
* Every action is logged to `~/.local/share/aura/aura.db` (table `actions`).
* Check the logic any time with `./run.sh test` (uses a fake Ollama; no GPU needed).

**Part 1 done when:** the tool calls above work. If the model ignores tools, use a Qwen3-Coder/Qwen3
instruct model and keep `num_ctx` ≥ 16384.

---------------------------------------------------------------------------------------------
## Part 2 — voice (terminal)

```bash
./install.sh 2        # audio libs, Whisper small.en, Kokoro voice (~340 MB download)
./run.sh voice
```
Press Enter, speak, stop talking → it transcribes, acts, and speaks the answer. For risky actions it
asks out loud; answer "yes" or "no".

Tuning (`~/.config/aura/config.json`):
* Mishears you (Indian English accent?) → `"stt_model": "medium.en"` (or `"large-v3-turbo"`).
* Whisper on GPU: `"stt_device": "cuda", "stt_compute": "float16"` (needs `sudo pacman -S cuda cudnn`;
  falls back to CPU automatically if it fails). CPU is fine and keeps VRAM free for the LLM.
* Wrong mic/speakers → `"input_device"` / `"output_device"` (device names; list with
  `python -c "import sounddevice as s; print(s.query_devices())"` inside the venv).
* Cuts you off / never stops → `"silence_ms"` (default 900), `"vad_min_level"` (default 0.012; raise it in
  noisy rooms, lower it for quiet mics).
* Voice: `"tts_voice"` (af_sarah, af_bella, am_adam, bf_emma, bm_george…), `"tts_speed"`.
  If Kokoro files are missing it falls back to `espeak-ng` (robotic but works).
* Slow replies? The 30B model doesn't fully fit in 16 GB VRAM. For snappy voice, try a smaller model
  (`"model": "qwen3:14b"` or similar) and keep the 30B for text/coding.

**Part 2 done when:** you can have a spoken exchange and a spoken yes/no confirmation.

---------------------------------------------------------------------------------------------
## Part 3 — the app (tray + blob + quick chat + full window)

```bash
./install.sh 3
~/.local/bin/aura --background      # or just log out/in: it autostarts
```
Then bind two global shortcuts in **System Settings → Shortcuts → Add New → Command**:

| Command | Suggested key | Does |
|---|---|---|
| `aura voice` | Ctrl+Alt+V | toggle voice mode — blob appears top-right, press again to stop |
| `aura chat`  | Ctrl+Alt+Space | toggle the quick chat box (Esc closes) |

Tray icon: click → full window (all chats, Activity log of every action, Settings).
Other commands: `aura show | new-chat | voice-start | voice-stop | status | quit`.

How placement works on Wayland: apps can't position themselves, so Aura loads a tiny KWin script over
D-Bus (`aura/kwin.py`) that puts the blob in your chosen corner, keeps it above windows, and focuses the
quick chat box. Corner/margin are in Settings → Floating blob.

**Status of Part 3 — read this:** it was written and statically checked but I could **not run the Qt UI**
in my sandbox (no PySide6 there), so expect first-run bugs. The agent, tools, voice logic and storage under it
are tested. If something fails:
1. Run `aura --background` from a terminal and read the output, or `tail -f ~/.local/share/aura/aura.log`
   (QML errors are logged as `qml:` lines, with file and line number).
2. Blob not in the corner / not on top → KWin script didn't load (log line "KWin ..."). Workaround:
   System Settings → Window Management → Window Rules → add rule for window title `Aura Blob`:
   Position, Keep above, Skip taskbar, No titlebar.
3. Shortcut does nothing → run `aura voice` in a terminal; if that works the binding is the problem.

Paste the error lines into a new chat with any assistant along with `aura/ui/qml/<file>` for a quick fix.

---------------------------------------------------------------------------------------------
## Update 1 — audio fix + wake word
* **Mic/speaker errors** (`PortAudioError ... ALSA error -2`): Aura now prefers the PipeWire device, retries at the
  device's own sample rate and resamples. Also run once: `sudo pacman -S --needed pipewire-alsa pipewire-pulse alsa-utils`.
  Diagnose with `./run.sh audio` (lists devices, plays a beep, measures the mic).
* **Wake word:** Settings → Wake word (or tray menu, or `aura wake-on`). Say "hey aura" or "hey aura, open Firefox".
  Uses a small Whisper model on CPU; the mic stays open while idle. Edit `wake_phrases` to add spellings Whisper
  tends to hear. Off by default.

## Update 2 — fixes + UI rework
- Chats: rename (double-click or pencil), pin, queue messages while Aura is busy, stop button, time per reply.
- Voice approvals read the actual command and accept spoken or typed instructions instead of yes/no.
- Steadier audio (persistent mic/speaker streams) and a friendly voice-name dropdown.
- **Settings now stage changes**: edit freely, then press **Apply** (or **Revert**) in the bar at the bottom.
- **Floating blob position**: pick the monitor and click/drag in the mini screen (Settings → Floating blob).
- **Activity** page lists voice, chat, tool, approval and error events with filter chips.
- New gradient look with slow looping background glow (no blur). Animations pause when the window is hidden/unfocused.
- Title-bar flicker: Aura now defaults to Qt's `basic` render loop; if it still flickers, turn on
  Settings → Main window → "Use Aura's own title bar" and restart Aura.

## Update 3 — voice polish
- Click the status pill under the blob to show the whole message; click again to collapse.
- Live card under the blob during voice mode: what you said, and Aura's reply as it streams in.
- Sounds (Settings → Sounds): voice start/stop chimes, an approval ping, warning and error tones. Generated locally and
  played on the open speaker stream. Toggle and volume are in Settings.
- Blob placement uses a KWin window rule written from Settings → Floating blob.
- `./run.sh kwin` prints placement diagnostics.

## Layout
```
aura/config.py   settings + paths        aura/voice.py    mic/VAD, Whisper, Kokoro, voice session
aura/db.py       chats + action log      aura/backend.py  Qt bridge (models, signals, settings)
aura/llm.py      Ollama streaming        aura/app.py      daemon, tray, IPC, QML loading
aura/tools.py    23 PC-control tools     aura/kwin.py     overlay placement on KDE/Wayland
aura/agent.py    tool-calling loop       aura/ui/qml/     Blob, QuickChat, Main, Settings, Activity
aura/cli_chat.py (Part 1)  aura/voice_cli.py (Part 2)  aura/__main__.py (Part 3 command line)
tests/           mock-Ollama + VAD tests
```

## Next ideas (not built)
Wake word ("hey aura") with openWakeWord · MCP servers as extra tools · web search (SearXNG) ·
vision via a Qwen-VL model · Silero VAD for noisy rooms · interrupt-by-speaking (barge-in).

## Screen help, pointer, MCP (patch 29)
- Ask "what's on my screen?" or "how do I export this?". Aura takes a screenshot and asks a vision model
  (Settings -> Screen reading; `ollama pull gemma3:12b` works). With a target it dims the screen and glows a box around it.
  Test without the LLM: `./run.sh app point-test` (while Aura is running); with it: `./run.sh app look-test`.
- MCP servers: add to ~/.config/aura/config.json, e.g.
  `"mcp_servers": {"files": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/you/Documents"]}}`.
  Their tools appear as `mcp_<server>_<tool>` and ask for approval by default.
- Accurate pointing needs OCR: `sudo pacman -S tesseract tesseract-data-eng`. Aura reads the screen's text with it, asks the model
  *which words* to point at, and draws the box around the real position of those words. Without tesseract it falls back to a grid method.
- Icons and shapes: Aura finds likely controls with OpenCV (`opencv-python-headless`), numbers them on the picture and lets the model
  choose a number, so it never has to guess coordinates. "All screens" mode looks at every monitor.

## Mouse and keyboard control (patch 39)
"Click the close button", "click the text box in Notepad and type ...". Tools: click_element, type_text, press_keys, scroll_mouse
(they ask for approval first; change that under Settings -> What Aura is allowed to do). Needs /dev/uinput access, see
`aura/inputctl.py`; test with `./run.sh input`.

## Install as a standalone app (patch 44)
`./install-app.sh` (add `--wake` for the "hey aura" wake word) copies Aura to `~/.local/share/aura/app`, installs the launcher `aura`,
the app-menu entry, and a systemd user service that starts Aura at login and restarts it if it crashes. You can then delete the
unzipped folder. Update by running `./install-app.sh` from a newer folder. Remove with `~/.local/share/aura/app/uninstall-app.sh`.
Handy: `aura doctor`, `aura voice`, `aura chat`, `systemctl --user status aura`.
