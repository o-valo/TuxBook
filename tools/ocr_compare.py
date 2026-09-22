"""OCR-Qualitätsvergleich: Tesseract vs. Ollama-Vision auf einer degradierten
Scan-Seite. Erzeugt eine schlechte Nachbildung (niedrige dpi, Rauschen,
Rotation) und misst Text-Ähnlichkeit + Zeit je Engine.

Aufruf:  python3 tools/ocr_compare.py <pdf> --page N [--ollama-url URL]
"""
import argparse
import difflib
import io
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf
from PIL import Image, ImageFilter
import random

from tuxbook_lib import config
from tuxbook_lib.extract import page_to_jpeg
from tuxbook_lib.ocr import ocr_jpeg, tesseract_available
from tuxbook_lib.llm import OllamaClient


def make_degraded_jpeg(src_pdf: Path, pno: int, dpi: int = 96,
                       angle: float = 1.2, noise: float = 14) -> bytes:
    """Seite rasterisieren, drehen, verrauschen -> JPEG (schlechter Scan)."""
    doc = pymupdf.open(src_pdf)
    pix = doc[pno].get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    img = img.rotate(angle, expand=True, fillcolor=255,
                     resample=Image.BICUBIC)
    px = img.load()
    rnd = random.Random(42)
    w, h = img.size
    for _ in range(int(w * h * 0.02)):
        x, y = rnd.randrange(w), rnd.randrange(h)
        v = px[x, y] + rnd.randint(-noise, noise)
        px[x, y] = max(0, min(255, v))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=62)
    return buf.getvalue()


def norm(t: str) -> str:
    t = t.lower()
    t = re.sub(r"[^a-zäöüß\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def score(text: str, reference: str) -> float:
    """Wortbasierte Ähnlichkeit (0..1) gegen den Originaltext."""
    sm = difflib.SequenceMatcher(None, norm(text), norm(reference))
    return sm.ratio()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, default=3)
    ap.add_argument("--ollama-url", default=config.OLLAMA_URL)
    ap.add_argument("--skip-ollama", action="store_true")
    args = ap.parse_args()

    src_pdf = Path(args.pdf).expanduser().resolve()
    pno = args.page - 1
    doc = pymupdf.open(src_pdf)
    reference = doc[pno].get_text()
    doc.close()

    print(f"Degradiere Seite {args.page} (96 dpi, +1.2° gedreht, Rauschen, "
          f"Gauss-Blur, JPEG q62) …")
    jpeg = make_degraded_jpeg(src_pdf, pno)
    print(f"Degradiertes JPEG: {len(jpeg)//1024} KB\n")

    results = []
    if tesseract_available():
        t0 = time.time()
        text, eng = ocr_jpeg(jpeg, "en", "tesseract", None)
        results.append(("Tesseract", text, time.time() - t0))
    if not args.skip_ollama:
        client = OllamaClient(url=args.ollama_url)
        if client.alive():
            t0 = time.time()
            text, eng = ocr_jpeg(jpeg, "en", "ollama", client)
            results.append((f"Ollama ({client.model})", text, time.time() - t0))
        else:
            print(f"Ollama an {args.ollama_url} nicht erreichbar — übersprungen")

    print(f"{'Engine':34s} {'Zeit':>8s} {'Ähnlichkeit':>12s}")
    print("-" * 58)
    for name, text, dt in results:
        s = score(text, reference)
        print(f"{name:34s} {dt:6.1f}s {s:11.1%}")
    print()
    for name, text, _ in results:
        print(f"--- {name} (erste 300 Zeichen) ---")
        print(text[:300] or "(nichts erkannt)")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
