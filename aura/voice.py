"""Voice pipeline: microphone + VAD -> faster-whisper -> (agent) -> Kokoro/espeak TTS -> speakers.

Heavy libraries (sounddevice, faster_whisper, kokoro_onnx) are imported lazily so the app starts fast
and the rest of the code stays testable without audio hardware.
"""
from __future__ import annotations

import contextlib
import io
import logging
import queue
import re
import shutil
import subprocess
import threading
import time
import wave
from collections import deque
from typing import Callable, Iterable

import numpy as np

from .config import MODELS_DIR

log = logging.getLogger("aura.voice")
SR_IN = 16000
BLOCK = 320  # 20 ms @ 16 kHz


# ====================================================================== VAD / utterance capture
def collect_utterance(blocks: Iterable[np.ndarray], *, sr: int = SR_IN, stop: Callable[[], bool] = lambda: False,
                      on_level: Callable[[float], None] | None = None, wait_s: float = 8.0, max_s: float = 30.0,
                      silence_ms: int = 900, min_level: float = 0.012) -> np.ndarray | None:
    """Energy-based endpointing. Returns the utterance (with a little pre-roll) or None if nobody spoke.

    Pure function over an iterable of float32 blocks, so it can be tested with synthetic audio.
    Swap in Silero VAD here later if you want better noise robustness.
    """
    pre: deque = deque(maxlen=12)
    calib: list[float] = []
    noise = 0.003
    speech: list[np.ndarray] = []
    started = False
    run = voiced = 0
    silent = 0.0
    t = 0.0
    for b in blocks:
        if stop():
            return None
        rms = float(np.sqrt(np.mean(b * b)) + 1e-9)
        dur = len(b) / sr
        t += dur
        if on_level:
            on_level(min(1.0, rms * 10))
        if len(calib) < 8 and not started:
            calib.append(rms)
            noise = max(1e-4, min(float(np.median(calib)), 0.015))
        thr = max(min_level, noise * 3.0)
        if not started:
            pre.append(b)
            run = run + 1 if rms > thr else 0
            if run >= 3:
                started, speech, silent, voiced = True, list(pre), 0.0, run
            else:
                noise = 0.97 * noise + 0.03 * min(rms, 0.015)
                if t > wait_s:
                    return None
            continue
        speech.append(b)
        if rms > thr:
            voiced += 1
            silent = 0.0
        elif rms < thr * 0.8:
            silent += dur
        if silent * 1000 >= silence_ms or t >= max_s:
            if voiced < 8 and t < max_s:      # a cough / click, not speech: keep waiting
                started, speech, run, silent, voiced = False, [], 0, 0.0, 0
                pre.clear()
                continue
            break
    if not started or not speech:
        return None
    return np.concatenate(speech).astype(np.float32)


def _pick_device(name: str, kind: str):
    """Choose an audio device index. Prefers PipeWire/Pulse over raw ALSA 'default' (which often fails)."""
    import sounddevice as sd
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    devs = sd.query_devices()
    if name:
        for i, d in enumerate(devs):
            if d["name"] == name and d[key] > 0:
                return i
    for pref in ("pipewire", "pulse", "default"):
        for i, d in enumerate(devs):
            if d["name"].lower() == pref and d[key] > 0:
                return i
    try:
        di = sd.default.device[0 if kind == "input" else 1]
        if di is not None and di >= 0 and devs[di][key] > 0:
            return int(di)
    except Exception:
        pass
    for i, d in enumerate(devs):
        if d[key] > 0:
            return i
    return None


_AUDIO_HELP = ("Could not open the audio device. On Arch/CachyOS run: "
               "sudo pacman -S --needed pipewire-alsa pipewire-pulse alsa-utils  (then try again). "
               "You can also pick a device in Settings or config.json (input_device / output_device).")


def use_pulse(cfg) -> bool:
    """parec/pacat (separate processes) are preferred: PortAudio inside this process can corrupt the heap."""
    mode = str(cfg["audio_backend"] or "auto")
    if mode == "portaudio":
        return False
    from . import audio_pulse
    return audio_pulse.available()


def open_input(cfg, callback):
    """Open a mic stream, trying several device / sample-rate / channel combinations. Returns (stream, rate)."""
    if use_pulse(cfg):
        from . import audio_pulse
        st = audio_pulse.PulseInput(str(cfg["input_device"]), callback)
        log.info("mic opened via parec")
        return st, audio_pulse.PulseInput.RATE
    import sounddevice as sd
    dev = _pick_device(str(cfg["input_device"]), "input")
    errors: list[str] = []
    for d in dict.fromkeys([dev, None]):
        rates = [SR_IN]
        try:
            rates.append(int(sd.query_devices(d, "input")["default_samplerate"]))
        except Exception:
            pass
        for fs in dict.fromkeys(rates):
            for ch in (1, 2):
                try:
                    st = sd.InputStream(samplerate=fs, channels=ch, dtype="float32", blocksize=int(fs * 0.02),
                                        device=d, callback=callback)
                    st.start()
                    log.info("mic opened: device=%s rate=%s channels=%s", d, fs, ch)
                    return st, fs
                except Exception as e:
                    errors.append(f"device={d} rate={fs} ch={ch}: {e}")
    log.error("mic open failed:\n%s", "\n".join(errors))
    raise RuntimeError(_AUDIO_HELP)


def open_output(cfg, sr: int):
    """Open a speaker stream. Returns (stream, rate, channels)."""
    if use_pulse(cfg):
        from . import audio_pulse
        return audio_pulse.PulseOutput(str(cfg["output_device"]), sr), sr, 1
    import sounddevice as sd
    dev = _pick_device(str(cfg["output_device"]), "output")
    errors: list[str] = []
    for d in dict.fromkeys([dev, None]):
        rates = [sr]
        try:
            rates.append(int(sd.query_devices(d, "output")["default_samplerate"]))
        except Exception:
            pass
        for fs in dict.fromkeys(rates):
            for ch in (1, 2):
                try:
                    st = sd.OutputStream(samplerate=fs, channels=ch, dtype="float32", device=d)
                    st.start()
                    return st, fs, ch
                except Exception as e:
                    errors.append(f"device={d} rate={fs} ch={ch}: {e}")
    log.error("speaker open failed:\n%s", "\n".join(errors))
    raise RuntimeError(_AUDIO_HELP)


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(x) == 0:
        return x
    if src % dst == 0:                                  # e.g. 48000 -> 16000: average (cheap anti-alias)
        k = src // dst
        n = len(x) // k * k
        return x[:n].reshape(-1, k).mean(axis=1).astype(np.float32)
    n_out = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x).astype(np.float32)


class MicStream:
    """One open capture stream, reused for a whole voice session.

    Re-opening the microphone for every utterance makes PipeWire (and Bluetooth headsets in particular)
    switch profiles each time: the headset pop-up appears and the volume jumps. Keep it open instead.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.q: queue.Queue = queue.Queue(maxsize=600)
        self.stream = None
        self.fs = SR_IN
        self._got_data = False

    def open(self) -> "MicStream":
        if self.stream is None:
            self.stream, self.fs = open_input(self.cfg, self._cb)
        return self

    def _cb(self, indata, frames, t, status):
        try:
            self.q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def flush(self) -> None:
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                return

    def blocks(self, stop: Callable[[], bool]):
        idle = 0.0
        while True:
            try:
                blk = self.q.get(timeout=0.25)
                idle = 0.0
                self._got_data = True
                yield resample(blk, self.fs, SR_IN)
            except queue.Empty:
                if stop():
                    return
                idle += 0.25
                # a sleeping or Bluetooth-headset microphone can need several seconds to wake up / switch profile
                if idle > 15:
                    raise RuntimeError("No audio from the microphone (check the input device in Settings).")

    def utterance(self, stop: Callable[[], bool], on_level, wait_s: float, flush: bool = True,
                  prefix: list | None = None) -> np.ndarray | None:
        if flush:
            self.flush()                  # drop whatever was heard while we were thinking / speaking
        src = self.blocks(stop)
        if prefix:                        # speech already captured while Aura was talking (barge-in)
            import itertools
            src = itertools.chain((resample(b, self.fs, SR_IN) for b in prefix), src)
        return collect_utterance(src, stop=stop, on_level=on_level, wait_s=wait_s,
                                 silence_ms=int(self.cfg["silence_ms"]),
                                 min_level=float(self.cfg["vad_min_level"]))

    def close(self) -> None:
        st, self.stream = self.stream, None
        if st is not None:
            try:
                st.stop()
                st.close()
            except Exception:
                pass


class Mic:
    def __init__(self, cfg):
        self.cfg = cfg

    @contextlib.contextmanager
    def blocks(self, stop: Callable[[], bool]):
        """Yield a generator of 16 kHz mono float32 blocks. The stream stays open for the whole `with`."""
        ms = MicStream(self.cfg).open()
        try:
            yield ms.blocks(stop)
        finally:
            ms.close()

    def session(self) -> MicStream:
        return MicStream(self.cfg).open()

    def utterance(self, stop: Callable[[], bool], on_level, wait_s: float) -> np.ndarray | None:
        ms = self.session()
        try:
            return ms.utterance(stop, on_level, wait_s, flush=False)
        finally:
            ms.close()


def list_devices(kind: str) -> list[str]:
    from . import audio_pulse
    if audio_pulse.available():
        return audio_pulse.list_devices(kind)
    try:
        import sounddevice as sd
        key = "max_input_channels" if kind == "input" else "max_output_channels"
        seen: list[str] = []
        for d in sd.query_devices():
            if d[key] > 0 and d["name"] not in seen:
                seen.append(d["name"])
        return seen
    except Exception:
        return []


# ====================================================================== STT
class STT:
    def __init__(self, cfg, model_key: str = "stt_model"):
        self.cfg = cfg
        self.model_key = model_key
        self._model = None
        self._key = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            key = (self.cfg[self.model_key], self.cfg["stt_device"], self.cfg["stt_compute"])
            if self._model is not None and key == self._key:
                return
            from faster_whisper import WhisperModel
            name, device, compute = key
            try:
                self._model = WhisperModel(name, device=device, compute_type=compute, cpu_threads=8)
            except Exception as e:
                if device == "cpu":
                    raise
                log.warning("STT on %s failed (%s); falling back to CPU int8", device, e)
                self._model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=8)
            self._key = key
            log.info("STT ready: %s", key)

    def transcribe(self, audio: np.ndarray, prompt: str | None = None) -> str:
        if audio is None or len(audio) < SR_IN * 0.3:
            return ""
        self.load()
        lang = self.cfg["stt_language"] or None
        segs, _ = self._model.transcribe(audio, language=lang, beam_size=1, vad_filter=True,
                                         condition_on_previous_text=False, initial_prompt=prompt)
        return " ".join(s.text.strip() for s in segs).strip()


# ====================================================================== TTS
class KokoroEngine:
    def __init__(self, cfg):
        from kokoro_onnx import Kokoro
        model, voices = MODELS_DIR / "kokoro-v1.0.onnx", MODELS_DIR / "voices-v1.0.bin"
        if not (model.exists() and voices.exists()):
            raise RuntimeError(f"Kokoro model files not found in {MODELS_DIR} (run install.sh)")
        self.k = Kokoro(str(model), str(voices))
        self.cfg = cfg

    def voices(self) -> list[str]:
        try:
            return list(self.k.get_voices())
        except Exception:
            return []

    def synth(self, text: str, voice: str | None = None):
        voice = voice or str(self.cfg["tts_voice"])
        lang = "en-gb" if voice[:1] == "b" else "en-us"
        samples, sr = self.k.create(text, voice=voice, speed=float(self.cfg["tts_speed"]), lang=lang)
        return np.asarray(samples, dtype=np.float32), int(sr)


class EspeakEngine:
    def __init__(self, cfg):
        if not shutil.which("espeak-ng"):
            raise RuntimeError("espeak-ng is not installed")
        self.cfg = cfg

    def synth(self, text: str, voice: str | None = None):
        wpm = int(165 * float(self.cfg["tts_speed"]))
        p = subprocess.run(["espeak-ng", "--stdout", "-s", str(wpm), text], capture_output=True, timeout=30)
        with wave.open(io.BytesIO(p.stdout)) as w:
            sr = w.getframerate()
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        return pcm, sr


class TTSPlayer:
    """Synthesises sentences in one thread and plays them in another so the next sentence is ready in time."""

    def __init__(self, cfg, on_level: Callable[[float], None], on_start: Callable[[], None],
                 on_error: Callable[[str], None]):
        self.cfg, self.on_level, self.on_start, self.on_error = cfg, on_level, on_start, on_error
        self._engine = None
        self._engine_key = None
        self._text_q: queue.Queue = queue.Queue()
        self._audio_q: queue.Queue = queue.Queue(maxsize=3)
        self._gen = 0
        self._pending = 0
        self._cv = threading.Condition()
        self._started = False
        self._warned = False
        self._release = threading.Event()

    # ---- public
    muted = False                       # set while the user is interrupting: drop speech until the turn ends

    def speak(self, text: str, voice: str | None = None) -> None:
        if self.muted:
            return
        self._ensure_threads()
        with self._cv:
            self._pending += 1
        self._text_q.put((self._gen, text, voice))

    def play_sound(self, audio: np.ndarray, sr: int = 24000) -> None:
        """Queue a UI sound on the speaker stream (never cancelled by stop(), never counted as speech)."""
        self._ensure_threads()
        try:
            self._audio_q.put_nowait((-1, audio, sr))
        except queue.Full:
            pass

    def release(self) -> None:
        """Close the speaker stream once playback is finished (called when a voice session ends)."""
        self._release.set()

    def stop(self) -> None:
        with self._cv:
            self._gen += 1
        while True:
            try:
                self._text_q.get_nowait()
            except queue.Empty:
                break
            self._done_one()

    def wait_idle(self, stop: Callable[[], bool] = lambda: False, timeout: float = 180) -> None:
        end = time.time() + timeout
        with self._cv:
            while self._pending > 0 and not stop() and time.time() < end:
                self._cv.wait(0.15)

    def warm(self) -> None:
        try:
            self._get_engine()
        except Exception as e:
            log.warning("TTS warm-up failed: %s", e)

    def invalidate(self) -> None:
        self._engine = None

    # ---- internals
    def _done_one(self) -> None:
        with self._cv:
            self._pending = max(0, self._pending - 1)
            self._cv.notify_all()

    def _ensure_threads(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._synth_loop, daemon=True, name="tts-synth").start()
        threading.Thread(target=self._play_loop, daemon=True, name="tts-play").start()

    def _get_engine(self):
        key = self.cfg["tts_engine"]                  # voice is applied per sentence; no model reload on change
        if self._engine is not None and key == self._engine_key:
            return self._engine
        want = str(self.cfg["tts_engine"])
        errors = []
        for name in ([want] if want != "espeak" else []) + ["espeak"]:
            try:
                self._engine = KokoroEngine(self.cfg) if name == "kokoro" else EspeakEngine(self.cfg)
                self._engine_key = key
                if name != want and not self._warned:
                    self._warned = True
                    self.on_error(f"{want} TTS unavailable ({errors[-1]}); using espeak-ng")
                return self._engine
            except Exception as e:
                errors.append(str(e))
                log.warning("TTS engine %s failed: %s", name, e)
        raise RuntimeError("No TTS engine available: " + "; ".join(errors))

    def _synth_loop(self) -> None:
        while True:
            gen, text, voice = self._text_q.get()
            if gen != self._gen:
                self._done_one()
                continue
            try:
                audio, sr = self._get_engine().synth(text, voice)
            except Exception as e:
                log.exception("TTS synth failed")
                self.on_error(f"TTS error: {e}")
                self._done_one()
                continue
            self._audio_q.put((gen, audio, sr))

    IDLE_CLOSE = 90.0

    def _play_loop(self) -> None:
        """Plays sentences through ONE long-lived output stream (opening a stream per sentence makes PipeWire
        create/destroy a device each time, which can pop up the headset icon and move the volume)."""
        out, out_sr, fs, ch, last = None, 0, 0, 1, time.time()

        def close_out():
            nonlocal out
            if out is not None:
                try:
                    out.stop()
                    out.close()
                except Exception:
                    pass
                out = None

        while True:
            try:
                gen, audio, sr = self._audio_q.get(timeout=0.5)
            except queue.Empty:
                if out is not None and (self._release.is_set() or time.time() - last > self.IDLE_CLOSE):
                    close_out()
                    self._release.clear()
                continue
            self._release.clear()
            sound = gen == -1
            if not sound and gen != self._gen:
                self._done_one()
                continue
            try:
                if not sound:
                    self.on_start()
                if out is None or out_sr != sr:
                    close_out()
                    out, fs, ch = open_output(self.cfg, sr)
                    out_sr = sr
                audio = resample(audio, sr, fs)
                step = 1024
                for i in range(0, len(audio), step):
                    if not sound and gen != self._gen:
                        break
                    chunk = audio[i:i + step]
                    if not sound:
                        self.on_level(min(1.0, float(np.sqrt(np.mean(chunk * chunk))) * 5))
                    out.write(np.repeat(chunk.reshape(-1, 1), ch, axis=1))
            except Exception as e:
                log.exception("audio playback failed")
                self.on_error(f"Audio output error: {e}")
                close_out()
            finally:
                last = time.time()
                if not sound:
                    self.on_level(0.0)
                    self._done_one()


# ====================================================================== controller
YES = re.compile(r"\b(yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|confirm|proceed|allow|affirmative)\b", re.I)
NO = re.compile(r"\b(no|nope|nah|cancel|stop|don'?t|deny|negative|abort)\b", re.I)


def parse_yes_no(text: str) -> bool | None:
    n, y = NO.search(text), YES.search(text)
    if n and (not y or n.start() < y.start()):
        return False
    return True if y else None


def classify_reply(text: str) -> bool | str | None:
    """Approval reply: True/False for a plain yes/no, the text itself for anything longer (= new instructions)."""
    text = (text or "").strip()
    if not text:
        return None
    words = re.findall(r"[\w']+", text)
    if len(words) <= 4:
        v = parse_yes_no(text)
        if v is not None:
            return v
    return text


class VoiceController:
    """One voice session: listen -> transcribe -> agent turn (spoken) -> optionally keep listening."""

    def __init__(self, cfg, hooks):
        """hooks needs: state(str), level(float), caption(str), turn(text, cancel), warm(), toast(str),
        event(kind, title, detail)."""
        self.cfg, self.h = cfg, hooks
        self.mic = Mic(cfg)
        self.stt = STT(cfg)
        self.tts = TTSPlayer(cfg, on_level=hooks.level, on_start=self._tts_started, on_error=hooks.toast)
        self.cancel = threading.Event()
        self.active = False
        self._confirming = False
        self._initial: str | None = None
        self._ms: MicStream | None = None
        self._lock = threading.Lock()

    def preload(self) -> None:
        def go():
            for fn in (self.stt.load, self.tts.warm):
                try:
                    fn()
                except Exception as e:
                    log.warning("preload: %s", e)
        threading.Thread(target=go, daemon=True, name="voice-preload").start()

    def invalidate(self) -> None:
        self.tts.invalidate()

    def toggle(self) -> None:
        self.stop() if self.active else self.start()

    def start(self, initial_text: str | None = None) -> None:
        with self._lock:
            if self.active:
                return
            self.active = True
            self.cancel = threading.Event()
            self._initial = initial_text
        threading.Thread(target=self._run, daemon=True, name="voice-session").start()

    def stop(self) -> None:
        self.cancel.set()
        self.tts.stop()

    def _tts_started(self) -> None:
        if self.active and not self._confirming and not self.cancel.is_set():
            self.h.state("speaking")

    def _listen(self, stop, wait_s: float, prefix: list | None = None):
        if self._ms is not None:
            return self._ms.utterance(stop, self.h.level, wait_s, flush=not prefix, prefix=prefix)
        return self.mic.utterance(stop, self.h.level, wait_s)

    def _barge_watch(self, cancel: threading.Event, tcancel: threading.Event, done: threading.Event, out: dict) -> None:
        """While Aura speaks, listen for the user talking over it. Loud sound for ~0.2 s = interrupt."""
        ms = self._ms
        level = float(self.cfg["barge_in_level"])
        recent: deque = deque(maxlen=14)
        run = 0
        while not done.is_set():
            if cancel.is_set():
                tcancel.set()
                return
            try:
                blk = ms.q.get(timeout=0.05)
            except queue.Empty:
                continue
            if self.tts._pending <= 0:               # not talking: nothing to interrupt, ignore the mic
                recent.clear()
                run = 0
                continue
            recent.append(blk)
            rms = float(np.sqrt(np.mean(blk * blk)) + 1e-9)
            run = run + 1 if rms > level else 0
            if run >= 10:
                out["prefix"] = list(recent)
                self.tts.muted = True
                self.tts.stop()
                tcancel.set()
                log.info("barge-in: user spoke over Aura")
                return

    def _run(self) -> None:
        h, cancel = self.h, self.cancel
        try:
            h.event("system", "Voice mode started", "")
            h.warm()
            self._ms = self.mic.session()           # one open mic stream for the whole session
            first, empties = True, 0
            while not cancel.is_set():
                follow = float(self.cfg["followup_seconds"])
                if self._initial:                       # wake word came with a command: "hey aura, open firefox"
                    text, self._initial = self._initial, None
                    h.state("thinking")
                else:
                    h.state("listening")
                    h.caption("Listening…")
                    audio = self._listen(cancel.is_set, 8.0 if first else follow)
                    h.level(0.0)
                    if cancel.is_set() or audio is None:
                        break
                    h.state("thinking")
                    h.caption("Thinking…")
                    t0 = time.time()
                    text = self.stt.transcribe(audio)
                    h.event("voice", "Heard you", f"{text}\n(speech recognition took {time.time() - t0:.1f} s)")
                    if not text:
                        empties += 1
                        if empties >= 2:
                            break
                        continue
                h.caption(f"“{text}”")
                prefix = None
                if self.cfg["barge_in"] and self._ms is not None:
                    tcancel, done, out = threading.Event(), threading.Event(), {}
                    w = threading.Thread(target=self._barge_watch, args=(cancel, tcancel, done, out),
                                         daemon=True, name="barge-watch")
                    w.start()
                    try:
                        h.turn(text, tcancel)
                        if not tcancel.is_set():
                            self.tts.wait_idle(stop=lambda: cancel.is_set() or tcancel.is_set())
                    finally:
                        done.set()
                        w.join(1.0)
                    prefix = out.get("prefix")
                    if prefix:
                        self.tts.stop()
                        self.tts.muted = False
                        first = False
                        audio = None
                        h.state("listening")
                        h.caption("Listening…")
                        audio = self._listen(cancel.is_set, 8.0, prefix)
                        h.level(0.0)
                        if cancel.is_set() or audio is None:
                            continue
                        self._initial = None
                        h.state("thinking")
                        h.caption("Thinking…")
                        heard = self.stt.transcribe(audio)
                        h.event("voice", "Heard you (interrupting)", heard)
                        if heard:
                            self._initial = heard      # next loop iteration treats it as the user's request
                        continue
                else:
                    h.turn(text, cancel)
                    self.tts.wait_idle(stop=cancel.is_set)
                first = False
                if follow <= 0:
                    break
        except Exception as e:
            log.exception("voice session failed")
            h.toast(f"Voice error: {e}")
            h.event("error", "Voice error", str(e))
            h.state("error")
            h.caption(str(e)[:80])
            time.sleep(1.8)
        finally:
            if cancel.is_set():
                self.tts.stop()
            if self._ms is not None:
                self._ms.close()
                self._ms = None
            self.tts.release()
            h.level(0.0)
            h.state("idle")
            self.active = False
            h.event("system", "Voice mode stopped", "")

    # Called from the voice thread (inside an agent turn) when a tool needs approval.
    # Sets pend.result to True / False / "new instructions" (any longer reply).
    def ask_confirm(self, prompt: str, pend) -> None:
        h = self.h
        self._confirming = True
        try:
            h.state("confirm")
            h.caption(prompt.replace("\n", " ")[:120])
            self.tts.speak(prompt)
            self.tts.wait_idle(stop=lambda: self.cancel.is_set() or pend.event.is_set())
            stop = lambda: self.cancel.is_set() or pend.event.is_set()          # noqa: E731
            for _ in range(2):
                if stop():
                    break
                audio = self._listen(stop, 9.0)
                h.level(0.0)
                if audio is None:
                    continue
                text = self.stt.transcribe(audio)
                h.event("voice", "Approval reply", text)
                ans = classify_reply(text)
                if ans is not None:
                    pend.result = ans
                    pend.event.set()
                    break
        finally:
            self._confirming = False
            if not self.cancel.is_set():
                h.state("thinking")
