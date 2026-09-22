"""md2pdf: setzt ein Markdown (Output des tuxbook-MD-Exports) als Buch-PDF neu.

Das Markdown ist die korrigierbare Quelle — der Mensch kann Überschriften
verschieben, Bilder einfügen/entfernen, Tippfehler fixen — und aus genau
diesem Markdown entsteht ein frisch gesetztes PDF:

  - A4, DejaVu-Serif (falls installiert), Blocksatz, Absatzabstand
  - Titelblatt aus dem H1-Titel (Datei ohne H1: Dateiname als Titel)
  - H2 = Kapitel → beginnt auf neuer Seite; H3 = Untertitel
  - Bilder: passend skaliert, zentriert, nummeriert („Abbildung n")
  - TOC-Zeilen („Titel .... 12") als eigene Zeilen: Titel fett, Zahl rechts
  - Seitenzahlen zentriert unten (Titelblatt ohne)
  - Speicherarm & schnell: ein TextWriter pro Seite (ein Schreibvorgang),
    Absätze fließen seitenweise weiter — nie das ganze Buch im RAM.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import pymupdf

PAGE_W, PAGE_H = pymupdf.paper_size("a4")
MARGIN = 68.0
BODY = 11.0
LEAD = 16.0
H1 = 24.0
H2 = 17.0
H3 = 13.5
GAP = 7.0
COL_TXT = (0.13, 0.13, 0.13)
COL_DIM = (0.45, 0.45, 0.45)

_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman_val(s: str) -> int | None:
    s = s.lower()
    if not s or any(c not in _ROMAN for c in s):
        return None
    total = 0
    for i, c in enumerate(s):
        v = _ROMAN[c]
        if i + 1 < len(s) and _ROMAN[s[i + 1]] > v:
            total -= v
        else:
            total += v
    return total if total > 1 else None


# --------------------------------------------------------------------- Fonts
def _load_fonts() -> dict[str, pymupdf.Font]:
    """DejaVu Serif (buch-typisch) wenn vorhanden, sonst Helvetica."""
    fonts: dict[str, pymupdf.Font] = {}
    cands = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "serif"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "serif-b"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf", "serif-i"),
    ]
    for path, alias in cands:
        if Path(path).is_file():
            try:
                fonts[alias] = pymupdf.Font(fontfile=path)
            except Exception:
                pass
    if "serif" not in fonts:  # Fallback: eingebaute Basis-Fonts
        fonts = {"serif": pymupdf.Font("helv"),
                 "serif-b": pymupdf.Font("hebo"),
                 "serif-i": pymupdf.Font("heit")}
    fonts.setdefault("serif-b", fonts["serif"])
    fonts.setdefault("serif-i", fonts["serif"])
    return fonts


# ------------------------------------------------------------------- Parsing
def _img_refs(text: str) -> list[str]:
    return re.findall(r"!\[[^\]]*\]\(<([^>]+)>\)", text)


def _only_images(line: str) -> bool:
    return re.sub(r"!\[[^\]]*\]\(<[^>]+>\)", "", line).strip() == ""


def parse_md(md_path: Path) -> tuple[dict, list[dict]]:
    """Markdown → (meta, blocks). block = {"t", "text", "path"?, "page"?}."""
    meta: dict = {}
    blocks: list[dict] = []
    h1_done = False

    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        imgs = _img_refs(line)
        if imgs:
            for ref in imgs:
                blocks.append({"t": "img", "path": str(md_path.parent / ref),
                               "text": ""})
            if _only_images(line):
                continue  # reine Bildzeile — Blöcke stehen schon

        s = re.sub(r"\s+", " ", line).strip()
        if not s:
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            level, txt = len(m.group(1)), m.group(2).strip()
            if level == 1 and not h1_done:
                meta["title"] = txt
                h1_done = True
            else:
                blocks.append({"t": f"h{min(level, 3)}", "text": txt})
            continue

        # Trennzeilen / einsame Ellipsen verwerfen
        if re.fullmatch(r"[-*_•─—~]{3,}", s) or s in {"…", "..."}:
            continue

        # TOC-Zeile: „Titel .... 12" — „§XII." (römisch) wäre Kapitel, nicht TOC.
        # Zählpunkt im Titel („§1. Das Ende…") darf nicht mitgezählt werden:
        # erst die Führungspunkt-Gruppe vor der Zahl abschneiden.
        # Toleranz-Variante: „§9. Titel. 122" (LLM hat Punkte geschluckt) —
        # §-Präfix + kurze Zeile + Schlusszahl reicht als TOC-Kennzeichen.
        mt = re.match(r"^(.{1,90}?)\s*\.{3,}\s*(\d{1,4})\s*$", s)
        if mt:
            txt = mt.group(1).strip()
            lead = re.sub(r"\.{3,}$", "", txt).strip()
            first = lead.split(".")[0].strip().lstrip("§").strip()
            if not _roman_val(first):
                blocks.append({"t": "toc", "text": lead, "page": mt.group(2)})
                continue
        ms = re.match(r"^(§\d{1,3}\.\s*.{1,80}?)\.?\s+(\d{1,4})$", s)
        if ms and len(s) < 110:
            blocks.append({"t": "toc", "text": ms.group(1).strip(),
                           "page": ms.group(2)})
            continue

        blocks.append({"t": "p", "text": html.unescape(s)})

    if not h1_done:
        meta["title"] = md_path.stem.replace("_", " ").replace("-", " ").title()
    return meta, blocks


# -------------------------------------------------------------------- Render
class _Page:
    """Eine Ausgabeseite mit Y-Cursor und je einem TextWriter für Haupt-
    und gedämpften Text (je ein write_text pro Seite → schnell)."""

    def __init__(self, doc: pymupdf.Document,
                 fonts: dict[str, pymupdf.Font]):
        self.pdf = doc.new_page(width=PAGE_W, height=PAGE_H)
        self.fonts = fonts
        self.tw = pymupdf.TextWriter(self.pdf.rect)        # Haupttext
        self.tw_dim = pymupdf.TextWriter(self.pdf.rect)    # gedämpft (Kapt./Zahlen)
        self._n = 0
        self._n_dim = 0
        self.y = MARGIN

    # -- Basics ------------------------------------------------------------
    def _w(self, text: str, size: float, font: str) -> float:
        return self.fonts[font].text_length(text, fontsize=size)

    def _fits(self, needed: float) -> bool:
        return self.y + needed <= PAGE_H - MARGIN + 2

    def _line(self, words: list[str], size: float, font: str, x0: float,
              extra: float = 0.0, dim: bool = False):
        f = self.fonts[font]
        tw = self.tw_dim if dim else self.tw
        if not words:
            return
        if extra <= 0.0:
            # ein Append für die ganze Zeile → echte Leerzeichen-Glyphen
            tw.append(pymupdf.Point(x0, self.y), " ".join(words),
                      font=f, fontsize=size)
        else:
            # Blocksatz: Wort für Wort, gedehnte Zwischenräume
            x = x0
            for i, w in enumerate(words):
                _rect, last = tw.append(pymupdf.Point(x, self.y), w,
                                        font=f, fontsize=size)
                x = last.x
                if i < len(words) - 1:
                    _rect, last = tw.append(pymupdf.Point(x, self.y), " ",
                                            font=f, fontsize=size)
                    x = last.x + extra
        if dim:
            self._n_dim += 1
        else:
            self._n += 1

    def flush(self) -> None:
        if self._n:
            self.tw.write_text(self.pdf, color=COL_TXT)
        if self._n_dim:
            self.tw_dim.write_text(self.pdf, color=COL_DIM)
        self._n = self._n_dim = 0

    # -- Blocksatz-Absatz (fließt über Seiten) -------------------------------
    def paragraph(self, text: str, size=BODY, lead=LEAD, font="serif",
                  align="justify") -> str:
        """Setzt so viele Zeilen wie passen; Rückgabe = Resttext ('' = fertig).
        Liefert den Text unverändert zurück, wenn nicht einmal eine Zeile passt
        (Aufrufer macht dann einen Seitenwechsel)."""
        width = PAGE_W - 2 * MARGIN
        words = text.split(" ")
        space = self._w(" ", size, font)
        consumed = 0
        while consumed < len(words):
            if not self._fits(lead):
                return " ".join(words[consumed:])
            # eine Zeile füllen
            cur: list[str] = []
            cur_w = 0.0
            i = consumed
            while i < len(words):
                ww = self._w(words[i], size, font)
                if cur and cur_w + space + ww > width:
                    break
                cur_w = ww if not cur else cur_w + space + ww
                cur.append(words[i])
                i += 1
            n = len(cur)
            last = i >= len(words)
            extra = 0.0
            if align == "justify" and not last and n > 1:
                words_w = sum(self._w(w, size, font) for w in cur)
                natural = words_w + (n - 1) * space
                extra = max(0.0, (width - natural) / (n - 1))
            self._line(cur, size, font, MARGIN, extra)
            consumed = i
            self.y += lead
        return ""

    # -- Überschriften -------------------------------------------------------
    def heading(self, text: str, size: float, lead=None, gap_after=GAP,
                centered=False) -> None:
        width = PAGE_W - 2 * MARGIN
        lead = lead or size * 1.35
        words = text.split(" ")
        lines: list[list[str]] = []
        cur: list[str] = []
        cur_w = 0.0
        for w in words:
            ww = self._w(w, size, "serif-b")
            if cur and cur_w + self._w(" ", size, "serif-b") + ww > width:
                lines.append(cur)
                cur, cur_w = [w], ww
            else:
                cur_w = (ww if not cur
                         else cur_w + self._w(" ", size, "serif-b") + ww)
                cur.append(w)
        if cur:
            lines.append(cur)
        sp_b = self._w(" ", size, "serif-b")
        for ws in lines:
            x0 = MARGIN
            if centered:
                lw = sum(self._w(w, size, "serif-b") for w in ws) \
                    + (len(ws) - 1) * sp_b
                x0 = MARGIN + max(0.0, (width - lw) / 2)
            self._line(ws, size, "serif-b", x0, 0.0)
            self.y += lead
        self.y += gap_after

    def toc_line(self, text: str, page_no: str) -> bool:
        need = LEAD + 4
        if not self._fits(need):
            return False
        size = 11.5
        while self._w(text, size, "serif-b") > PAGE_W - 2 * MARGIN - 34 and \
                len(text) > 8:
            text = text[:-2].rstrip()
        self._line([text], size, "serif-b", MARGIN, 0.0)
        num_w = self._w(page_no, 10, "serif")
        x_num = PAGE_W - MARGIN - num_w
        self.tw_dim.append(pymupdf.Point(x_num, self.y), page_no,
                           font=self.fonts["serif"], fontsize=10)
        self._n_dim += 1
        self.y += need
        return True

    def center_line(self, text: str, size: float, font="serif",
                    dim=True) -> None:
        """Einzeilig, horizontal zentriert (Titelblatt, Bildunterschriften)."""
        f = self.fonts[font]
        w = f.text_length(text, fontsize=size)
        tw = self.tw_dim if dim else self.tw
        tw.append(pymupdf.Point((PAGE_W - w) / 2, self.y), text,
                  font=f, fontsize=size)
        if dim:
            self._n_dim += 1
        else:
            self._n += 1
        self.y += size * 1.5

    # -- Bild -------------------------------------------------------------
    def image(self, path: str, number: int) -> tuple[bool, bool]:
        """(platziert?, neue Seite nötig?)"""
        try:
            img = pymupdf.Pixmap(path)
            iw, ih = img.width, img.height
            img = None
        except Exception:
            return True, False      # fehlendes Bild: still überspringen
        if iw <= 0 or ih <= 0:
            return True, False
        max_w = PAGE_W - 2 * MARGIN
        max_h = PAGE_H - 2 * MARGIN - 110
        scale = min(max_w / iw, max_h / ih, 1.6)
        w, h = iw * scale, ih * scale
        need = h + 26
        if not self._fits(need):
            if self.y > MARGIN + 10:
                return False, True      # neue Seite, dann erneut versuchen
            scale *= max_h / h          # passt nicht mal leer → verkleinern
            w, h = iw * scale, ih * scale
        rect = pymupdf.Rect(PAGE_W / 2 - w / 2, self.y,
                            PAGE_W / 2 + w / 2, self.y + h)
        try:
            self.pdf.insert_image(rect, filename=path)
        except Exception:
            return True, False
        self.y += h + 4
        cap = f"Abbildung {number}"
        cw = self._w(cap, 9, "serif")
        self.tw_dim.append(pymupdf.Point(PAGE_W / 2 - cw / 2, self.y), cap,
                           font=self.fonts["serif"], fontsize=9)
        self._n_dim += 1
        self.y += 20
        return True, False


# --------------------------------------------------------------------- Main
def _merge_continuations(blocks: list[dict]) -> list[dict]:
    """Absätze, die im MD mit „…“ über die Quellseitengrenze reichen, wieder
    zu einem Absatz verbinden (das Rendering bricht selbst sauber um).
    Ein abschließendes „…“ ohne Fortsetzung wird entfernt."""
    out: list[dict] = []
    for b in blocks:
        prev = out[-1] if out else None
        prev_open = (prev is not None and prev["t"] == "p"
                     and prev["text"].endswith("…"))
        if prev_open and b["t"] == "p":
            # Fortsetzung: Marker des Vorgängers durch echten Text ersetzen;
            # b behält sein eigenes End-Marker-Schicksal für die nächste Runde
            prev["text"] = prev["text"][:-1].rstrip() + " " + b["text"]
            continue
        if prev_open:
            # „…“ ohne Fortsetzung (z. B. Scope-Ende vor Überschrift)
            prev["text"] = prev["text"][:-1].rstrip()
        out.append(b)
    if out and out[-1]["t"] == "p" and out[-1]["text"].endswith("…"):
        out[-1]["text"] = out[-1]["text"][:-1].rstrip()
    return out


def md_to_pdf(md_path: Path, out_pdf: Path, title: str | None = None) -> Path:
    """Setzt ein Markdown als Buch-PDF neu. Rückgabe: Ausgabepfad."""
    meta, blocks = parse_md(Path(md_path))
    blocks = _merge_continuations(blocks)
    book_title = title or meta.get("title") or Path(md_path).stem
    fonts = _load_fonts()

    doc = pymupdf.open()
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    # ---- Titelblatt ----
    pg = _Page(doc, fonts)
    pg.y = PAGE_H * 0.32
    pg.heading(book_title, H1, lead=H1 * 1.35, gap_after=10, centered=True)
    pg.flush()

    # ---- Inhalt (erste Body-Seite entsteht lazy → kein Leerbatt vor §1) ----
    fig_no = 0
    body: _Page | None = None

    def new_body():
        nonlocal body
        if body is not None:
            body.flush()
        body = _Page(doc, fonts)

    i = 0
    while i < len(blocks):
        b = blocks[i]
        t = b["t"]

        if t == "h2":
            # Kapitel → immer neue Seite (wie in einem echten Buch). Im MD
            # gibt es keine Frontmatter-Pseudo-Überschriften mehr — der
            # MD-Export stuft Titelseiten-Zeilen als Fließtext ein.
            new_body()
            body.heading(b["text"], H2, lead=H2 * 1.4, gap_after=14)
            i += 1
            continue

        if t == "h3":
            if body is None:
                new_body()
            elif not body._fits(H3 * 1.4 + GAP + LEAD):
                new_body()
            body.heading(b["text"], H3, gap_after=GAP)
            i += 1
            continue

        if t == "toc":
            if body is None:
                new_body()
            if not body.toc_line(b["text"], b["page"]):
                new_body()
                body.toc_line(b["text"], b["page"])
            i += 1
            continue

        if t == "img":
            fig_no += 1
            if body is None:
                new_body()
            ok, brk = body.image(b["path"], fig_no)
            if not ok and brk:
                new_body()
                body.image(b["path"], fig_no)
            i += 1
            continue

        # Absatz (Fließtext, fließt über Seitengrenzen)
        if body is None:
            new_body()
        rest = body.paragraph(b["text"])
        while rest:
            new_body()
            rest = body.paragraph(rest)
        i += 1

    if body is not None:
        body.flush()

    # ---- Seitenzahlen (Titelblatt ausgenommen) ----
    for pno in range(1, doc.page_count):
        num = str(pno + 1)
        w = fonts["serif"].text_length(num, fontsize=9)
        doc[pno].insert_text((PAGE_W / 2 - w / 2, PAGE_H - 36), num,
                             fontsize=9, fontname="helv", color=COL_DIM)

    doc.save(str(out_pdf), garbage=3, deflate=True)
    doc.close()
    return out_pdf
