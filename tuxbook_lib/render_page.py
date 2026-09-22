"""Seitenmodus: Quelle N -> Ziel N. Originalseite als Vektor kopieren,
Textbereiche weiß überdecken und Übersetzung an derselben Stelle setzen."""
import pymupdf

from . import config
from .extract import PageData

MIN_SHRINK = 0.55
PAD = 2.0  # pt


def _fontfile(kind: str) -> str | None:
    p = config.font_path(kind)
    return p


def _fill_block(tp: "pymupdf.Page", rect: "pymupdf.Rect", text: str, size: float,
                bold: bool, italic: bool, justify: bool) -> float:
    """Text in rect setzen, Schrift verkleinern bis er passt.
    Rückgabe: genutzte Schriftgröße."""
    kind = ("bolditalic" if bold and italic else "bold" if bold
            else "italic" if italic else "regular")
    ff = _fontfile(kind) or _fontfile("regular")
    fname = f"tuxbook-{kind}"
    align = pymupdf.TEXT_ALIGN_JUSTIFY if justify else pymupdf.TEXT_ALIGN_LEFT
    s = size
    min_s = max(size * MIN_SHRINK, 4.5)
    while True:
        r = pymupdf.Rect(rect.x0, rect.y0, rect.x1 + 1, rect.y1 + 1)
        leftover = tp.insert_textbox(
            r, text, fontname=fname, fontfile=ff, fontsize=s,
            align=align, color=(0, 0, 0),
        )
        if leftover >= 0 or s <= min_s:
            return s
        s = max(min_s, s * 0.93)


def _place_flow(tp: "pymupdf.Page", paras: list[str], area: "pymupdf.Rect",
                size: float) -> None:
    """Absätze fließend untereinander in area setzen (für OCR-Seiten im Seitenmodus)."""
    y = area.y0
    for t in paras:
        if y >= area.y1 - size:
            break
        r = pymupdf.Rect(area.x0, y, area.x1, area.y1)
        used = _fill_block(tp, r, t, size, False, False, True)
        # geschätzte Höhe: grob über Zeilenzahl (Zeilenabstand ~1.2 im Textbox-Renderer)
        approx_lines = max(1, int(len(t) * used * 0.5 / max(area.width, 1)) + 1)
        y += approx_lines * used * 1.3 + 4


def render_page_mode(src: "pymupdf.Document", out: "pymupdf.Document",
                     pages: list[PageData], translated: dict[int, list[str]],
                     on_page=None) -> None:
    """Baut das Zielpdf seitenweise auf. translated[pno] = Absätze (Seitenmodus:
    gleiche Anzahl/Reihenfolge wie pd.blocks-Texte; Fluss: Liste von Absätzen)."""
    for pd in pages:
        if on_page:
            on_page(pd.pno)
        tp = out.new_page(width=pd.width, height=pd.height)
        tp.show_pdf_page(tp.rect, src, pd.pno)   # Original als Vektorobjekt

        if pd.ocr_used or (not pd.blocks and pd.paras):
            # OCR-/Bildseite: ganze Seite weiß, Übersetzung fließend setzen
            if translated.get(pd.pno):
                tp.draw_rect(tp.rect, color=None, fill=(1, 1, 1))
                area = pymupdf.Rect(pd.width * 0.12, pd.height * 0.12,
                                    pd.width * 0.88, pd.height * 0.92)
                _place_flow(tp, translated[pd.pno], area, pd.body_size)
            continue

        if not pd.blocks:
            continue  # leere/graphische Seite: nur Original kopieren

        tr = translated.get(pd.pno)
        for bi, b in enumerate(pd.blocks):
            r = pymupdf.Rect(b.bbox.x0 - PAD, b.bbox.y0 - PAD,
                             b.bbox.x1 + PAD, b.bbox.y1 + PAD)
            tp.draw_rect(r, color=None, fill=(1, 1, 1))
            text = tr[bi] if (tr and bi < len(tr)) else b.text
            if not text.strip():
                continue
            justify = b.nlines > 2
            _fill_block(tp, r, text, b.size, b.bold, b.italic, justify)
