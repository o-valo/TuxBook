"""Unit-Tests für die ZIP-Quellenaufbereitung (ohne LLM, ohne Netz)."""
import io
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import pymupdf

from tuxbook_lib.project import CleanError
from tuxbook_lib.zipsrc import natural_key, prepare_source


def _pdf_bytes(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_natural_sort():
    names = ["seite_10.pdf", "seite_2.pdf", "seite_1.pdf"]
    assert sorted(names, key=natural_key) == \
        ["seite_1.pdf", "seite_2.pdf", "seite_10.pdf"]


def test_prepare_prefers_matching_complete_pdf(tmp_path):
    """ZIP mit komplettem PDF + Einzelseiten -> komplettes PDF gewinnt."""
    zp = tmp_path / "buch.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("TheBook.pdf", _pdf_bytes(["SEITE-A", "SEITE-B", "SEITE-C"]))
        z.writestr("RTF/00000001.pdf", _pdf_bytes(["nur eine Seite"]))
    job = SimpleNamespace(dir=tmp_path / "job")
    master, note = prepare_source(zp, job)
    doc = pymupdf.open(master)
    assert doc.page_count == 3
    assert "TheBook.pdf" in note


def test_prepare_merges_single_pages_naturally(tmp_path):
    """Nur Einzelseiten -> natural sort Merge (seite_2 vor seite_10)."""
    zp = tmp_path / "buch.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("seite_10.pdf", _pdf_bytes(["SEITE-10"]))
        z.writestr("seite_1.pdf", _pdf_bytes(["SEITE-1"]))
        z.writestr("seite_2.pdf", _pdf_bytes(["SEITE-2"]))
    job = SimpleNamespace(dir=tmp_path / "job")
    master, _note = prepare_source(zp, job)
    doc = pymupdf.open(master)
    assert doc.page_count == 3
    assert "SEITE-1" in doc[0].get_text()
    assert "SEITE-2" in doc[1].get_text()
    assert "SEITE-10" in doc[2].get_text()


def test_prepare_rejects_ambiguous_multipage(tmp_path):
    zp = tmp_path / "buch.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("a.pdf", _pdf_bytes(["1", "2", "3"]))
        z.writestr("b.pdf", _pdf_bytes(["x", "y", "z"]))
    job = SimpleNamespace(dir=tmp_path / "job")
    with pytest.raises(CleanError):
        prepare_source(zp, job)


def test_prepare_uses_master_cache(tmp_path):
    zp = tmp_path / "buch.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("solo.pdf", _pdf_bytes(["EINS", "ZWEI"]))
    job = SimpleNamespace(dir=tmp_path / "job")
    m1, _ = prepare_source(zp, job)
    m2, note2 = prepare_source(zp, job)
    assert m1 == m2
    assert "Cache" in note2
