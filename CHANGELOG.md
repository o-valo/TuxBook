# Release-Notes

## v0.7.0 — Das Projekt heißt jetzt TuxBook (AGPL)

Umbenennung von `book2book`/`b2b` auf **TuxBook** — vollständig, also auch bei
CLI, Paket und Konfigurationsdatei — und Lizenzwechsel von MIT auf
**AGPL-3.0-or-later**.

### Geändert (nicht rückwärtskompatibel)

| alt | neu |
|---|---|
| `./b2b …` | `./tuxbook …` |
| `b2b_lib/` | `tuxbook_lib/` |
| `b2b.conf`, `b2b.conf.example` | `tuxbook.conf`, `tuxbook.conf.example` |
| `B2B_BAHNHOF_URL`, `B2B_OLLAMA_URL`, … | `TUXBOOK_BAHNHOF_URL`, `TUXBOOK_OLLAMA_URL`, … |
| Projektordner `book2book` | `TuxBook` |

- **Lizenz: AGPL-3.0-or-later** statt MIT. `LICENSE` enthält den unveränderten
  Lizenztext, Copyright (C) 2026 Olav Surawski (<https://github.com/o-valo>).
  Abschnitt 13 greift, wenn eine **geänderte** Fassung als Netzdienst öffentlich
  erreichbar ist — dann muss der Quellcode dieser Fassung zugänglich sein.
  Für die Nutzung am eigenen Rechner ändert sich nichts.
- **CLI und Paket heißen `tuxbook` bzw. `tuxbook_lib`**: Programmname im
  `argparse`, `--version` („tuxbook 0.7.0“), alle Hilfetexte und Ausgaben.
- **Konfiguration** liegt in `tuxbook.conf` (Vorlage `tuxbook.conf.example`).
  Die Schlüssel *in* der Datei bleiben unverändert (`BAHNHOF_URL`, …), nur der
  Präfix der Umgebungsvariablen wird zu `TUXBOOK_`.
- **CI, README, Tests und Tools** auf die neuen Namen gezogen; Version **0.7.0**.

### Umstellung einer bestehenden Installation

1. Projektordner umbenennen (`~/book2book` → `~/TuxBook`).
2. `.venv` neu anlegen — oder die Pfade in `.venv/bin/` auf den neuen Ordner
   korrigieren; `.venv/bin/python3` selbst ist nur ein Symlink und bleibt gültig.
3. `b2b.conf` in `tuxbook.conf` umbenennen — der Inhalt bleibt derselbe.
4. Umgebungsvariablen von `B2B_…` auf `TUXBOOK_…` umstellen, falls gesetzt.

## v0.6.0 — Markdown wird zur Quelle: neuer Befehl `tuxbook md2pdf`

Aus der Übersetzung entsteht jetzt ein **frisch gesetztes Buch-PDF aus dem
Markdown** – der Kreis PDF → OCR → Markdown → PDF ist geschlossen.

### Neu

- **`tuxbook md2pdf <datei.md>`** — setzt den Markdown-Export als Buch-PDF neu:
  A4, DejaVu-Serif (falls installiert), Blocksatz, Absatzabstand;
  H2 = Kapitel (beginnt auf neuer Seite), H3 = Untertitel; Titelblatt aus dem
  H1-Titel (ohne H1: Dateiname); Seitenzahlen unten mittig (Titelblatt ohne);
  TOC-Zeilen (`Titel .... 12`) mit fettem Titel und Seitenzahl rechts.
  Schalter: `--out DATEI`, `--title TITEL`, `--images ORDNER`.
- **Bilder im Markdown** — Inhaltsbilder werden je Seite extrahiert und als PNG
  neben das Markdown gelegt (`out/<job>_page_bilder/`), im MD verlinkt und im
  md2pdf passend skaliert, zentriert und nummeriert („Abbildung n“).
  Die Extraktion filtert Vollseiten-Scans (hinter der Textschicht gescannter
  Blätter) und Deko-Streifen, dedupliziert wiederverwendete Bilder sowie
  SMask-Paare und hält den Speicher flach (pro Seite nur Metadaten).
- **`--no-render`** bei `tuxbook run` — nur übersetzen, Rendering später; trennt
  Übersetzen und Setzen sauber, damit das Markdown vor dem Neusatz von Hand
  korrigiert werden kann.
- **README:** empfohlener Workflow **PDF → OCR → Markdown → PDF** in fünf
  Schritten (inkl. Hinweis, dass das Markdown die korrigierbare Quelle ist).
- **Tests:** `tests/test_images_md2pdf.py` für Bild-Extraktion und Markdown→PDF
  (Suite damit 24 Prüfungen, offline).

### Geändert

- `tuxbook_lib/render_md.py` deutlich erweitert (Bilder, Überschriftenstruktur,
  TOC-Zeilen)
- `tuxbook_lib/render_flow.py` und `tuxbook` an den Neusatz angepasst
- Version auf **0.6.0**

## v0.5.0 — erste öffentliche Version

Erste funktionsfähige Version von TuxBook: übersetzt ganze Bücher
(PDF oder ZIP mit Einzelseiten) seitenweise über einen OpenAI-kompatiblen
Chat-Endpunkt und setzt sie neu.

### Kernfunktionen

- **Eingabe:** einzelnes PDF oder ZIP (komplettes PDF wird automatisch
  bevorzugt; nur Einzelseiten werden natürlich sortiert zu einem Master-PDF
  zusammengeführt — `seite_2` vor `seite_10`)
- **Zwei Layout-Modi:**
  - `page`: 1:1-Seitenlayout, Übersetzung an Originalposition
  - `flow`: frisch gesetztes A4-Buch (Titelseite, Blocksatz, Seitenzahlen)
- **Markdown-Export** bei jedem Lauf (mit erkannten Überschriften)
- **Textquelle wählbar:** `--text-source auto|embedded|ocr`
  (eingebettete Textschicht nutzen oder alles per OCR neu erfassen)
- **OCR:** Tesseract lokal als Standard; Ollama-Vision als Fallback bzw.
  erzwungen per Flag
- **Bereinigungsschicht** vor der Übersetzung:
  - Scan-Artefakte (`i94o` → `1940`, `Mayjfower` → `Mayflower`)
  - Rauschzeilen und Deko-Präfixe
  - zerpflückte Inhaltsverzeichnisse → saubere `§n. Titel .... Seite`-Einträge
    (inkl. Sequenz-Fix: `§ II` nach `§ X` = 11, nicht 2)
  - Absatz-Rekonstruktion bei großem Zeilenabstand
- **Terminologie-Lock:** Schlüsselbegriffe aus den ersten Seiten werden
  allen Seiten-Requests konsistent vorgegeben (kein Drift über hunderte Seiten)
- **Seitengrenzen-Kontext:** Nachbarseiten-Texte mitigieren Satzbrüche;
  zerrissene Sätze werden beim MD-/Flow-Render gestitched
- **Resume/Cache:** jeder Lauf unterbrechbar (Strg+C gefahrlos) und wird
  fortgesetzt; Wechsel von Engine/Extraktion/Textquelle invalidieren den
  Cache automatisch
- **Übersetzungs-Engine austauschbar:** beliebiger OpenAI-kompatibler
  Endpunkt (`--engine bahnhof`) oder Mini-Übersetzer per Ollama
  (`--engine ollama --translate-model <modell>`)

### Konfiguration

Alle Endpunkte über `tuxbook.conf` (Vorlage: `tuxbook.conf.example`) oder
Umgebungsvariablen — keine fest verdrahteten Adressen im Code.

### Tests & CI

- Offline-Unit-Tests für Extraktion, Bereinigung, TOC-Fusion, Stitching
  und ZIP-Aufbereitung (`pytest tests/`)
- GitHub-Actions-CI: Syntax-Check, Unit-Tests, CLI- und OCR-Smoke-Test
- Hilfswerkzeuge: `tools/ocr_compare.py` (Tesseract vs. Vision-OCR auf
  einer degradierten Seite), `tools/pdf_look.py` (visuelle Qualitätskontrolle
  per Vision-Modell)

### Bekannte Grenzen

- Seitenmodus: Textsuche im Zielpdf findet zusätzlich die verdeckte
  Originalebene (visuell korrekt; für sauberen Text den `flow`-Modus nutzen)
- Komplexe Spalten-/Fußnoten-Layouts werden als Absatzstrom übernommen
- Vision-OCR halluziniert gern plausible Wörter — Tesseract bleibt Standard
