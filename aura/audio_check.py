"""Audio diagnostic: python -m aura.audio_check   (or ./run.sh audio)"""
import sys
import time

import numpy as np

from .config import Config
from .voice import SR_IN, Mic, _pick_device, list_devices, open_output, resample


def main() -> int:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = Config()
    import sounddevice as sd
    print("Input devices :", list_devices("input"))
    print("Output devices:", list_devices("output"))
    print("Chosen input idx:", _pick_device(str(cfg["input_device"]), "input"),
          " output idx:", _pick_device(str(cfg["output_device"]), "output"))
    print("\nSpeaker test (a short beep)…")
    try:
        t = np.arange(int(24000 * 0.5)) / 24000
        beep = (0.2 * np.sin(2 * np.pi * 660 * t)).astype(np.float32)
        out, fs, ch = open_output(cfg, 24000)
        out.write(np.repeat(resample(beep, 24000, fs).reshape(-1, 1), ch, axis=1))
        out.stop(); out.close()
        print("  OK")
    except Exception as e:
        print("  FAILED:", e)
    print("\nMic test: say something for 3 seconds…")
    try:
        levels = []
        with Mic(cfg).blocks(lambda: False) as g:
            t0 = time.time()
            for b in g:
                levels.append(float(np.sqrt(np.mean(b * b))))
                if time.time() - t0 > 3:
                    break
        print(f"  OK  quiet≈{np.percentile(levels, 10):.4f}  loud≈{np.percentile(levels, 95):.4f}  "
              f"(speech should be clearly above quiet; vad_min_level is {cfg['vad_min_level']})")
    except Exception as e:
        print("  FAILED:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
