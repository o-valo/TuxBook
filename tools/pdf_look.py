"""Visuelle PDF-Prüfung mit einem Ollama-Vision-Modell.

Rendert Seiten eines PDFs als Bilder und lässt ein Vision-Modell das
Layout bewerten: Sauberkeit, Artefakte, Lesbarkeit, gemischte Sprachen.

Aufruf:
  python3 tools/pdf_look.py <pdf> --pages 1,4,10
  python3 tools/pdf_look.py <pdf> --pages 2 --question "Wirkt die Titelseite aufgeräumt?"
"""
import argparse
import base64
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf
import requests
from PIL import Image

from tuxbook_lib import config


DEFAULT_PROMPT = """You are a print-shop quality inspector looking at one page \
of a translated book (German). Judge ONLY what you see:

1. Is the text cleanly typeset (aligned margins, consistent line spacing, no \
overlapping or double-printed text)?
2. Any visual artifacts: stray marks, scan noise, half-erased old text, \
garbled glyphs?
3. Is the page readable for a human? Any layout problems (cramped blocks, \
text running off the page, weird gaps)?
4. Does any text in a language other than German appear? Quote it if so.

Answer in German, compact, as bullet points. End with a verdict line:
"URTEIL: sauber" or "URTEIL: Problem — <one sentence>"."""


def page_to_jpeg_bytes(doc: "pymupdf.Document", pno: int, dpi: int = 150,
                       max_width: int = 1400) -> bytes:
    pix = doc[pno].get_pixmap(dpi=dpi)
    if pix.width > max_width:
        pix = doc[pno].get_pixmap(dpi=max(72, int(dpi * max_width / pix.width)))
    return pix.tobytes("jpeg", jpg_quality=80)


def ask_gemma4(url: str, model: str, jpeg: bytes, prompt: str,
               timeout: int = 600) -> str:
    b64 = base64.b64encode(jpeg).decode()
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [b64],
        }],
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }
    r = requests.post(f"{url.rstrip('/')}/api/chat", json=payload,
                      timeout=timeout)
    r.raise_for_status()
    content = r.json().get("message", {}).get("content") or ""
    # <think>-Blöcke mancher Modelle entfernen
    import re
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", default="1", help="z.B. '1,4,10' (1-basiert)")
    ap.add_argument("--url", default=config.OLLAMA_URL)
    ap.add_argument("--model", default=config.OLLAMA_VISION_MODEL)
    ap.add_argument("--question", default=None,
                    help="eigene Frage statt Standard-Inspektions-Prompt")
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    doc = pymupdf.open(Path(args.pdf).expanduser().resolve())
    pages = []
    for part in args.pages.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        elif part:
            pages.append(int(part))

    prompt = DEFAULT_PROMPT if not args.question else (
        f"{args.question}\n\nAntworte in Deutsch, kompakt, mit Urteilszeile "
        "'URTEIL: ...' am Ende.")

    for p in pages:
        if not (1 <= p <= doc.page_count):
            print(f"--- S.{p}: existiert nicht (1-{doc.page_count}) ---\n")
            continue
        jpeg = page_to_jpeg_bytes(doc, p - 1, dpi=args.dpi)
        print(f"=== S.{p} ({len(jpeg)//1024} KB -> {args.model}) ===")
        t0 = time.time()
        try:
            answer = ask_gemma4(args.url, args.model, jpeg, prompt)
            print(answer)
            print(f"[{time.time()-t0:.0f}s]\n")
        except Exception as e:
            print(f"FEHLER: {e}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
