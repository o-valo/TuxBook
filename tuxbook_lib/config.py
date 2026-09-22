"""Zentrale Konfiguration für TuxBook (tuxbook).

Endpunkte werden in dieser Reihenfolge aufgelöst:
1. tuxbook.conf im Projektverzeichnis (gitignored — persönliche Infrastruktur)
2. Umgebungsvariablen (TUXBOOK_BAHNHOF_URL, TUXBOOK_OLLAMA_URL, ...)
3. Hier eingetragene Fallback-Defaults
Siehe tuxbook.conf.example.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_conf_file() -> dict[str, str]:
    """Liest tuxbook.conf (KEY=VALUE pro Zeile), falls vorhanden."""
    conf = ROOT / "tuxbook.conf"
    out: dict[str, str] = {}
    if conf.exists():
        for line in conf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


_CONF = _load_conf_file()


def _get(key: str, env: str, default: str) -> str:
    return _CONF.get(key) or os.environ.get(env) or default


# --- Endpunkte ---
BAHNHOF_URL = _get("BAHNHOF_URL", "TUXBOOK_BAHNHOF_URL",
                   "http://localhost:8000/v1")
BAHNHOF_MODEL = _get("BAHNHOF_MODEL", "TUXBOOK_BAHNHOF_MODEL", "llm-bahnhof")

OLLAMA_URL = _get("OLLAMA_URL", "TUXBOOK_OLLAMA_URL", "http://localhost:11434")
OLLAMA_VISION_MODEL = _get("OLLAMA_MODEL", "TUXBOOK_OLLAMA_MODEL", "gemma4:12b")
# Zusätzlicher Ollama-Endpunkt (optional, nur nach Freigabe des Betreibers)
OLLAMA_URL_ALT = _get("OLLAMA_URL_ALT", "TUXBOOK_OLLAMA_URL_ALT", "")

# --- Gesperrte Zeitfenster für Ollama (lokale Zeit) ---
# Gilt nur für Hosts aus OLLAMA_RESTRICTED_HOSTS (Substring-Match in der URL).
OLLAMA_BLOCKED_WINDOWS = [("12:30", "13:30"), ("19:30", "20:30")]
_RESTR_RAW = _get("OLLAMA_RESTRICTED_HOSTS",
                  "TUXBOOK_OLLAMA_RESTRICTED_HOSTS", "")
OLLAMA_RESTRICTED_HOSTS = tuple(
    h.strip() for h in _RESTR_RAW.split(",") if h.strip())

# --- OCR ---
OCR_MIN_CHARS = 120          # weniger Text auf der Seite -> OCR versuchen (wenn Bild vorhanden)
OCR_DPI = 170                # Rasterungsauflösung für Vision-OCR
OCR_MAX_WIDTH = 1400         # Bild vor dem Senden herunter skalieren

# --- Übersetzung ---
CHUNK_TARGET = None          # (reserviert) Übersetzung erfolgt seitenweise
TEMPERATURE = 0.2
MAX_RETRIES = 3
# Token-Marge: Reasoning-Modelle verbrennen Tokens im Nachdenken,
# bevor der eigentliche Inhalt entsteht
TOKEN_MARGIN = 768

# --- Projektordner ---
JOBS_DIR = ROOT / "jobs"
OUT_DIR = ROOT / "out"

# --- Fonts (DejaVu auf diesem System vorhanden) ---
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts"]
FONTS = {
    "regular": "DejaVuSerif.ttf",
    "bold": "DejaVuSerif-Bold.ttf",
    "italic": "DejaVuSerif-Italic.ttf",
    "bolditalic": "DejaVuSerif-BoldItalic.ttf",
}
SANS_FONTS = {
    "regular": "DejaVuSans.ttf",
    "bold": "DejaVuSans-Bold.ttf",
    "italic": "DejaVuSans-Oblique.ttf",
    "bolditalic": "DejaVuSans-BoldOblique.ttf",
}


def font_path(kind: str = "regular", sans: bool = False) -> str | None:
    """Liefert den Pfad einer installierten TTF oder None."""
    table = SANS_FONTS if sans else FONTS
    name = table.get(kind) or table["regular"]
    for d in FONT_DIRS:
        p = Path(d) / name
        if p.exists():
            return str(p)
    return None


LANG_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "nl": "Dutch", "pl": "Polish", "pt": "Portuguese",
    "ru": "Russian", "uk": "Ukrainian", "tr": "Turkish", "da": "Danish",
    "sv": "Swedish", "no": "Norwegian", "fi": "Finnish", "cs": "Czech",
    "el": "Greek", "hu": "Hungarian", "ro": "Romanian", "zh": "Chinese",
    "ja": "Japanese", "ko": "Korean", "ar": "Arabic", "he": "Hebrew",
    "la": "Latin", "auto": "auto-detected source language",
}


def lang_display(code: str) -> str:
    c = (code or "").strip().lower()
    return LANG_NAMES.get(c, code or "unknown")
