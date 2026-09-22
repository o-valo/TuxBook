"""Erzeugt ein englisches Test-PDF zum Testen von TuxBook."""
from pathlib import Path

import pymupdf

PAGE1 = ("The Lighthouse of Cape Morrow", "",
         "The old lighthouse stood alone at the edge of the cliff, watching over "
         "the grey sea as it had done for almost two hundred years. Its keeper, "
         "an elderly man named Elias Crane, had lived there for thirty-one of "
         "those years, and he knew every sound the tower made in the wind.",
         "On the morning of the storm, Elias climbed the one hundred and twelve "
         "steps to the lamp room, as he did every evening. The sea below was "
         "already white with foam, and the gulls had vanished inland hours ago. "
         "Somewhere beyond the horizon, the fishing fleet was racing home.",
         "He lit the lamp at sunset, trimming the wick with the care of a "
         "surgeon. The beam swept across the water, once every seven seconds, "
         "as it had since the year his grandfather was born.")

PAGE2 = ("Chapter Two — The Visitor", "",
         "Nobody came to the lighthouse by road. The path from the village was "
         "three miles of loose stone and gorse, and the supply boat called only "
         "once a month. Yet on the fourth day of the storm, Elias found "
         "footprints in the wet sand below the tower, leading up from the sea "
         "and back again.",
         "He told himself it was nothing. Cargo washed ashore, perhaps, or a "
         "sailor who had decided against the climb. But that night, the lamp "
         "burned strangely low, and the wind carried a sound that might have "
         "been a bell.",
         "In the morning there was a package on the doorstep, wrapped in "
         "oilcloth and tied with tarred string. There was no name upon it, only "
         "a single word, cut into the wax of the seal: REMEMBER.")

MORE = [
    ("Chapter Three — The Charts", "",
     "The lighthouse kept its records in a cabinet of oak and iron, and every "
     "keeper since 1821 had added his observations to the same charts. Elias "
     "pulled the oldest folio from the shelf and carried it to the window, "
     "where the morning light fell grey and cold upon the paper.",
     "The handwriting changed from decade to decade, but the entries were "
     "always the same in substance: weather, shipping, the trimming of wicks. "
     "Only once, in the autumn of 1893, had a keeper written something "
     "different, in a hand that shook as it wrote.",
     "It is not a wreck, the old entry read. It rises with the tide and it "
     "has no lantern. God forgive us, we have seen it from the tower."),
    ("Chapter Four — What the Sea Keeps", "",
     "Elias had never been a superstitious man; a keeper learns that the sea "
     "explains everything, if one is willing to hear the explanation. But the "
     "package lay on his table, and the word upon the seal was in a hand he "
     "recognised, because it was his own.",
     "He did not remember writing it. He did not remember the autumn of 1893, "
     "for the simple reason that he had not been born. And yet the ink had "
     "faded as only old ink fades, and the wax had cracked as only old wax "
     "cracks.",
     "Outside, the storm turned. The wind came round to the north-east with a "
     "sound like tearing canvas, and the tower leaned into it, and the lamp "
     "burned on."),
]


def _page(doc, blocks, draw_fig=False):
    p = doc.new_page(width=419, height=595)  # A5, ähnlich einem Buch
    y = 60
    for i, (head, _, *paras) in enumerate([blocks] if not isinstance(blocks, list) else blocks):
        pass
    return p


def make_test_pdf(out_path: Path) -> Path:
    out_path = Path(out_path).expanduser()
    doc = pymupdf.open()

    chapters = [("The Lighthouse of Cape Morrow", PAGE1)] if False else []
    # Titelblatt
    t = doc.new_page(width=419, height=595)
    t.insert_text((110, 200), "THE LIGHTHOUSE", fontname="hebo", fontsize=26)
    t.insert_text((140, 230), "of Cape Morrow", fontname="hebo", fontsize=18)
    t.insert_text((150, 300), "A Story of the Sea", fontname="tiro", fontsize=12)
    t.insert_text((160, 520), "Test book for TuxBook", fontname="tiro", fontsize=9)

    # Kapitelseiten
    chs = [PAGE1, PAGE2] + MORE
    for head, _, *paras in chs:
        p = doc.new_page(width=419, height=595)
        p.insert_textbox((50, 50, 369, 90), head, fontname="hebo", fontsize=15)
        y = 100
        for para in paras:
            r = pymupdf.Rect(50, y, 369, y + 150)
            used = p.insert_textbox(r, para, fontname="tiro", fontsize=10.5,
                                    align=pymupdf.TEXT_ALIGN_JUSTIFY)
            nlines = max(1, round(-(-len(para) // 78)))
            y += nlines * 13.2 + 8

    # Grafikseite (Karte/Abbildung) mit Bildunterschrift
    fig = doc.new_page(width=419, height=595)
    fig.insert_textbox((50, 40, 369, 70), "Appendix: Chart of the Cape",
                       fontname="hebo", fontsize=13)
    fig.draw_circle((210, 260), 120, color=(0, 0, 0.55), width=1.4)
    fig.draw_line((90, 260), (330, 260), color=(0, 0, 0.55), width=1)
    fig.draw_line((210, 140), (210, 380), color=(0, 0, 0.55), width=1)
    fig.insert_textbox((50, 420, 369, 520),
                       "Fig. 1 — The cape as surveyed in 1893. The tower is "
                       "marked at the northern point; the reef extends "
                       "north-east beneath the tide.",
                       fontname="tiro", fontsize=10)

    # "Gescannte" Seite: Seite 2 als Bild einbetten -> erzwingt OCR
    pix = doc[2].get_pixmap(dpi=100)
    scan = doc.new_page(width=419, height=595)
    scan.insert_image(scan.rect, pixmap=pix)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path), garbage=4, deflate=True)
    doc.close()
    return out_path


if __name__ == "__main__":
    print(make_test_pdf(Path("test_book_en.pdf")))
