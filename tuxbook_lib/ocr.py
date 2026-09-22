"""OCR-Schicht: Tesseract primär, LLM-Vision (Ollama) als Fallback."""
import shutil
import subprocess

from . import config
from .llm import OllamaClient, LLMError

# ISO-639-1 -> Tesseract-Sprachcode
TESS_LANGS = {
    "de": "deu", "en": "eng", "fr": "fra", "es": "spa", "it": "ita",
    "nl": "nld", "pl": "pol", "pt": "por", "ru": "rus", "uk": "ukr",
    "tr": "tur", "da": "dan", "sv": "swe", "no": "nor", "fi": "fin",
    "cs": "ces", "el": "ell", "hu": "hun", "ro": "ron", "zh": "chi_sim",
    "ja": "jpn", "ko": "kor", "ar": "ara", "he": "heb", "la": "lat",
}


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def tesseract_installed_langs() -> set[str]:
    try:
        p = subprocess.run(["tesseract", "--list-langs"],
                           capture_output=True, timeout=15)
        out = (p.stdout or p.stderr).decode("utf-8", "replace")
        return {l.strip() for l in out.splitlines()[1:] if l.strip()}
    except Exception:
        return set()


def ocr_jpeg(jpeg_bytes: bytes, lang_code: str = "en",
             engine: str = "auto",
             ollama: OllamaClient | None = None) -> tuple[str, str]:
    """OCR eines JPEG. Rückgabe: (text, engine).
    engine: auto | tesseract | ollama
    Bei 'auto': Tesseract, wenn vorhanden; sonst Ollama, wenn erreichbar."""
    if engine in ("auto", "tesseract") and tesseract_available():
        want = TESS_LANGS.get((lang_code or "en").lower(), "eng")
        have = tesseract_installed_langs()
        lang = want if want in have else ("eng" if "eng" in have else "")
        if lang:
            try:
                p = subprocess.run(
                    ["tesseract", "stdin", "stdout", "-l", lang, "--psm", "3"],
                    input=jpeg_bytes, capture_output=True, timeout=180)
                text = (p.stdout or b"").decode("utf-8", "replace").strip()
                if text:
                    return text, "tesseract"
            except (subprocess.TimeoutExpired, OSError):
                pass  # auf Fallback fallen

    if engine in ("auto", "ollama") and ollama is not None and ollama.alive():
        try:
            text = ollama.ocr_image(jpeg_bytes).strip()
            if text:
                return text, "ollama"
        except LLMError:
            pass

    return "", "none"
