"""Flussmodus: Übersetzung als neu gesetztes Buch (ReportLab, A4).

Speicherarm: bekommt keine PageData-Objekte, sondern leichte Tupel
items = [(pno, body_size, [(kind, text, size), ...])] — dadurch auch für
1000-Seiten-Bücher geeignet.
"""
import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image

from . import config
from .extract import ends_sentence


def _uninline(t: str) -> str:
    """ReportLab-Tags für die Satzgrenzen-Prüfung entfernen."""
    return t.replace("<b>", "").replace("</b>", "") \
            .replace("<i>", "").replace("</i>", "") \
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

_REGISTERED = False
_FAMILY = "Helvetica"


def _register_fonts():
    """Registriert die DejaVu-Schriften (idempotent) und liefert den
    Familiennamen zurück — auch bei wiederholten Aufrufen."""
    global _REGISTERED, _FAMILY
    if _REGISTERED:
        return _FAMILY
    reg = config.font_path("regular")
    bold = config.font_path("bold")
    ital = config.font_path("italic")
    bi = config.font_path("bolditalic")
    fam = "DejaVuSerif"
    if reg:
        pdfmetrics.registerFont(TTFont(fam, reg))
        pdfmetrics.registerFont(TTFont(fam + "-Bold", bold or reg))
        pdfmetrics.registerFont(TTFont(fam + "-Italic", ital or reg))
        pdfmetrics.registerFont(TTFont(fam + "-BoldItalic", bi or bold or reg))
        pdfmetrics.registerFontFamily(fam, normal=fam, bold=fam + "-Bold",
                                      italic=fam + "-Italic",
                                      boldItalic=fam + "-BoldItalic")
        _FAMILY = fam
    else:
        _FAMILY = "Helvetica"
    _REGISTERED = True
    return _FAMILY


_TAG_B = re.compile(r"\*\*(.+?)\*\*", re.S)
_TAG_I = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)", re.S)


def _inline(text: str) -> str:
    t = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = _TAG_B.sub(r"<b>\1</b>", t)
    t = _TAG_I.sub(r"<i>\1</i>", t)
    return t


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(_register_fonts(), 8.5)
    canvas.setFillColor(HexColor("#555555"))
    canvas.drawCentredString(A4[0] / 2, 1.1 * cm, str(canvas.getPageNumber()))
    canvas.restoreState()


def render_flow(items, translated, out_path, title: str | None = None,
                page_break_per_page: bool = False, on_page=None,
                cover_image: str | None = None,
                cover_subtitle: str | None = None) -> None:
    """Neu gesetztes PDF aus den übersetzten Absätzen bauen.

    items: Liste (pno, body_size, [(kind, text, size)]) —
           kind: para | heading | pagenum
    cover_image: optional Pfad zu einem Cover-Bild (PNG/JPEG), das als
                 Seite 1 eingesetzt wird. cover_subtitle: Untertitel,
                 der unter dem Bild zentriert gesetzt wird.
    """
    fam = _register_fonts()
    body_size = 10.5

    s_body = ParagraphStyle("body", fontName=fam, fontSize=body_size,
                            leading=body_size * 1.38, alignment=TA_JUSTIFY,
                            firstLineIndent=14, spaceAfter=3)
    s_head1 = ParagraphStyle("h1", fontName=fam + "-Bold", fontSize=19,
                             leading=24, spaceBefore=22, spaceAfter=12,
                             alignment=TA_CENTER, keepWithNext=1)
    s_head2 = ParagraphStyle("h2", fontName=fam + "-Bold", fontSize=14.5,
                             leading=19, spaceBefore=16, spaceAfter=8,
                             keepWithNext=1)
    s_head3 = ParagraphStyle("h3", fontName=fam + "-Bold", fontSize=12,
                             leading=16, spaceBefore=12, spaceAfter=6,
                             keepWithNext=1)
    s_title = ParagraphStyle("title", fontName=fam + "-Bold", fontSize=26,
                             leading=34, alignment=TA_CENTER, spaceBefore=120)
    s_subtitle = ParagraphStyle("subtitle", fontName=fam, fontSize=13.5,
                                leading=18, alignment=TA_CENTER,
                                spaceBefore=14, spaceAfter=0)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                            leftMargin=2.2 * cm, rightMargin=2.2 * cm,
                            topMargin=2.2 * cm, bottomMargin=2.4 * cm,
                            title=title or "TuxBook translation")
    story: list = []

    # ---- Cover-Seite (Bild + optionaler Untertitel) ------------------------
    if cover_image:
        cover_path = Path(cover_image)
        if cover_path.is_file():
            try:
                from PIL import Image as PILImage
                with PILImage.open(cover_path) as pil:
                    cw, ch = pil.size
            except Exception:
                cw, ch = 0, 0
            if cw > 0 and ch > 0:
                # Cover auf A4-Seitenhöhe skaliert, horizontal zentriert
                # (A4 595 x 842 pt, Seitenrand 2.2 cm = 62.4 pt)
                avail_w = A4[0] - 4.4 * cm
                avail_h = A4[1] - 4.4 * cm
                scale = min(avail_w / cw, avail_h / ch, 1.0)
                w = cw * scale
                h = ch * scale
                x0 = (A4[0] - w) / 2
                y0 = (A4[1] - h) / 2
                story.append(Image(str(cover_path), width=w, height=h,
                                   hAlign="CENTER"))
                story.append(Spacer(1, A4[1] - y0 - h - 10))
                if cover_subtitle:
                    story.append(Paragraph(_inline(cover_subtitle), s_subtitle))
                story.append(PageBreak())
            else:
                # Fallback: reiner Text-Titel
                if title:
                    story.append(Paragraph(_inline(title), s_title))
                    story.append(Spacer(1, 24))
                    story.append(PageBreak())
        else:
            if title:
                story.append(Paragraph(_inline(title), s_title))
                story.append(Spacer(1, 24))
                story.append(PageBreak())
    elif title:
        story.append(Paragraph(_inline(title), s_title))
        story.append(Spacer(1, 24))
        story.append(PageBreak())

    # Größte Überschrift + Median der Körpertextgrößen (1. Pass, leicht)
    max_head = 0.0
    sizes = [body for _, body, paras in items if paras]
    for _, _, paras in items:
        for kind, _, size in paras:
            if kind == "heading":
                max_head = max(max_head, size)
    body_mode = sorted(sizes)[len(sizes) // 2] if sizes else 10.0

    for pno, _, paras in items:
        if on_page:
            on_page(pno)
        tr = translated.get(pno) or []
        raw: list[list] = []   # [is_heading, text, style]
        for i, (kind, text, size) in enumerate(paras):
            t = (tr[i] if i < len(tr) else text)
            t = t.replace("\n", " ").strip()
            if not t or kind == "pagenum":
                continue
            if kind == "heading":
                ratio = size / max(body_mode, 1)
                if max_head and size >= max_head * 0.95 and ratio >= 1.35:
                    style = s_head1
                elif ratio >= 1.22:
                    style = s_head2
                else:
                    style = s_head3
                raw.append([True, _inline(t), style])
            else:
                raw.append([False, _inline(t), s_body])
        # Merge über Seitengrenzen: vorheriger Absatz endet mitten im Satz
        # und nächster beginnt kleingeschrieben -> zusammenführen (Style des
        # ersten Elements bleibt erhalten)
        merged: list[list] = []
        for item in raw:
            if (merged and not merged[-1][0] and not item[0]
                    and not ends_sentence(_uninline(merged[-1][1]))
                    and _uninline(item[1])[:1].islower()):
                merged[-1][1] = merged[-1][1].rstrip() + " " + item[1]
            else:
                merged.append(item)
        for is_heading, t, style in merged:
            story.append(Paragraph(t, style))
        if page_break_per_page:
            story.append(PageBreak())

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
