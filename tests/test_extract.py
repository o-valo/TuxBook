"""Unit-Tests für die Extraktions-/Bereinigungsschicht (ohne LLM, ohne Netz)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf

from tuxbook_lib.extract import (Block, Para, clean_artifacts, is_noise,
                             merge_toc, stitch_paragraphs, _dominant_body_size)


# ---- Artefakt-Fixes --------------------------------------------------------

def test_clean_artifacts_year():
    assert "1940" in clean_artifacts("im Jahre i94o")


def test_clean_artifacts_ligature():
    assert "Mayflower" in clean_artifacts("The Mayjfower Press")


def test_clean_artifacts_leading_noise_prefix():
    out = clean_artifacts("__, _ _ Hergestellt und gedruckt in Great Britain")
    assert out.startswith("Hergestellt")


def test_is_noise():
    assert is_noise("»— <")
    assert is_noise("• · .")
    assert not is_noise("Hergestellt und gedruckt")


# ---- TOC-Fusion ------------------------------------------------------------

def _blk(text):
    return Block(pymupdf.Rect(0, 0, 1, 1), text, 12.0, False, False, 1)


def test_merge_toc_fragments_and_sequence_fix():
    """Zerpflücktes Inhaltsverzeichnis + '§ II' nach '§ X' = 11 (nicht 2)."""
    blocks = [
        _blk("SEITE"),
        _blk("§ I."),
        _blk("Das Ende eines Zeitalters"),
        _blk("• 9"),
        _blk("§ X."),
        _blk("Offene Konferenzen"),
        _blk("• 21"),
        _blk("§ II."),
        _blk("Der Apparat des Friedens"),
        _blk("• 34"),
        _blk("Another Entry .... 55"),
        _blk("One More .... 61"),
    ]
    out = merge_toc(blocks)
    texts = [b.text for b in out]
    assert texts[0] == "§1. Das Ende eines Zeitalters .... 9"
    assert "§10. Offene Konferenzen .... 21" in texts
    assert "§11. Der Apparat des Friedens .... 34" in texts  # Sequenz-Fix


def test_merge_toc_leaves_normal_pages_alone():
    blocks = [_blk("Ein ganz normaler Absatz."),
              _blk("Noch einer mit Inhalt.")]
    assert merge_toc(blocks) is blocks


# ---- Stitching über Seitengrenzen ------------------------------------------

def test_stitch_joins_sentence_fragments():
    items = [("para", "Der alte Leuchtturm stand am Rand"),
             ("para", "und bewachte das Meer.")]
    out = stitch_paragraphs(items)
    assert len(out) == 1
    assert out[0][1] == ("Der alte Leuchtturm stand am Rand "
                         "und bewachte das Meer.")


def test_stitch_keeps_finished_sentences():
    items = [("para", "Der Satz ist fertig."),
             ("para", "Ein neuer Absatz beginnt.")]
    out = stitch_paragraphs(items)
    assert len(out) == 2


# ---- Metrik / Para ---------------------------------------------------------

def test_dominant_body_size():
    assert _dominant_body_size([10.0, 10.2, 10.1, 20.5]) < 12.0


def test_para_kinds():
    p = Para("Titel", 14.0, kind="heading")
    assert p.kind == "heading"
    q = Para("Text", 10.0)
    assert q.kind == "para"
