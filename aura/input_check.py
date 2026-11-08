"""`./run.sh input` : can Aura move the mouse where it should, and type? Moves the pointer (no clicks), measures where
it really went, then types a short text."""
import sys
import time

from . import cursor
from .inputctl import CONTROLLER, InputError


def main() -> int:
    import os
    print("/dev/uinput writable:", os.access("/dev/uinput", os.W_OK))
    q = cursor.query() if cursor.available() else None
    if q:
        print("KWin reports the pointer at", (q["x"], q["y"]), "and these monitors (logical pixels):")
        for s in q["screens"]:
            print(f"   {s['name']:12s} x={s['x']} y={s['y']} {s['w']}x{s['h']}")
    else:
        print("(couldn't read the pointer position from KWin: moves will not be verified/corrected)")
    scr = (q or {}).get("screens") or []
    if not scr:
        print("no monitor info; aborting")
        return 1
    ux, uy = min(s["x"] for s in scr), min(s["y"] for s in scr)
    uw = max(s["x"] + s["w"] for s in scr) - ux
    uh = max(s["y"] + s["h"] for s in scr) - uy
    try:
        CONTROLLER._devices()
        print("\nMoving to the centre and the four REAL corners (2 px from the edge) of each monitor (no clicks). wanted -> where it landed:")
        bad = 0
        for s in scr:
            e = 2                                                        # px in from the real edge
            pts = ((s["x"] + s["w"] / 2, s["y"] + s["h"] / 2), (s["x"] + e, s["y"] + e), (s["x"] + s["w"] - 1 - e, s["y"] + e),
                   (s["x"] + s["w"] - 1 - e, s["y"] + s["h"] - 1 - e), (s["x"] + e, s["y"] + s["h"] - 1 - e))
            for x, y in pts:
                r = CONTROLLER.goto(x, y, (ux, uy, uw, uh))
                m = r["measured"]
                flag = "" if r["ok"] else "   <-- MISSED"
                bad += 0 if r["ok"] else 1
                print(f"  {s['name']:10s} wanted ({round(x)},{round(y)})  got {m}  off by {r['error']} px{flag}")
                time.sleep(0.3)
        print("\n" + ("All positions reached." if not bad else f"{bad} positions missed; send me this output."))
        print("\nNow click into any text field (e.g. Kate or a search box). Typing in 6 seconds...")
        for i in range(6, 0, -1):
            print(f"  {i}", end="\r", flush=True)
            time.sleep(1)
        CONTROLLER.type_paste("aura test (paste)")
        time.sleep(0.4)
        CONTROLLER.type_keys(" aura test (keys)")
        print("done.")
    except InputError as e:
        print("\nFAILED:", e)
        return 1
    finally:
        CONTROLLER.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
