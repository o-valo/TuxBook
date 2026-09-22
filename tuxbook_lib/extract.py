"""PDF-Extraktion: Textblöcke (Seitenmodus) + Absätze (Flussmodus), OCR-Fallback."""
import re

import pymupdf

# Version der Extraktionslogik — Cache-Einträge mit anderer Version sind ungültig
EXTRACT_VERSION = 4

from . import config
from .llm import OllamaClient, LLMError

# pymupdf span flags
F_BOLD = 2 ** 4
F_ITALIC = 2 ** 1


class Block:
    """Textblock einer Seite mit Position und Schriftinfo (für Seitenmodus)."""
    __slots__ = ("bbox", "text", "size", "bold", "italic", "nlines")

    def __init__(self, bbox, text, size, bold, italic, nlines):
        self.bbox = bbox          # pymupdf.Rect
        self.text = text
        self.size = size
        self.bold = bold
        self.italic = italic
        self.nlines = nlines


class Para:
    """Absatz mit Schriftmetrik (für Flussmodus)."""
    __slots__ = ("text", "size", "bold", "italic", "kind")

    def __init__(self, text, size, bold=False, italic=False, kind="para"):
        self.text = text
        self.size = size
        self.bold = bold
        self.italic = italic
        self.kind = kind  # para | heading | pagenum


class PageData:
    def __init__(self, pno: int, width: float, height: float):
        self.pno = pno
        self.width = width
        self.height = height
        self.blocks: list[Block] = []     # Seitenmodus
        self.paras: list[Para] = []       # Flussmodus / OCR-Text
        self.body_size: float = 10.0
        self.ocr_used: bool = False
        self.is_empty: bool = False


def _join_lines(lines: list[dict]) -> tuple[str, float, bool, bool]:
    """Zeilen eines Blocks mit De-Hyphenation zusammenführen."""
    parts: list[str] = []
    size, bold_chars, ital_chars, total = 0.0, 0, 0, 0
    prev = ""
    for ln in lines:
        line_text = "".join(s["text"] for s in ln["spans"]).strip()
        for s in ln["spans"]:
            n = len(s["text"].strip())
            total += n
            size += s["size"] * n
            if s["flags"] & F_BOLD:
                bold_chars += n
            if s["flags"] & F_ITALIC:
                ital_chars += n
        if not line_text:
            continue
        if parts:
            if prev.endswith("-") and line_text[:1].islower():
                parts[-1] = parts[-1][:-1]          # De-Hyphenation
                parts[-1] += line_text
            else:
                parts[-1] += " " + line_text
        else:
            parts.append(line_text)
        prev = line_text
    text = parts[0] if parts else ""
    n = max(total, 1)
    return text, (size / n) if total else 10.0, bold_chars > n / 2, ital_chars > n / 2


def _dominant_body_size(sizes: list[float]) -> float:
    if not sizes:
        return 10.0
    sizes = sorted(round(s * 2) / 2 for s in sizes)
    return sizes[len(sizes) // 2]


def _merge_line_blocks(blocks: list[Block]) -> list[Block]:
    """Bücher mit großem Zeilenabstand: PyMuPDF macht aus jeder Zeile einen
    eigenen Block. Zusammenführen, wenn linksbündig ausgerichtet, gleiche
    Schriftgröße und vertikaler Abstand ~ eine Zeile. Neue Absätze (mit
    Erstzeilen-Einzug, andere x-Position) brechen die Kette."""
    if len(blocks) < 2:
        return blocks
    out: list[Block] = []
    for b in blocks:
        if out:
            a = out[-1]
            gap = b.bbox.y0 - a.bbox.y1
            same_x = abs(b.bbox.x0 - a.bbox.x0) < 5
            # eingerückte Erstzeile: Block beginnt weiter rechts als die
            # Folgzeilen am linken Rand
            indent_start = a.nlines == 1 and b.bbox.x0 < a.bbox.x0 - 5
            same_size = abs(b.size - a.size) < 0.8
            if same_size and -1 <= gap < a.size * 1.9 and (same_x or indent_start):
                if a.text.endswith("-") and b.text[:1].islower():
                    a.text = a.text[:-1] + b.text          # De-Hyphenation
                else:
                    a.text = a.text + " " + b.text
                a.bbox = pymupdf.Rect(min(a.bbox.x0, b.bbox.x0),
                                      min(a.bbox.y0, b.bbox.y0),
                                      max(a.bbox.x1, b.bbox.x1),
                                      max(a.bbox.y1, b.bbox.y1))
                a.nlines += 1
                continue
        out.append(b)
    return out


def extract_page(src: "pymupdf.Document", pno: int,
                 text_source: str = "auto") -> PageData:
    """text_source: 'auto' = eingebetteter Text, OCR-Marker nur wenn leer;
    'embedded' = nie OCR; 'ocr' = eingebetteten Text ignorieren, immer
    OCR-Marker setzen (Rasterisierung übernimmt die OCR-Schicht)."""
    page = src[pno]
    pd = PageData(pno, page.rect.width, page.rect.height)
    d = page.get_text("dict")
    sizes: list[float] = []
    has_image = any(b.get("type") == 1 for b in d.get("blocks", []))

    skip_embedded = (text_source == "ocr")
    if not skip_embedded:
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            lines = b.get("lines", [])
            if not lines:
                continue
            text, size, bold, italic = _join_lines(lines)
            if not text.strip():
                continue
            nlines = len(lines)
            sizes.extend(s["size"] for ln in lines
                         for s in ln["spans"] if s["text"].strip())
            pd.blocks.append(Block(pymupdf.Rect(b["bbox"]), text, size,
                                   bold, italic, nlines))

    pd.body_size = _dominant_body_size(sizes) if sizes else 10.0
    total_chars = sum(len(b.text) for b in pd.blocks)

    # Zeilenfragmente zu Absätzen zusammenführen
    if len(pd.blocks) > 1:
        pd.blocks = _merge_line_blocks(pd.blocks)
        total_chars = sum(len(b.text) for b in pd.blocks)

    # Scan-Artefakte bereinigen (deutsches+englisches Set)
    for b in pd.blocks:
        b.text = clean_artifacts(b.text)

    # Deko-/Artefakt-Zeilen verwerfen
    pd.blocks = [b for b in pd.blocks if not is_noise(b.text)]

    # Inhaltsverzeichnis-Seiten: Fragmente zu sauberen Einträgen fusionieren
    if pd.blocks:
        pd.blocks = merge_toc(pd.blocks)

    if not pd.blocks:
        pd.is_empty = not has_image

    # ---- Absätze für Flussmodus (aus Blöcken) ------------------------------
    if pd.blocks:
        for b in pd.blocks:
            kind = "para"
            short = len(b.text) < 70
            if b.size >= pd.body_size * 1.22 or (short and b.bold and b.size >= pd.body_size * 1.08):
                kind = "heading"
            elif b.nlines == 1 and len(b.text) <= 6 and b.size < pd.body_size:
                kind = "pagenum"
            pd.paras.append(Para(b.text, b.size, b.bold, b.italic, kind))

    # ---- OCR-Marker nach text_source --------------------------------------
    if text_source == "ocr":
        # embedded ignoriert: immer OCR-Anfrage (Rasterisierung + OCR in CLI)
        pd.ocr_used = True
        pd.paras = []
        pd.blocks = []
    elif text_source == "embedded":
        pd.ocr_used = False
    else:  # auto
        if total_chars < config.OCR_MIN_CHARS and has_image:
            pd.ocr_used = True  # Marker; Rasterisierung + OCR in der CLI
    return pd


def page_to_jpeg(src: "pymupdf.Document", pno: int, dpi: int = config.OCR_DPI) -> bytes:
    """Seite als (skaliertes) JPEG für Vision-OCR rasterisieren."""
    page = src[pno]
    pix = page.get_pixmap(dpi=dpi)
    if pix.width > config.OCR_MAX_WIDTH:
        pix = page.get_pixmap(dpi=max(72, int(dpi * config.OCR_MAX_WIDTH / pix.width)))
    return pix.tobytes("jpeg", jpg_quality=72)


def run_ocr(src: "pymupdf.Document", pd: PageData, ocr: OllamaClient) -> None:
    """OCR für eine Seite ausführen und Absätze füllen."""
    jpeg = page_to_jpeg(src, pd.pno)
    text = ocr.ocr_image(jpeg)
    text = text.strip()
    pd.ocr_used = True
    pd.paras = []
    if not text:
        pd.is_empty = True
        return
    for chunk in re_split_paras(text):
        t = chunk.strip().replace("\n", " ").strip()
        if t:
            pd.paras.append(Para(t, pd.body_size, False, False, "para"))
    pd.blocks = []


def re_split_paras(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


# ---- Scan-Artefakt-Bereinigung --------------------------------------------
_FIXES = [
    (re.compile(r"\b[Iil](?=\d)"), "1"),        # i94o / I94o / l94o -> 1940
    (re.compile(r"(?<=\d)[oO]\b"), "0"),        # 19O / 19o -> 190
    (re.compile(r"(\w)jf(\w)"), r"\1fl\2"),     # Mayjfower -> Mayflower (jf=fl-Fehllesung)
    (re.compile(r"([a-zA-Z])\s*/\s*([A-Z]{2,})"), r"\1/\2"),  # V /RG -> V/RG
    (re.compile(r"\s+/\s+"), "/"),              # zerdehnte Schrägstriche
    (re.compile(r"\s+([,.;:!?])"), r"\1"),      # Leerzeichen vor Satzzeichen
    (re.compile(r"([,.;:!?])(?=[a-z])"), r"\1 "),  # fehlendes Leerzeichen danach
    (re.compile(r"\s{2,}"), " "),               # Mehrfach-Leerzeichen
    (re.compile(r"\s+([»”'\"])"), r"\1"),      # Leerzeichen vor Schluss-Anführung
]
_NOISE_CHARS = " \t_»—–-•·.'\",;:=+*~^°|#<>"
_NOISE_RE = re.compile("^[" + re.escape(_NOISE_CHARS) + "]*$")


_LEAD_NOISE = re.compile(r"^[_»<,;:=+*~^|#\s]+")


def clean_artifacts(t: str) -> str:
    """OCR-/Scan-Artefakte in extrahiertem Text bereinigen."""
    t = t.strip()
    if not t:
        return t
    # führende Deko-Artefakte ('__, _ _ Hergestellt...' -> 'Hergestellt...')
    # — Bindestriche bleiben bewusst unangetastet (Dialog-Striche)
    t = _LEAD_NOISE.sub("", t).strip()
    for rx, repl in _FIXES:
        t = rx.sub(repl, t)
    return t


def is_noise(t: str) -> bool:
    """Wahr für reine Deko-/Artefakt-Zeilen ('__ , _ _', '»— <', '·····')."""
    return bool(_NOISE_RE.match(t.strip()))


# ---- Struktur: Inhaltsverzeichnis-Fusion ----------------------------------
_DOTTED = re.compile(r"[. •·]{3,}\s*([0-9]{1,4})?\s*$")
_TRAILNUM = re.compile(r"\s*(?:[.•·]\s*)*(\d{1,4})\s*$")
_TOC_NUM = re.compile(r"^§?\s*[0-9IVXivx]+(?:\s*[0-9IVXivx]+)?[.;\-]?\s*$")
_TOC_HEADERS = {"SEITE", "PAGE", "CONTENTS", "INHALT", "INHALTSVERZEICHNIS"}
_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
          "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
          "xi": "11", "xii": "12"}


def _norm_toc_num(t: str) -> str:
    """'§ I.' / 'I 6.' / '§10;' -> '1' / '6' / '10'."""
    t = t.strip().lstrip("§").strip().rstrip(".,;:-").strip()
    t = re.sub(r"^[iI]\s+(?=\d)", "", t)          # 'I 6' -> '6'
    key = t.lower().replace(" ", "")
    if key in _ROMAN:
        return _ROMAN[key]
    m = re.search(r"\d+", t)
    return m.group(0) if m else t


def _is_toc_page(blocks: list[Block]) -> bool:
    if len(blocks) < 6:
        return False
    hits = 0
    for b in blocks:
        t = b.text.strip()
        if t in _TOC_HEADERS or _DOTTED.search(t) or _TRAILNUM.search(t):
            hits += 1
    return hits >= max(5, len(blocks) // 3)


def merge_toc(blocks: list[Block]) -> list[Block]:
    """Inhaltsverzeichnis-Seiten: zerschnittene Einträge ('§ I.' / Titel /
    'SEITE' / '• 9') zu sauberen Zeilen '§1. Titel .... 9' fusionieren.
    Zweipassig: sammeln, dann emittieren — dadurch funktionieren beide
    Layouts (Zahl vor Titel, Seitenzahl-Spalte nach dem Titel)."""
    if not _is_toc_page(blocks):
        return blocks
    entries: list[dict] = []   # {num, raw, title, page}
    for b in blocks:
        t = b.text.strip()
        if is_noise(t) or t in _TOC_HEADERS:
            continue
        if _TOC_NUM.match(t) and len(t) <= 8:
            entries.append({"num": _norm_toc_num(t), "raw": t,
                            "title": None, "page": None})
            continue
        if re.fullmatch(r"[.•·\s]*\d{1,4}", t):
            # freistehende Seitenzahl -> an letzten Eintrag ohne Seite hängen
            for e in reversed(entries):
                if e["page"] is None:
                    e["page"] = re.search(r"\d+", t).group(0)
                    break
            continue
        title = _DOTTED.sub("", t).strip().rstrip(".").strip()
        if not title:
            continue
        m = _TRAILNUM.search(t)
        page = m.group(1) if (m and _DOTTED.search(t)) else None
        if entries and entries[-1]["title"] is None:
            entries[-1]["title"] = title
            if page:
                entries[-1]["page"] = page
        else:
            entries.append({"num": None, "title": title, "page": page})

    # Sequenz-Fix: '§ II' nach '§ 10' ist 11, nicht römisch 2
    last_num = 0
    for e in entries:
        if e["num"] is None:
            continue
        try:
            v = int(e["num"])
        except ValueError:
            continue
        if v < last_num:
            raw = re.sub(r"[^IiVvXx]", "", e.get("raw", ""))
            if raw and re.fullmatch(r"[Ii]+", raw):
                v = int("1" * len(raw))     # II -> 11, III -> 111 etc.
        e["num"] = str(v)
        last_num = max(last_num, v)

    new: list[Block] = []
    for e in entries:
        if not e["title"]:
            continue  # nackte §-Nummer ohne Titel verwerfen
        text = (f"§{e['num']}. " if e["num"] else "") + e["title"]
        if e["page"]:
            text += f" .... {e['page']}"
        new.append(Block(pymupdf.Rect(0, 0, 1, 1), text, 12.0, False, False, 1))
    return new if len(new) >= 3 else blocks


# ---- Satz-Grenzen & Stitching über Seitengrenzen --------------------------
_TERM_END = tuple('.!?…:;)»”\'"')


def ends_sentence(t: str) -> bool:
    """Wahr, wenn der Text mit Satz-Interval-Punktuation endet."""
    t = t.rstrip()
    return bool(t) and t.endswith(_TERM_END)


def stitch_paragraphs(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Fügt Absätze, die an Seitengrenzen mitten im Satz enden/beginnen,
    zu einem Absatz zusammen. items: (kind, text), kind = 'para'/'headN'."""
    out: list[tuple[str, str]] = []
    for kind, text in items:
        if (out and out[-1][0] == "para" and kind == "para"
                and not ends_sentence(out[-1][1]) and text[:1].islower()):
            out[-1] = ("para", out[-1][1].rstrip() + " " + text)
        else:
            out.append((kind, text))
    return out
