"""Markdown-Export: übersetztes Buch als .md (Überschriften, Absätze, Bilder).

Das MD ist die **korrigierbare Quelle** für den Neu-Satz (`tuxbook md2pdf`) —
deshalb erzeugt der Export direkt ein lesbares, sauberes Markdown:

  - Absätze, die im Original über Seitengrenzen laufen, werden zusammengeführt
    (keine „…“-Marker im Text — das PDF-Rendering bricht selbst sauber um)
  - Kapitel-Blobs wie „§9 POLITIK FÜR … Lassen Sie uns …“ (Nummer, Titel und
    Body in einem Absatz) werden in §-Nummer + Kapitel-h2 + Body zerlegt
  - „§n“-Kapitelnummer + Kapitelüberschrift verschmelzen zu einer H2-Zeile
  - Kapitel ohne §-Nummer im Seitentext (nur ALL-CAPS-Überschrift) werden
    über den Titel-Abgleich mit dem Inhaltsverzeichnis identifiziert und
    erhalten ihre §-Nummer; alle weiteren Vorkommen desselben Titels sind
    laufende Kolumnentitel (Druck-Furniture) und werden verworfen
  - Zeilen der Titelseite (Autor, Untertitel, Verlag, Jahr) bleiben Fließtext
    und zerlegen sich nicht als Pseudo-Kapitel-Überschriften
  - freistehende Seitenzahl-Artefakte („14“, „ix“) werden verworfen
  - Überschriften erhalten ihre Übersetzung (Index-Ausrichtung zum Cache)
  - Bilder werden an ihrer Seitenposition eingebettet und können im MD
    von Hand verschoben werden

Speicherarm: items = [(pno, page_count, [(kind, text, size)])] statt
PageData-Objekten — auch für 1000-Seiten-Bücher geeignet.
"""
from __future__ import annotations

import re
from pathlib import Path

from .extract import ends_sentence


def _uninline(t: str) -> str:
    return t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


_PAGE_NUM_RE = re.compile(r"^\d{1,3}$")           # freistehende Seitenzahl
_ROMAN_PAGE_RE = re.compile(r"^[ivxlcdm]{1,6}$")  # Kleinbuchstaben-römisch
_SEC_LINE_RE = re.compile(r"^§\s*\d{1,3}\.?$")    # solo „§1“ / „§ 1.“
_SEC_HEAD_RE = re.compile(r"^§\s*(\d{1,3})\.?\s*(.*)$")
# Kapitel-Blob: „§9 POLITIK …“ (Nummer, LEERZEICHEN, Großbuchstaben-Titel;
# TOC-Zeilen haben einen Punkt direkt nach der Zahl und treffen nicht zu)
_SEC_SPLIT_RE = re.compile(r"^(§\s*\d{1,3})\s+([A-ZÄÖÜ].*)$")
# ALL-CAPS-Titel gefolgt von Fließtext (Kapiteltitel + Body in einem Absatz)
_CAPS_BODY_RE = re.compile(
    r"^([A-ZÄÖÜ][A-ZÄÖÜ\s.,;:!?'’&\-–—/]*[A-ZÄÖÜ.!?])\s+([a-zäöü].*)$")
_ALLCAPS_RE = re.compile(r"^[A-ZÄÖÜ][A-ZÄÖÜ0-9\s.,;:!?''&\-–—/()]{1,79}$")
_TOC_END_RE = re.compile(r"\.{3,}\s*\d{1,4}\s*$")
# TOC-Zeile: „§7. Föderation .... 89“ (auch „§9. Titel. 122“ ohne Punkte)
_TOC_LINE_RE = re.compile(
    r"^§\s*(\d{1,3})\.?\s+(.+?)(?:\s*\.{3,}|\.\s+|\s+)\d{1,4}\s*$")


def _norm_title(t: str) -> str:
    """Titel normalisieren für den TOC-Abgleich: §-Präfix weg, Gross-/Klein-
    schreibung egal, Punkte/Leerzeichen kollabiert."""
    s = t.strip()
    m = _SEC_HEAD_RE.match(s)
    if m:
        s = m.group(2)                # nur den §-Präfix abtrennen
    s = re.sub(r"\s+", " ", s).strip(" .,;:")
    return s.upper()


def _title_tokens(norm: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß]+", norm.lower())
            if len(w) > 2}


def _match_toc(norm: str, toc_norms: list[str]) -> str | None:
    """Exakter Titel-Match, sonst toleranter Token-Überlappungs-Match
    (Jaccard ≥ 0.6) — fängt Übersetzungs-Varianten wie „die neue Art“
    vs. „der neue Typus“ ab."""
    if norm in toc_norms:
        return norm
    want = _title_tokens(norm)
    if not want:
        return None
    best, best_j = None, 0.0
    for cand in toc_norms:
        have = _title_tokens(cand)
        if not have:
            continue
        j = len(want & have) / len(want | have)
        if j > best_j:
            best, best_j = cand, j
    return best if best_j >= 0.6 else None


def _open_end(t: str, pno: int, scope: set, max_ref: int) -> bool:
    """Absatz läuft ohne Satzende über die Seitengrenze? Kaps-Zeilen
    (Kapiteltitel/Kolumnentitel) und Zahl-Abschlüsse (TOC) nie verkleben."""
    return (not ends_sentence(t) and pno < max_ref
            and (pno + 1) in scope
            and not re.search(r"\d\s*$", t)
            and not _ALLCAPS_RE.match(t))


def md_blocks(items, translated: dict[int, list[str]],
              image_map: dict | None = None,
              scope: set | None = None) -> list[tuple[str, str]]:
    """Items + Übersetzungen → saubere MD-Blockliste [(typ, text)].

    typ: 'h2' (Kapitel) | 'p' (Absatz) | 'img' (relativer Bildpfad)
    items: [(pno, page_count, [(kind, text, size), ...]), ...]  (pno aufsteigend)
    translated: pno -> [Absatztexte]  (Index-ausgerichtet zu den Paras)
    scope: tatsächlich gerenderte Seiten — Absätze werden nur dann mit der
    Folgeseite verschmolzen, wenn diese ebenfalls im Scope liegt.
    """
    image_map = image_map or {}
    scope = set(scope) if scope is not None else {pno for pno, _, _ in items}
    max_ref = max(scope) if scope else -1

    # 1) Rohe Blöcke; Kapitel-Blobs sofort zerlegen --------------------------
    raw: list[list] = []  # [typ, text, open_end]
    for pno, _page_count, paras in items:
        for img in image_map.get(pno, []):
            raw.append(["img", img["file"], False])
        tr = translated.get(pno, [])
        for i, (kind, text, _size) in enumerate(paras):
            tr_t = tr[i] if i < len(tr) else text
            if kind == "heading":
                txt = _uninline(tr_t).strip()
                if txt:
                    raw.append(["h2", txt, False])
                continue
            t = _uninline(tr_t).strip()
            if not t:
                continue
            ms = _SEC_SPLIT_RE.match(t)
            if ms and not _TOC_END_RE.search(t):
                rest = ms.group(2).strip()
                mb = _CAPS_BODY_RE.match(rest)
                if _ALLCAPS_RE.match(rest) or mb:
                    # „§9 POLITIK FÜR … Lassen Sie uns …“
                    # → §-Nummer + Kapiteltitel + Body
                    raw.append(["p", ms.group(1).strip(), False])
                    if mb:
                        raw.append(["p", mb.group(1).strip(), False])
                        body = mb.group(2).strip()
                        raw.append(["p", body,
                                    _open_end(body, pno, scope, max_ref)])
                    else:
                        raw.append(["p", rest, False])
                    continue
            raw.append(["p", t, _open_end(t, pno, scope, max_ref)])

    # 2) Absätze an Seitengrenzen zusammenführen -----------------------------
    #    Nicht in ALL-CAPS-Zeilen hineinverkleben (Kapitel-/Kolumnentitel)
    merged: list[list] = []
    for typ, text, open_end in raw:
        prev = merged[-1] if merged else None
        if (prev is not None and prev[0] == "p" and typ == "p" and prev[2]
                and not _ALLCAPS_RE.match(text)):
            if prev[1].endswith(("-", "¬")):      # Trennstrich-Artefakt
                prev[1] = prev[1].rstrip("-¬") + text
            else:
                prev[1] += " " + text
            prev[2] = open_end
            continue
        merged.append([typ, text, open_end])

    # 3) TOC-Zeilen, in denen das LLM zwei Einträge verschmolz, trennen ------
    step: list[list] = []
    for typ, text, o in merged:
        if typ == "p" and _TOC_END_RE.search(text):
            parts = [p.strip() for p in re.split(r"(?=\s§\s*\d{1,3}\.)", text)
                     if p.strip()]
            step.extend(["p", pt, False] for pt in parts)
            continue
        step.append([typ, text, o])
    merged = step

    # 4) „§n“ + Titel → Kapitel-h2 -------------------------------------------
    fused: list[list] = []
    j = 0
    while j < len(merged):
        typ, text, o = merged[j]
        if (typ == "p" and _SEC_LINE_RE.match(text)
                and j + 1 < len(merged)):
            ntyp, ntext, _ = merged[j + 1]
            if ntyp == "h2" or (ntyp == "p" and _ALLCAPS_RE.match(ntext)):
                combined = f"{text.rstrip('.')} {ntext}".strip()
                m = _SEC_HEAD_RE.match(combined)
                if m and m.group(2):
                    combined = f"§{m.group(1)}. {m.group(2)}"
                fused.append(["h2", combined, False])
                j += 2
                continue
        fused.append([typ, text, o])
        j += 1

    # 5) TOC-Titel-Map: Kapitel ohne §-Nummer im Text identifizieren ---------
    toc_titles: dict[str, str] = {}   # normierter Titel → „§n. Titel“
    for typ, text, _o in fused:
        if typ != "p":
            continue
        m0 = re.match(r"^§\s*(\d{1,3})\.?\s+(.+)$", text)
        if not m0 or _SEC_SPLIT_RE.match(text):
            continue      # Kapitel-Blob-Start („§9 TITEL …“) — kein TOC-Eintrag
        # Seitenzahl abschneiden: „Titel .... 89“ / „Titel. 122“ / ohne Zahl
        title = re.sub(r"(?:\s*\.{3,}|\.)\s*\d{1,4}\s*$", "",
                       m0.group(2)).strip(" .")
        if 0 < len(title) <= 80:
            toc_titles[_norm_title(title)] = f"§{m0.group(1)}. {title}"

    # 6) Kapitel-h2 festigen, Kolumnentitel verwerfen ------------------------
    #    - h2/Caps-Zeile, deren Titel im TOC steht: erstes Vorkommen = echter
    #      Kapitelanfang (→ h2 mit §-Nummer), weitere = laufender Kolumnentitel
    #    - Caps-Zeile OHNE TOC-Bezug, die ≥ 2× vorkommt (Buchtitel als
    #      Kolumnentitel): komplett verwerfen (Titel steht im Frontmatter)
    counts: dict[str, int] = {}
    for typ, text, _o in fused:
        if typ == "h2" or (typ == "p" and _ALLCAPS_RE.match(text)):
            counts[text] = counts.get(text, 0) + 1
    seen_toc: set[str] = set()
    toc_norms = list(toc_titles.keys())
    # §-Nummer → kanonischer TOC-Titel (Nummern-Match schlägt Token-Match:
    # scan-verdorbene Titel wie „GLAS-KRIEG“ sind über die Nummer eindeutig)
    toc_by_num: dict[str, str] = {}
    toc_num_by_norm: dict[str, str] = {}
    for v in toc_titles.values():
        mnum = re.match(r"^§\s*(\d{1,3})\.", v)
        if mnum:
            toc_by_num[mnum.group(1)] = v
            toc_num_by_norm[_norm_title(re.sub(r"^§\s*\d{1,3}\.?\s*", "", v))] = mnum.group(1)
    final: list[list] = []
    for typ, text, o in fused:
        if typ == "h2" or (typ == "p" and _ALLCAPS_RE.match(text)
                           and not _SEC_LINE_RE.match(text)):
            key, new_text = None, text
            mnum = _SEC_HEAD_RE.match(text)
            if mnum and mnum.group(2).strip() and mnum.group(1) in toc_by_num:
                key = mnum.group(1)          # Nummern-Match — verlässlich
                new_text = toc_by_num[key]
            else:
                norm = _norm_title(text)
                k2 = _match_toc(norm, toc_norms) if norm else None
                if k2:
                    new_text = toc_titles[k2]
                    key = toc_num_by_norm.get(k2, k2)   # Key = Kapitelnummer
            if key:
                if key in seen_toc:
                    continue                 # Kolumnentitel — verwerfen
                seen_toc.add(key)
                final.append(["h2", new_text, False])
                continue
            if counts.get(text, 0) >= 2:     # Buchtitel als Kolumnentitel
                continue
            final.append(["h2" if typ == "h2" else "p", text, o])
            continue
        final.append([typ, text, o])
    fused = final

    # 7) Erster §-Kapitelbeginn: alles davor ist Titelseite/Frontmatter ------
    first_sec = next((i for i, b in enumerate(fused)
                      if b[0] == "h2" and _SEC_HEAD_RE.match(b[1])), None)

    # 8) Ausgeben -------------------------------------------------------------
    out: list[tuple[str, str]] = []
    for i, (typ, text, _o) in enumerate(fused):
        if typ == "h2":
            if first_sec is not None and i < first_sec:
                out.append(("p", text))           # Titelseiten-Zeile
            else:
                out.append(("h2", text))
            continue
        if typ == "img":
            out.append(("img", text))
            continue
        if _PAGE_NUM_RE.match(text) or _ROMAN_PAGE_RE.match(text):
            continue                              # Seitenzahl-Artefakt
        out.append(("p", text))
    return out


def render_markdown(items, translated: dict[int, list[str]], out_path: Path,
                    title: str | None = None, image_map: dict | None = None,
                    render_scope: set | None = None):
    """Schreibt das übersetzte Buch als Markdown (Quelle für `tuxbook md2pdf`)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    blocks = md_blocks(items, translated, image_map=image_map,
                       scope=render_scope)

    lines: list[str] = []
    if title:
        lines.append(f"# {title}\n")
    for typ, text in blocks:
        if typ == "img":
            lines.append(f"![Bild](<{text}>)\n")
        elif typ == "h2":
            lines.append(f"## {text}\n")
        else:
            lines.append(f"{text}\n")

    # Leerzeilen-Normalisierung: max. 1 Leerzeile hintereinander
    clean: list[str] = []
    blank = 0
    for ln in lines:
        if ln.strip() == "":
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        clean.append(ln)

    out_path.write_text("\n".join(clean).rstrip() + "\n", encoding="utf-8")
