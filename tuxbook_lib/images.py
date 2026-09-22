"""Bild-Extraktion: Inhaltsbilder je Seite für den Markdown-Export.

Filtert Vollseiten-Scans weg (bei gescannten Büchern liegt hinter der
Textschicht ein Scan des ganzen Blattes — das ist kein Inhaltsbild) und
Deko-Streifen. Dedupliziert wiederverwendete Bilder (z. B. Kopfzeilen-Logo)
über die Seiten hinweg sowie SMask-Doppel (gleiches Seitenverhältnis,
kleiner — typische Masken-Paare in Scans).

Speicherarm: pro Seite nur Metadaten, kein Decode außer beim Export selbst.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf


# Ein Bild gilt als Vollseiten-Scan, wenn es (fast) die ganze Seite bedeckt
# UND die Seite auch einen Textlayer hat (sonst IST es der Inhalt → OCR-Fall).
FULLPAGE_COVER = 0.85

# Deko: extrem schmale oder flache Streifen (Linien, Rahmen)
MIN_W, MIN_H = 24, 24          # px-Untergrenze
MIN_ASPECT = 0.04              # Verhältnis kürzer/länger Seite < 4 % → Streifen
MAX_DIM = 2000                 # Export: längste Kante (größer → verkleinern)


class ImageExtractor:
    """Sammelt pro Seite die Inhaltsbilder und exportiert sie als PNG."""

    def __init__(self, src: pymupdf.Document, out_dir: Path,
                 md_name: str = "bilder"):
        self.src = src
        self.out_dir = Path(out_dir)
        self.md_dir = md_name          # relativer Name im MD
        self._seen_hash: set[str] = set()   # globale Dedup (wiederholte Logos)
        self._exported: dict[int, str] = {}  # xref -> Dateiname

    # ------------------------------------------------------------------
    def _is_fullpage_rect(self, pno: int, rect: pymupdf.Rect) -> bool:
        """Bild-Rect bedeckt (fast) die ganze Seite?"""
        area = self.src[pno].rect.get_area()
        if area <= 0:
            return False
        inter = (self.src[pno].rect & rect).get_area()
        return (inter / area) >= FULLPAGE_COVER

    @staticmethod
    def _is_stripe(w: float, h: float) -> bool:
        if w < MIN_W or h < MIN_H:
            return True
        short, long = min(w, h), max(w, h)
        return (short / long) < MIN_ASPECT

    # ------------------------------------------------------------------
    def _export(self, pno: int, xref: int) -> str | None:
        """Exportiert ein Bild als PNG (ggf. verkleinert). None = fehlgeschlagen."""
        if xref in self._exported:
            return self._exported[xref]
        # Dateien liegen in out_dir/md_name/ — genau auf den rel-Pfad passend
        dest_dir = self.out_dir / self.md_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"p{pno + 1:04d}_x{xref}.png"
        try:
            pix = pymupdf.Pixmap(self.src, xref)
            if pix.colorspace is None:            # Stencil-Maske o. ä.
                return None
            if pix.colorspace.n > 3:              # CMYK → RGB
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            # zu groß → verkleinern (halbiert, bis längste Kante ≤ MAX_DIM)
            while max(pix.width, pix.height) > MAX_DIM:
                pix.shrink(1)
            pix.save(path)
        except Exception:
            return None                            # korrupt → überspringen
        rel = f"{self.md_dir}/{path.name}"
        self._exported[xref] = rel
        return rel

    # ------------------------------------------------------------------
    def images_for_page(self, pno: int) -> list[dict]:
        """Liefert [{'file': relpath}] für die Inhaltsbilder der Seite.

        Zweistufig: Der Hauptfall gescannter Bücher (genau eine Bildgruppe
        mit Seitenaspekt und hoher DPI hinter einer Textschicht) wird ohne
        teure bbox-Ermittlung erkannt; alles Mehrdeutige wird über die
        platzierte Fläche geprüft (get_image_rects, zeigt den Display-List-
        Cache der Seite).
        """
        page = self.src[pno]
        out: list[dict] = []
        has_text = bool(page.get_text("text").strip())

        raw = [im for im in page.get_images(full=True)
               if im[0] and im[2] > 0 and im[3] > 0]
        if not raw:
            return out
        if not has_text:
            # Seite ohne Textschicht: das Bild IST der Inhalt (OCR-Fall) —
            # nichts als Inhaltsbild exportieren.
            return out

        # Masken-Paare deduplizieren: identische Pixelmaße = Base+SMask
        groups: list[tuple[int, int, int]] = []   # (xref, w, h)
        seen_dims: set[tuple[int, int]] = set()
        for im in raw:
            dims = (im[2], im[3])
            if dims in seen_dims:
                continue
            seen_dims.add(dims)
            groups.append((im[0], im[2], im[3]))

        pw, ph = page.rect.width, page.rect.height
        a_page = pw / ph if ph > 0 else 0

        # Schnellpfad (Scan-Familie): alle Bilder mit Seitenaspekt (±2 %)
        # und mindestens eines hochauflösend → gescannte Seite. Deckt auch
        # Base+SMask mit UNGLEICHEN Auflösungen ab (910x1364 + 2730x4092).
        if groups:
            same_aspect = all(
                (min(w / h, a_page) / max(w / h, a_page)) >= 0.98
                for _, w, h in groups if h > 0)
            dpi = max((min(w / (pw / 72.0), h / (ph / 72.0))
                       for _, w, h in groups if pw > 0 and ph > 0),
                      default=0.0)
            if same_aspect and (len(groups) >= 2 or dpi >= 200):
                return out                     # Scan hinter Textschicht

        # Präziser Pfad: platzierte Fläche je Gruppe prüfen
        for xref, w, h in groups:
            if self._is_stripe(w, h):
                continue
            try:
                rects = page.get_image_rects(xref, transform=False)
            except Exception:
                rects = []
            if rects:
                union = rects[0]
                for r in rects[1:]:
                    union |= r
                if self._is_fullpage_rect(pno, union):
                    continue                   # Vollseiten-Scan
            rel = self._export(pno, xref)
            if rel:
                out.append({"file": rel})

        return out


def build_image_map(src: pymupdf.Document, job_img_dir: Path,
                    md_name: str = "bilder") -> dict[int, list[dict]]:
    """Hauptentry: image_map[pno] = [{'file': rel}] für den MD-Renderer.

    Ruft ImageExtractor seitenweise auf — speicherarm, ohne alles vorzuhalten.
    """
    ex = ImageExtractor(src, job_img_dir, md_name=md_name)
    mapping: dict[int, list[dict]] = {}
    for pno in range(src.page_count):
        imgs = ex.images_for_page(pno)
        if imgs:
            mapping[pno] = imgs
    return mapping


def rebase_image_paths(md_path: Path, img_dir: Path) -> Path:
    """Bildpfade im MD auf einen anderen Ordner umbiegen (falls das MD oder
    die Bilder verschoben wurden). Rückgabe: Pfad des angepassten MDs —
    bei Bedarf wird eine Kopie <stem>_reb.md geschrieben, nie das Original
    überschrieben."""
    md_path = Path(md_path)
    txt = md_path.read_text(encoding="utf-8")
    pat = re.compile(r"(!\[[^\]]*\]\(<)([^>]+)(>\))")

    def sub(m):
        old = m.group(2)
        name = Path(old).name
        if (Path(img_dir) / name).is_file():
            return f"{m.group(1)}{img_dir / name}{m.group(3)}"
        return m.group(0)  # nicht auffindbar: unverändert lassen

    new = pat.sub(sub, txt)
    if new == txt:
        return md_path
    out = md_path.with_name(md_path.stem + "_reb.md")
    out.write_text(new, encoding="utf-8")
    return out
