"""ZIP-Quellen: PDFs aus einem ZIP-Archiv zu einem Master-PDF vorbereiten.

Strategie:
- Gibt es genau ein mehrseitiges PDF -> dieses als Master verwenden.
- Sonst alle einseitigen PDFs natürlich sortiert (seite_2 vor seite_10)
  zu einem Master-PDF zusammenführen.
- master.pdf wird im Job-Verzeichnis gecacht (nur einmal nötig).
"""
import re
import zipfile
from pathlib import Path

import pymupdf

from .project import CleanError


def natural_key(s: str):
    """Sortierschlüssel, der Zahlen numerisch vergleicht."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", s)]


def prepare_source(zip_path: Path, job) -> tuple[Path, str]:
    """Liefert (master_pdf, Hinweistext). Cacht jobs/<name>/master.pdf."""
    master = job.dir / "master.pdf"
    if master.exists():
        return master, "master.pdf bereits im Job-Cache"

    job.dir.mkdir(parents=True, exist_ok=True)
    z = zipfile.ZipFile(zip_path)
    try:
        pdfs = [i for i in z.infolist()
                if i.filename.lower().endswith(".pdf") and not i.is_dir()]
        if not pdfs:
            raise CleanError("ZIP enthält keine PDF-Dateien.")

        multipage: list[tuple[str, int]] = []
        single: list[tuple[str, int]] = []
        for info in pdfs:
            try:
                d = pymupdf.open(stream=z.read(info), filetype="pdf")
                n = d.page_count
                d.close()
            except Exception:
                continue  # kaputte Datei überspringen
            (multipage if n > 1 else single).append((info.filename, n))

        if multipage:
            # Bevorzugung: Name == ZIP-Stamm, sonst klar größtes PDF
            stem = zip_path.stem.lower()
            by_name = [t for t in multipage
                       if Path(t[0]).stem.lower() == stem]
            multipage.sort(key=lambda t: -t[1])
            pick = None
            if len(multipage) == 1:
                pick = multipage[0]
            elif by_name:
                pick = max(by_name, key=lambda t: t[1])
            elif multipage[0][1] >= 2 * multipage[1][1]:
                pick = multipage[0]
            if pick is None:
                raise CleanError(
                    "ZIP enthält mehrere mehrseitige PDFs ("
                    + ", ".join(Path(n).name for n, _ in multipage[:5])
                    + ") — bitte das gewünschte direkt als Eingabe angeben.")
            name, n = pick
            master.write_bytes(z.read(name))
            others = sum(c for nm, c in multipage if nm != name) + len(single)
            note = (f"komplettes PDF '{Path(name).name}' aus ZIP übernommen "
                    f"({n} Seiten"
                    + (f"; {others} weitere PDFs ignoriert)" if others else ")"))
        elif single:
            single.sort(key=lambda t: natural_key(t[0]))
            m = pymupdf.open()
            skipped = 0
            for name, _ in single:
                try:
                    d = pymupdf.open(stream=z.read(name), filetype="pdf")
                    m.insert_pdf(d, from_page=0, to_page=0)
                    d.close()
                except Exception:
                    skipped += 1
            if m.page_count == 0:
                raise CleanError("ZIP: keine lesbaren Einzelseiten-PDFs.")
            n_merged = m.page_count
            m.save(str(master), garbage=4, deflate=True)
            m.close()
            note = (f"{n_merged} Einzelseiten natürlich sortiert zu "
                    "master.pdf zusammengeführt"
                    + (f" ({skipped} defekte übersprungen)" if skipped else ""))
        else:
            raise CleanError("ZIP enthält keine lesbaren PDFs.")
    finally:
        z.close()
    return master, note
