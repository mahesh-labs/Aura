"""KDE Plasma 6 (Wayland) integration: desktop entries, autostart, KWin window rules.

Wayland clients cannot position themselves or stay on top, so the overlay windows are
placed by KWin window rules that Aura writes with kwriteconfig6.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import CONFIG_DIR, DATA_DIR

BLOB_RULE = "fba9141f-e936-4560-9cbc-d0cd15980ccf"
POPUP_RULE = "8085a67e-1fb5-44a0-b17f-5206174d1de8"

BLOB_SIZE = (300, 520)      # must match Blob.qml
POPUP_MARGIN = 12           # transparent shadow margin around the card (PopupWindow.qml)

APPLICATIONS = Path.home() / ".local/share/applications"
AUTOSTART = Path.home() / ".config/autostart"
ICONS = Path.home() / ".local/share/icons/hicolor/scalable/apps"


def aura_exe() -> str:
    return shutil.which("aura") or str(Path(sys.argv[0]).resolve())


# ----------------------------------------------------------------- desktop files
def desktop_entry() -> str:
    exe = aura_exe()
    return f"""[Desktop Entry]
Type=Application
Name=Aura
GenericName=Local AI assistant
Comment=Voice and text assistant powered by your local Ollama models
Exec={exe} show
Icon=aura
Terminal=false
Categories=Utility;
StartupWMClass=aura
Actions=Voice;Chat;

[Desktop Action Voice]
Name=Voice mode (toggle)
Exec={exe} voice

[Desktop Action Chat]
Name=Quick chat (toggle)
Exec={exe} chat
"""


def autostart_entry() -> str:
    return f"""[Desktop Entry]
Type=Application
Name=Aura
Comment=Local AI assistant (background service)
Exec={aura_exe()} start --background
Icon=aura
Terminal=false
X-KDE-autostart-after=panel
X-GNOME-Autostart-enabled=true
"""


def install_files() -> list[str]:
    done = []
    APPLICATIONS.mkdir(parents=True, exist_ok=True)
    AUTOSTART.mkdir(parents=True, exist_ok=True)
    ICONS.mkdir(parents=True, exist_ok=True)
    (APPLICATIONS / "aura.desktop").write_text(desktop_entry())
    done.append(str(APPLICATIONS / "aura.desktop"))
    (AUTOSTART / "aura.desktop").write_text(autostart_entry())
    done.append(str(AUTOSTART / "aura.desktop"))
    icon = Path(__file__).parent / "assets" / "aura.svg"
    if icon.exists():
        shutil.copy(icon, ICONS / "aura.svg")
        done.append(str(ICONS / "aura.svg"))
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(APPLICATIONS)], capture_output=True)
    if shutil.which("kbuildsycoca6"):
        subprocess.run(["kbuildsycoca6"], capture_output=True)
    return done


def uninstall_files() -> None:
    for p in (APPLICATIONS / "aura.desktop", AUTOSTART / "aura.desktop", ICONS / "aura.svg"):
        p.unlink(missing_ok=True)
    remove_window_rules()


# ----------------------------------------------------------------- KWin rules
def _kwrite(group: str, key: str, value: str, typ: str | None = None) -> None:
    cmd = ["kwriteconfig6", "--file", "kwinrulesrc", "--group", group, "--key", key]
    if typ:
        cmd += ["--type", typ]
    subprocess.run(cmd + [value], capture_output=True, check=False)


def _kread(group: str, key: str) -> str:
    try:
        p = subprocess.run(
            ["kreadconfig6", "--file", "kwinrulesrc", "--group", group, "--key", key],
            capture_output=True, text=True, timeout=5,
        )
        return p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _reconfigure_kwin() -> None:
    for cmd in (
        ["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"],
        ["dbus-send", "--session", "--dest=org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure"],
    ):
        if shutil.which(cmd[0]):
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                return


def _write_rule(group: str, description: str, title: str, pos: tuple[int, int],
                focus_steal_off: bool) -> None:
    _kwrite(group, "Description", description)
    _kwrite(group, "wmclass", "aura")
    _kwrite(group, "wmclasscomplete", "false", "bool")
    _kwrite(group, "wmclassmatch", "2")      # substring
    _kwrite(group, "title", title)
    _kwrite(group, "titlematch", "2")        # substring
    _kwrite(group, "position", f"{pos[0]},{pos[1]}")
    _kwrite(group, "positionrule", "2")      # force
    for key in ("above", "noborder", "skiptaskbar", "skippager", "skipswitcher"):
        _kwrite(group, key, "true", "bool")
        _kwrite(group, key + "rule", "2")
    if focus_steal_off:
        _kwrite(group, "fsplevel", "0")
        _kwrite(group, "fsplevelrule", "2")
    else:
        _kwrite(group, "acceptfocus", "false", "bool")
        _kwrite(group, "acceptfocusrule", "2")


def ensure_window_rules(screen: tuple[int, int, int, int], blob_margin: int, popup_width: int) -> bool:
    """screen = (x, y, w, h) in logical pixels. Returns True if rules were (re)written."""
    if not shutil.which("kwriteconfig6"):
        return False
    sx, sy, sw, sh = screen
    blob_pos = (sx + sw - BLOB_SIZE[0] - blob_margin, sy + blob_margin)
    pw = popup_width + 2 * POPUP_MARGIN
    popup_pos = (sx + (sw - pw) // 2, sy + int(sh * 0.16))

    want = {BLOB_RULE: f"{blob_pos[0]},{blob_pos[1]}", POPUP_RULE: f"{popup_pos[0]},{popup_pos[1]}"}
    rules = [r for r in _kread("General", "rules").split(",") if r]
    if all(g in rules and _kread(g, "position") == p for g, p in want.items()):
        return False

    _write_rule(BLOB_RULE, "Aura: voice blob", "Aura Blob", blob_pos, focus_steal_off=False)
    _write_rule(POPUP_RULE, "Aura: quick chat", "Aura Quick Chat", popup_pos, focus_steal_off=True)
    for g in (BLOB_RULE, POPUP_RULE):
        if g not in rules:
            rules.append(g)
    _kwrite("General", "rules", ",".join(rules))
    _kwrite("General", "count", str(len(rules)))
    _reconfigure_kwin()
    return True


def set_blob_rule(x: int, y: int) -> bool:
    """Force the blob window to (x, y) (global logical pixels) with a KWin window rule matched on its title.
    A script cannot move a freshly mapped Wayland window reliably; a rule is applied by KWin at placement."""
    if not shutil.which("kwriteconfig6"):
        return False
    g = BLOB_RULE
    _kwrite(g, "Description", "Aura: voice blob")
    _kwrite(g, "title", "Aura Blob")
    _kwrite(g, "titlematch", "1")            # exact
    _kwrite(g, "wmclassmatch", "0")          # any application id
    _kwrite(g, "position", f"{int(x)},{int(y)}")
    _kwrite(g, "positionrule", "2")          # force
    for key in ("above", "skiptaskbar", "skippager", "skipswitcher"):
        _kwrite(g, key, "true", "bool")
        _kwrite(g, key + "rule", "2")
    rules = [r for r in _kread("General", "rules").split(",") if r]
    if g not in rules:
        rules.append(g)
    _kwrite("General", "rules", ",".join(rules))
    _kwrite("General", "count", str(len(rules)))
    _reconfigure_kwin()
    return True


def remove_window_rules() -> None:
    if not shutil.which("kwriteconfig6"):
        return
    rules = [r for r in _kread("General", "rules").split(",") if r and r not in (BLOB_RULE, POPUP_RULE)]
    for g in (BLOB_RULE, POPUP_RULE):
        subprocess.run(
            ["kwriteconfig6", "--file", "kwinrulesrc", "--group", g, "--delete"],
            capture_output=True, check=False,
        )
    _kwrite("General", "rules", ",".join(rules))
    _kwrite("General", "count", str(len(rules)))
    _reconfigure_kwin()


def rules_installed() -> bool:
    rules = _kread("General", "rules").split(",")
    return BLOB_RULE in rules and POPUP_RULE in rules


SHORTCUT_HELP = """\
Bind your hotkeys once in System Settings:

  System Settings -> Keyboard -> Shortcuts -> Add New -> Application... -> pick "Aura"
  then assign keys to its actions "Voice mode (toggle)" and "Quick chat (toggle)".

  (Alternative: Add New -> Command or Script, with the commands `aura voice` and `aura chat`.)

Suggested keys: Meta+Alt+V for voice, Meta+Alt+C for quick chat.
"""
