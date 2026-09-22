"""Tests: Bild-Extraktion (Scan-Filter, Export) und md2pdf-Parsing/Merging.

Komplett offline — erzeugt synthetische PDFs und Markdowns.
"""
from pathlib import Path

import pymupdf

from tuxbook_lib.images import ImageExtractor, build_image_map
from tuxbook_lib.render_md2pdf import (_merge_continuations, md_to_pdf,
                                   _roman_val, parse_md)


def _make_scan_page(doc, w_px=1200, h_px=1600, with_text=True):
    """Seite mit Vollseiten-Bild (Scan-Simulation) + optionaler Textschicht."""
    page = doc.new_page(width=595, height=842)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w_px, h_px))
    pix.set_rect(pix.irect, (200, 200, 200))
    tmp = Path("/tmp/_tuxbook_scan.png")
    pix.save(tmp)
    page.insert_image(page.rect, filename=str(tmp))
    if with_text:
        page.insert_text((72, 100), "Scanned page text layer.", fontsize=12)
    return page


def _make_content_page(doc):
    """Textseite mit echtem Inhaltsbild (querformatig, nicht seitengroß)."""
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Kapitel eins mit Text.", fontsize=12)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 250))
    pix.set_rect(pix.irect, (180, 60, 60))
    tmp = Path("/tmp/_tuxbook_content.png")
    pix.save(tmp)
    page.insert_image(pymupdf.Rect(100, 200, 400, 387.5), filename=str(tmp))
    page.insert_text((72, 500), "Text unter dem Bild.", fontsize=12)
    return page


# ------------------------------------------------------------- Bild-Filter
def test_fullpage_scan_with_text_is_filtered(tmp_path):
    doc = pymupdf.open()
    _make_scan_page(doc, with_text=True)
    src_path = tmp_path / "scan.pdf"
    doc.save(src_path)
    src = pymupdf.open(src_path)
    m = build_image_map(src, tmp_path)
    assert m == {}, "Vollseiten-Scan hinter Textschicht darf nicht exportiert werden"


def test_fullpage_scan_without_text_is_not_exported(tmp_path):
    """Bildlose Seite (nur Scan): OCR liefert den Inhalt → kein Bild-Export."""
    doc = pymupdf.open()
    _make_scan_page(doc, with_text=False)
    src_path = tmp_path / "scan_notext.pdf"
    doc.save(src_path)
    src = pymupdf.open(src_path)
    m = build_image_map(src, tmp_path)
    assert m == {}


def test_content_image_is_exported(tmp_path):
    doc = pymupdf.open()
    _make_content_page(doc)
    src_path = tmp_path / "content.pdf"
    doc.save(src_path)
    src = pymupdf.open(src_path)
    m = build_image_map(src, tmp_path)
    files = [d["file"] for v in m.values() for d in v]
    assert len(files) == 1, f"genau 1 Inhaltsbild erwartet, got {files}"
    p = tmp_path / files[0]
    assert p.is_file() and p.stat().st_size > 0


def test_stripe_image_is_filtered(tmp_path):
    """Winziger Deko-Streifen (z. B. Linie) wird nicht exportiert."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Text", fontsize=12)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 500, 8))
    pix.set_rect(pix.irect, (0, 0, 0))
    tmp = Path("/tmp/_tuxbook_stripe.png")
    pix.save(tmp)
    page.insert_image(pymupdf.Rect(72, 120, 500, 128), filename=str(tmp))
    src_path = tmp_path / "stripe.pdf"
    doc.save(src_path)
    src = pymupdf.open(src_path)
    m = build_image_map(src, tmp_path)
    assert m == {}, "Deko-Streifen muss gefiltert werden"


def test_export_path_matches_md_reference(tmp_path):
    """Exportdatei liegt exakt unter dem im MD referenzierten rel-Pfad."""
    doc = pymupdf.open()
    _make_content_page(doc)
    src_path = tmp_path / "content.pdf"
    doc.save(src_path)
    src = pymupdf.open(src_path)
    ex = ImageExtractor(src, tmp_path, md_name="bilder")
    imgs = ex.images_for_page(0)
    assert imgs, "Inhaltsbild erwartet"
    assert (tmp_path / imgs[0]["file"]).is_file()


# ----------------------------------------------------------- md2pdf-Parsing
def test_roman_val():
    assert _roman_val("II") == 2
    assert _roman_val("iv") == 4
    assert _roman_val("12") is None
    assert _roman_val("") is None


def test_parse_md_headings_and_toc(tmp_path):
    md = tmp_path / "buch.md"
    md.write_text(
        "# Mein Buch\n"
        "## Kapitel eins\n"
        "Absatz eins.\n"
        "§1. Das Ende .... 9\n"
        "§9. Kurztitel. 122\n"
        "Zwei.\n",
        encoding="utf-8")
    meta, blocks = parse_md(md)
    assert meta["title"] == "Mein Buch"
    kinds = [b["t"] for b in blocks]
    assert kinds == ["h2", "p", "toc", "toc", "p"]
    assert blocks[2]["text"] == "§1. Das Ende" and blocks[2]["page"] == "9"
    assert blocks[3]["text"] == "§9. Kurztitel" and blocks[3]["page"] == "122"


def test_merge_continuations():
    blocks = [
        {"t": "p", "text": "Erster Teil …"},
        {"t": "p", "text": "Zweiter Teil."},
        {"t": "p", "text": "Letzter Absatz …"},
        {"t": "h2", "text": "Kapitel"},
    ]
    out = _merge_continuations(blocks)
    texts = [b["text"] for b in out if b["t"] == "p"]
    assert texts[0] == "Erster Teil Zweiter Teil."
    assert texts[1] == "Letzter Absatz", "… ohne Fortsetzung wird entfernt"
    assert out[-1]["t"] == "h2"


# ------------------------------------------------------------- End-to-End
def test_md_to_pdf_end_to_end(tmp_path):
    md = tmp_path / "buch.md"
    md.write_text(
        "# Titelbuch\n"
        "## Kapitel A\n"
        "Erster Absatz mit etwas Text. " * 3 + "\n"
        "## Kapitel B\n"
        "Zweiter Absatz. Ende.\n",
        encoding="utf-8")
    out = md_to_pdf(md, tmp_path / "buch.pdf")
    assert out.is_file() and out.stat().st_size > 0
    d = pymupdf.open(out)
    t1 = d[0].get_text()
    assert "Titelbuch" in t1, "Titelblatt muss den H1-Titel zeigen"
    full = "".join(d[p].get_text() for p in range(d.page_count))
    assert "Kapitel A" in full and "Kapitel B" in full
    assert "Erster Absatz" in full and "Zweiter Absatz" in full
    # Kapitel B beginnt auf einer neuen Seite (A-Seite enthält nicht beides)
    page_a = [p for p in range(d.page_count) if "Kapitel A" in d[p].get_text()]
    page_b = [p for p in range(d.page_count) if "Kapitel B" in d[p].get_text()]
    assert page_a and page_b and page_a[0] < page_b[0] \
        and page_a[0] != page_b[0], "Kapitel B muss neue Seite beginnen"
