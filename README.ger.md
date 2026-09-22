# TuxBook (tuxbook)

[![CI](https://github.com/o-valo/TuxBook/actions/workflows/ci.yml/badge.svg)](https://github.com/o-valo/TuxBook/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

Übersetzt ganze Bücher — PDF oder ZIP mit Einzelseiten — seitenweise in eine
andere Sprache und setzt sie neu zu einem sauberen PDF. Auch für dicke Bücher
(1000+ Seiten): unterbrechbar, cache-basiert, parallelisiert.

*Englische Fassung dieses Dokuments: [README.md](README.md)*

## Features

- **Eingabe:** einzelnes PDF *oder* ZIP (komplettes PDF +/oder nummerierte
  Einzelseiten — wird automatisch natürlich sortiert zu einem Master-PDF
  zusammengeführt, `seite_2` vor `seite_10`)
- **Zwei Layout-Modi:** `page` (1:1, deutscher Text an Originalposition)
  und `flow` (frisch gesetztes A4-Buch mit Titelseite, Blocksatz, Seitenzahlen)
- **Markdown-Export** bei jedem Lauf (mit erkannten Überschriften)
- **Bilder im Markdown:** Inhaltsbilder werden je Seite extrahiert, im MD
  verlinkt und beim Neusatz als Abbildungen gesetzt
- **`tuxbook md2pdf`:** setzt den — von Hand korrigierbaren — Markdown-Export als
  frisch gesetztes Buch-PDF neu (Titelblatt, Kapitel auf neuer Seite, TOC,
  Seitenzahlen)
- **Textquelle wählbar:** eingebettete Textschicht nutzen (`auto`/`embedded`)
  oder alles per OCR neu erfassen (`ocr`)
- **OCR:** Tesseract lokal als Standard (schnell & präzise), Ollama-Vision
  als Fallback für harte Fälle
- **Bereinigungsschicht** vor der Übersetzung: Scan-Artefakte (`i94o`→`1940`,
  `jf`→`fl`), Rauschzeilen, zerpflückte Inhaltsverzeichnisse werden repariert
- **Terminologie-Lock:** Schlüsselbegriffe werden aus den ersten Seiten
  extrahiert und allen Seiten-Requests konsistent vorgegeben
- **Seitengrenzen-Kontext:** Nachbarseiten-Texte mitigieren Satzbrüche
- **Resume/Cache:** jeder Lauf ist unterbrechbar (Strg+C gefahrlos) und wird
  exakt dort fortgesetzt; Engine-/Extraktions-Wechsel invalidieren den Cache
  automatisch

## Setup

```bash
git clone <dieses-repo> && cd TuxBook
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# OCR (Standard-Engine, rein lokal):
sudo apt-get install tesseract-ocr tesseract-ocr-deu   # + weitere Sprachpakete nach Bedarf
```

**Venv:** `./tuxbook` aktiviert das Projekt-Venv (`.venv`) automatisch — der Aufruf
funktioniert also auch **ohne** vorheriges `source .venv/bin/activate`. Nur wenn
du `python3` direkt brauchst (Tools, Tests, eigene Skripte), vorher aktivieren:

```bash
source .venv/bin/activate
```

### Konfiguration

Endpunkte werden aus `tuxbook.conf` gelesen (siehe `tuxbook.conf.example`):

```bash
cp tuxbook.conf.example tuxbook.conf
# dann deine eigene Chat-API (OpenAI-kompatibel) und optional einen
# Ollama-Endpunkt für Vision-OCR eintragen
```

Alternativ funktionieren Umgebungsvariablen
(`TUXBOOK_BAHNHOF_URL`, `TUXBOOK_BAHNHOF_MODEL`, `TUXBOOK_OLLAMA_URL`, `TUXBOOK_OLLAMA_MODEL`).
Ohne Konfiguration lauten die Defaults `localhost` — d. h. du brauchst:

1. einen **OpenAI-kompatiblen Chat-Endpunkt** für die Übersetzung
   (irgendein selbst gehostetes LLM funktioniert, z. B. vLLM/llama.cpp/LM Studio)
2. optional einen **Ollama-Endpunkt** für Vision-OCR und Mini-Übersetzer

## Nutzung

```bash
# 1) Übersetzen + 1:1 neu setzen (Quellseite N -> Zielseite N)
./tuxbook run buch.pdf --from auto --to de --mode page

# 2) Übersetzen + als Buch neu setzen (A4, Blocksatz, Seitenzahlen)
./tuxbook run buch.pdf --from en --to de --mode flow --title "Buchtitel"

# 3) ZIP mit Einzelseiten — wird automatisch zu einem Master-PDF verbunden
./tuxbook run buchseiten.zip --to de --job meinbuch

# 4) Große Bücher: stapelweise (Resume nutzt den Cache)
./tuxbook run buch.pdf --pages 1-250 --job meinbuch
./tuxbook run buch.pdf --pages 251-500 --job meinbuch

# 5) Nur rendern, wenn alle Seiten im Cache sind
./tuxbook run buch.pdf --mode flow --job meinbuch --render-only --title "Titel"

# 6) Status / OCR-Vergleich / visuelle Qualitätskontrolle
#    (für die python3-Tools vorher: source .venv/bin/activate)
./tuxbook status --job meinbuch
python3 tools/ocr_compare.py buch.pdf --page 42
python3 tools/pdf_look.py out/meinbuch_page.pdf --pages 2,4,10
```

Wichtige Flags:

| Flag | Wirkung |
|---|---|
| `--mode page` | 1 Seite Quelle → 1 Seite Ziel, Text an Originalposition (Standard) |
| `--mode flow` | neu gesetztes Buch, Absätze fließen natürlich |
| `--text-source auto` | eingebetteter Text, OCR nur als Fallback (Standard) |
| `--text-source embedded` | nie OCR — nur eingebettete Textschicht |
| `--text-source ocr` | eingebetteten Text ignorieren, jede Seite per OCR erfassen |
| `--pages` | Seitenbereiche wie `1-50,60,71-80` |
| `--job NAME` | Jobname = Resume-Schlüssel (Cache in `jobs/NAME/pages/`) |
| `--glossary datei` | Zeilen `Begriff = Übersetzung` (vom LLM zu beachten) |
| `--no-term-lock` | Terminologie-Extraktion abschalten |
| `--no-render` | nur übersetzen, Rendering später (z. B. um das MD vorher zu korrigieren) |
| `--workers N` | parallele Seiten (Standard 3) |
| `--engine bahnhof` | Übersetzung über den konfigurierten Chat-Endpunkt (Standard) |
| `--engine ollama --translate-model M` | Mini-Übersetzungsmodell auf Ollama (z. B. ein dedizierter 1B-Translator); Cache ist engine-spezifisch |
| `--ocr tesseract` | Standard. `auto` = Ollama-Vision als Fallback, `ollama` erzwingt Vision-OCR |
| `--retranslate` | Cache ignorieren, alles neu |

## Empfohlener Workflow: PDF → OCR → Markdown → PDF

Für gescannte Bücher (oder wenn die eingebettete Textschicht unbrauchbar ist)
ist das der Weg zu einem sauberen, von Menschen lesbaren Ergebnis:

```bash
# 1) Übersetzen — OCR erzwingen (jede Seite wird gerendert + per OCR erfasst)
./tuxbook run buch.pdf --from auto --to de --mode page \
    --text-source ocr --job meinbuch

# 2) Status: alle Seiten im Cache?
./tuxbook status --job meinbuch

# 3) Markdown aus dem Cache rendern (1:1-PDF gibt es gratis dazu)
./tuxbook run buch.pdf --job meinbuch --render-only
#    -> out/meinbuch_page.md + out/meinbuch_page.pdf

# 4) Markdown von Hand korrigieren — es ist die korrigierbare Quelle;
#    Bilder liegen daneben (out/meinbuch_page_bilder/) und sind verlinkt
#    (optional: nur mit --no-render übersetzen, um diesen Schritt zu trennen)

# 5) Sauber gesetztes Buch-PDF aus dem Markdown neu setzen
./tuxbook md2pdf out/meinbuch_page.md --title "Buchtitel"
#    -> out/meinbuch_page_neu.pdf
```

Hinweise:

- **`--mode page` + `--render-only`** liefert das MD als Zwischenprodukt; das
  eigentliche Buch-PDF entsteht in Schritt 5 aus dem MD (Blocksatz, echte
  Überschriften, Kapitel auf neuer Seite, Titelseite).
- Bei **großen Büchern** stapelweise arbeiten (Schritt 1 mit `--pages 1-250`,
  dann `251-500`, …) — der Cache macht jede Unterbrechung gefahrlos.
- Das **MD ist die Quelle der Wahrheit**: Korrekturen (z. B. OCR-Fehler in
  Eigennamen) gehören vor Schritt 5 ins Markdown, nicht ins PDF.
- Wurden MD und Bilder-Ordner verschoben, zeigt `md2pdf --images ORDNER` auf
  die Bilder; `--out DATEI` setzt einen anderen Ausgabenamen.

## Ablauf

1. **Vorbereitung:** ZIP ggf. entpacken/mergen (mit Cache), Extraktion mit
   Bereinigungsschicht (Artefakt-Fixes, Noise-Filter, TOC-Fusion, Absatz-Merge)
2. **OCR**, falls eine Seite kaum Text enthält und ein Bild hat (je nach
   `--text-source`)
3. **Übersetzung** parallel (`--workers`): Absätze nummeriert (`Pn:`-Protokoll)
   mit Verifikation — fehlende Absätze werden einzeln nachgefragt; schlägt eine
   Seite komplett fehl, wird sie nicht gecacht und beim nächsten Lauf wiederholt
4. **Rendering** am Ende (oder per `--render-only`): PDF + Markdown

## Struktur

```
tuxbook                     CLI-Einstieg (run/status/md2pdf/make-test-pdf/ocr-test)
tuxbook_lib/
  config.py             Endpunkte (tuxbook.conf/env), Fonts, Guard-Fenster
  llm.py                Chat-Client + Ollama-Client (Guard, Retries)
  zipsrc.py             ZIP-Vorbereitung (Master-PDF-Auswahl/Merge)
  extract.py            PDF-Extraktion, Bereinigung, TOC-Fusion, Absatz-Merge
  ocr.py                Tesseract primär, Ollama-Vision Fallback
  translate.py          Pn-Protokoll, Verifikation, Term-Lock, Kontext
  images.py             Inhaltsbilder je Seite extrahieren (für den MD-Export)
  render_page.py        Seitenmodus (Original überdeckt + Übersetzung)
  render_flow.py        Flussmodus (ReportLab, A4, Blocksatz, Titelseite)
  render_md.py          Markdown-Export
  render_md2pdf.py      Markdown → frisch gesetztes Buch-PDF
  project.py            Jobs, Manifest, Resume, Glossar
tools/
  ocr_compare.py        Tesseract vs. Vision-OCR auf einer degradierten Seite
  pdf_look.py           visuelle Qualitätskontrolle per Vision-Modell
  make_test_pdf.py      Test-PDF für die CI bauen
jobs/<name>/pages/*.json  Seiten-Cache
out/<name>_<mode>.pdf     Zielpdf (+ .md, + _bilder/)
```

## Tests & Entwicklung

Offline-Unit-Tests (ohne LLM/Netz) für Extraktion, Bereinigung, TOC-Fusion,
Stitching, ZIP-Aufbereitung sowie Bild-Extraktion und Markdown→PDF:

```bash
pip install -r requirements-dev.txt
pytest tests/
```

CI (GitHub Actions) prüft bei jedem Push: Syntax aller Module, Unit-Tests,
CLI-Smoke (`--version`, `make-test-pdf`) und OCR-Smoke mit Tesseract.

> Die Badge-URL zeigt auf <https://github.com/o-valo/TuxBook> — bei einem
> anderen Repository-Namen dort anpassen.

## Bekannte Grenzen

- **Seitenmodus:** Textsuche im Zielpdf findet zusätzlich die verdeckte
  Originalebene (visuell korrekt; für sauberen Text `--mode flow` nutzen).
- Komplexe Spalten-/Fußnoten-Layouts werden als Absatzstrom übernommen.
- Vision-OCR halluziniert gern plausible Wörter — deshalb ist Tesseract der
  Standard und Vision nur Fallback (Messung mit `tools/ocr_compare.py`).
- Rechtschreibung/Typografie des Originals (Ligaturen, Kapitälchen) werden
  vereinfacht übernommen.

## Lizenz

**GNU Affero General Public License v3.0 oder später** (AGPL-3.0-or-later) —
unveränderter Lizenztext in [LICENSE](LICENSE),
Copyright (C) 2026 Olav Surawski (<https://github.com/o-valo>).

Kurz gesagt: benutzen, ändern und weitergeben ist frei erlaubt, solange
abgeleitete Fassungen wieder unter der AGPL stehen. Abschnitt 13 greift, wenn
du eine **geänderte** Fassung als Netzdienst öffentlich erreichbar machst —
dann muss der Quellcode dieser Fassung den Nutzern zugänglich sein. Für die
Nutzung am eigenen Rechner ändert sich gegenüber MIT nichts.
