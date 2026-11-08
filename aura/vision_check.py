"""`./run.sh vision` : test screen reading step by step, no app needed."""
import sys, tempfile, time
from pathlib import Path
from .config import Config
from .llm import OllamaClient
from . import screen


def main() -> int:
    cfg = Config()
    installed = OllamaClient(cfg).list_models()
    import requests
    try:
        print("loaded in memory now:", [m["name"] for m in requests.get(cfg["ollama_url"] + "/api/ps", timeout=3).json().get("models", [])])
    except Exception as e:
        print("could not read /api/ps:", e)
    print("installed models:", ", ".join(installed) or "(none: is `ollama serve` running?)")
    for n in installed:
        print(f"  {n:40s} vision={screen.has_vision(cfg, n)}")
    import shutil
    print("tesseract (accurate pointing):", shutil.which("tesseract") or "NOT INSTALLED -> sudo pacman -S tesseract tesseract-data-eng")
    model = screen.vision_model(cfg, installed)
    print("\nvision model chosen:", model)
    if not model:
        return 1
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.png"
        t = time.time()
        ok = screen.capture(p)
        print(f"screenshot: {'OK' if ok else 'FAILED'} ({time.time() - t:.1f}s)", p.stat().st_size if ok else "")
        if not ok:
            print("  -> install spectacle (KDE) or grim; run this from a normal desktop terminal, not over SSH.")
            return 1
    t = time.time()
    res = screen.look(cfg, "Describe what is on this screen in one sentence and point at the most prominent window title.", installed)
    print(f"\nmodel reply ({time.time() - t:.0f}s):")
    for k, v in res.items():
        print(f"  {k}: {v}")
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    sys.exit(main())
