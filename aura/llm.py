"""Minimal streaming client for Ollama's native /api/chat (with tool calling)."""
from __future__ import annotations

import json
import threading
from typing import Iterator

import requests


class LLMError(Exception):
    pass


class OllamaClient:
    def __init__(self, cfg):
        self.cfg = cfg

    @property
    def base(self) -> str:
        return str(self.cfg["ollama_url"]).rstrip("/")

    def _options(self) -> dict:
        return {"num_ctx": int(self.cfg["num_ctx"]), "temperature": float(self.cfg["temperature"])}

    def list_models(self, timeout: float = 2.0) -> list[str]:
        try:
            r = requests.get(f"{self.base}/api/tags", timeout=timeout)
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
        except Exception:
            return []

    def warm(self) -> None:
        """Load the model into memory in the background so the first reply is fast."""
        def go():
            try:
                requests.post(f"{self.base}/api/generate",
                              json={"model": self.cfg["model"], "prompt": "",
                                    "keep_alive": self.cfg["keep_alive"], "options": self._options()},
                              timeout=300)
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()

    def chat_stream(self, messages: list[dict], tools: list[dict] | None,
                    cancel: threading.Event) -> Iterator[dict]:
        """Yield {'content': str, 'tool_calls': list|None, 'done': bool} chunks."""
        payload = {"model": self.cfg["model"], "messages": messages, "stream": True,
                   "keep_alive": self.cfg["keep_alive"], "options": self._options()}
        if tools:
            payload["tools"] = tools
        try:
            r = requests.post(f"{self.base}/api/chat", json=payload, stream=True, timeout=(5, 600))
        except requests.ConnectionError:
            raise LLMError(f"Can't reach Ollama at {self.base}. Is `ollama serve` running?")
        except requests.RequestException as e:
            raise LLMError(f"Ollama request failed: {e}")
        if r.status_code != 200:
            try:
                msg = r.json().get("error", r.text)
            except Exception:
                msg = r.text
            raise LLMError(f"Ollama error {r.status_code}: {msg}")
        try:
            for line in r.iter_lines():
                if cancel.is_set():
                    return
                if not line:
                    continue
                obj = json.loads(line)
                if "error" in obj:
                    raise LLMError(f"Ollama error: {obj['error']}")
                m = obj.get("message") or {}
                yield {"content": m.get("content") or "",
                       "tool_calls": m.get("tool_calls") or None,
                       "done": bool(obj.get("done"))}
        except requests.RequestException as e:
            raise LLMError(f"Connection to Ollama lost: {e}")
        finally:
            r.close()
