"""LLM-Clients: LLM Bahnhof (OpenAI-kompatible Chat-API) und Ollama (Vision/OCR)."""
import base64
import re
import time
from datetime import datetime

import requests

from . import config


class LLMError(RuntimeError):
    pass


def _strip_think(text: str) -> str:
    """Manche Modelle betten Reasoning in <think>...</think> ein."""
    if not text:
        return text
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I).strip()


class BahnhofClient:
    """OpenAI-kompatible Chat-Completions gegen den LLM Bahnhof."""

    def __init__(self, url: str | None = None, model: str | None = None,
                 timeout: int = 180):
        self.url = (url or config.BAHNHOF_URL).rstrip("/")
        self.model = model or config.BAHNHOF_MODEL
        self.timeout = timeout

    def chat(self, system: str, user: str, temperature: float = config.TEMPERATURE,
             max_tokens: int | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            # Reasoning ist für Übersetzen reiner Overhead (verbrennt Tokens,
            # verursacht leere Antworten). Wird von Backends ohne Unterstützung
            # ignoriert.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        last_err = None
        for attempt in range(config.MAX_RETRIES):
            try:
                r = requests.post(f"{self.url}/chat/completions", json=payload,
                                  timeout=self.timeout)
                if r.status_code in (429, 500, 502, 503, 504):
                    last_err = LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                    time.sleep(2 * (attempt + 1) ** 2)
                    continue
                r.raise_for_status()
                data = r.json()
                msg = data["choices"][0]["message"]
                content = _strip_think(msg.get("content") or "")
                if content:
                    return content
                # Reasoning-Modell: Budget im Nachdenken verbrannt ->
                # max_tokens verdoppeln und sofort erneut versuchen
                reasoning = msg.get("reasoning_content") or ""
                if reasoning:
                    cur = payload.get("max_tokens") or 2048
                    payload["max_tokens"] = min(cur * 2, 16384)
                    last_err = LLMError(
                        f"leere Antwort (Reasoning '{len(reasoning)}' Zeichen, "
                        f"max_tokens={cur})")
                    continue
                last_err = LLMError("leere Antwort vom Modell")
                time.sleep(2)
                continue
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                time.sleep(2 * (attempt + 1) ** 2)
        raise LLMError(f"Bahnhof nicht erreichbar / Fehler: {last_err}")

    def detect_language(self, sample: str) -> str:
        """Erkennt die Sprache eines Textmusters, gibt ISO-Code zurück."""
        out = self.chat(
            "You are a language detector. Answer with ONLY the ISO 639-1 "
            "language code (two lowercase letters) of the text.",
            sample[:1500], temperature=0.0, max_tokens=512,
        )
        m = re.search(r"[a-z]{2}", out.lower())
        return m.group(0) if m else "en"


class OllamaClient:
    """Ollama-Client für Vision/OCR — mit Zeitfenster-Guard."""

    def __init__(self, url: str | None = None, model: str | None = None,
                 timeout: int = 600, ignore_window: bool = False):
        self.url = (url or config.OLLAMA_URL).rstrip("/")
        self.model = model or config.OLLAMA_VISION_MODEL
        self.timeout = timeout
        self.ignore_window = ignore_window

    # ---- Zeitfenster-Guard ------------------------------------------------
    @staticmethod
    def check_window(host: str | None = None) -> str | None:
        """Gibt einen Sperr-Hinweis zurück, wenn wir in einem gesperrten
        Zeitfenster sind UND der Host gesperrt ist, sonst None."""
        if host and not any(h in host for h in config.OLLAMA_RESTRICTED_HOSTS):
            return None
        now = datetime.now().strftime("%H:%M")
        for a, b in config.OLLAMA_BLOCKED_WINDOWS:
            if a <= now < b:
                return f"{a}-{b}"
        return None

    def _guard(self):
        w = self.check_window(self.url)
        if w and not self.ignore_window:
            raise LLMError(
                f"Ollama an {self.url} ist zwischen {w} Uhr gesperrt. "
                "Warte bis zum Ende des Zeitfensters, nutze --ignore-window "
                "oder konfiguriere einen anderen Endpunkt."
            )

    # ---- API ---------------------------------------------------------------
    def alive(self) -> bool:
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=5)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def chat(self, user: str, system: str | None = None,
             model: str | None = None, temperature: float = 0.1,
             timeout: int | None = None) -> str:
        """Text-Chat über ein beliebiges Ollama-Modell (z.B. Mini-Übersetzer)."""
        self._guard()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload = {"model": model or self.model, "messages": messages,
                   "stream": False, "options": {"temperature": temperature}}
        last_err = None
        for attempt in range(config.MAX_RETRIES):
            try:
                r = requests.post(f"{self.url}/api/chat", json=payload,
                                  timeout=timeout or self.timeout)
                r.raise_for_status()
                content = _strip_think(
                    r.json().get("message", {}).get("content") or "")
                if content:
                    return content
                last_err = LLMError("leere Antwort vom Modell")
            except requests.RequestException as e:
                last_err = e
            time.sleep(2 * (attempt + 1))
        raise LLMError(f"Ollama-Chat fehlgeschlagen: {last_err}")

    def ocr_image(self, jpeg_bytes: bytes, prompt: str | None = None) -> str:
        """Vision-OCR: JPEG-Bild -> transkribierter Text."""
        self._guard()
        b64 = base64.b64encode(jpeg_bytes).decode()
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": prompt or (
                    "Transcribe ALL text visible in this book page image. "
                    "Preserve reading order and paragraph structure (separate "
                    "paragraphs with a blank line). Keep the original language, "
                    "spelling and punctuation. Do not summarize, do not comment, "
                    "output ONLY the transcribed text. If there is no readable "
                    "text, output nothing."
                ),
                "images": [b64],
            }],
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 8192},
        }
        last_err = None
        for attempt in range(config.MAX_RETRIES):
            try:
                r = requests.post(f"{self.url}/api/chat", json=payload,
                                  timeout=self.timeout)
                r.raise_for_status()
                content = _strip_think(r.json().get("message", {}).get("content") or "")
                return content
            except (requests.ConnectionError, requests.Timeout,
                    requests.HTTPError) as e:
                last_err = e
                self._guard()
                time.sleep(3 * (attempt + 1))
        raise LLMError(f"Ollama-OCR fehlgeschlagen: {last_err}")
