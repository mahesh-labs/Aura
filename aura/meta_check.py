"""`./run.sh meta` : why doesn't holding the Meta key work? Checks each requirement, then shows live key events."""
import grp, os, sys, time, glob, selectors


def main() -> int:
    print("user:", os.environ.get("USER"), "| groups now:", " ".join(grp.getgrgid(g).gr_name for g in os.getgroups()))
    try:
        in_db = [g.gr_name for g in grp.getgrall() if os.environ.get("USER") in g.gr_mem]
    except Exception:
        in_db = []
    print("groups on disk:", " ".join(in_db))
    if "input" in in_db and "input" not in [grp.getgrgid(g).gr_name for g in os.getgroups()]:
        print("  -> you ARE in the input group, but this session doesn't know yet: LOG OUT AND BACK IN (or reboot).")
    elif "input" not in in_db:
        print("  -> not in the input group. Run: sudo usermod -aG input $USER   then log out and back in.")
    try:
        import evdev
        from evdev import ecodes
    except Exception as e:
        print("python-evdev missing:", e, "\n  -> uv pip install --python ~/.local/share/aura/venv/bin/python evdev")
        return 1
    print("python-evdev:", evdev.__version__ if hasattr(evdev, "__version__") else "ok")
    nodes = sorted(glob.glob("/dev/input/event*"))
    readable = [n for n in nodes if os.access(n, os.R_OK)]
    print(f"/dev/input/event*: {len(nodes)} found, {len(readable)} readable")
    devs = []
    for n in readable:
        try:
            d = evdev.InputDevice(n)
            keys = d.capabilities().get(ecodes.EV_KEY, [])
            tag = "KEYBOARD" if (ecodes.KEY_LEFTMETA in keys and ecodes.KEY_A in keys) else ""
            print(f"  {n}  {d.name!r} {tag}")
            if tag:
                devs.append(d)
        except Exception as e:
            print(f"  {n}  error: {e}")
    if not devs:
        print("\nNo readable keyboard -> that's the problem (permissions / not logged in again after adding the group).")
        return 1
    print("\nPress and HOLD the Meta key for 2 seconds, then press a few other keys. Watching for 12 s...")
    sel = selectors.DefaultSelector()
    for d in devs:
        sel.register(d, selectors.EVENT_READ)
    end, down = time.time() + 12, None
    names = {ecodes.KEY_LEFTMETA: "LEFT META", ecodes.KEY_RIGHTMETA: "RIGHT META"}
    while time.time() < end:
        for key, _ in sel.select(timeout=0.5):
            for ev in key.fileobj.read():
                if ev.type != ecodes.EV_KEY or ev.value == 2:
                    continue
                nm = names.get(ev.code) or ecodes.KEY.get(ev.code, ev.code)
                if ev.code in names:
                    if ev.value == 1:
                        down = time.time()
                    elif down:
                        print(f"  {nm} released after {time.time() - down:.2f} s  {'<- long enough' if time.time() - down >= 1 else '<- too short'}")
                        continue
                print(f"  {nm} {'down' if ev.value else 'up'}")
    print("\nIf Meta showed up above with a hold time, the key reading works; send me the Aura log lines containing 'meta'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
