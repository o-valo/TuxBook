"""Übersetzung seitenweise über den LLM Bahnhof — mit Verifikation & Resume."""
import hashlib
import json
import re
import time

from . import config
from .extract import PageData, ends_sentence
from .llm import BahnhofClient, OllamaClient, LLMError

_UNTRANSLATABLE = re.compile(r"^[\s\d\W]{0,8}$", re.UNICODE)


def _is_untranslatable(t: str) -> bool:
    """Reine Zahlen/puren Zeichensatz-Deko nicht an das LLM geben."""
    t = t.strip()
    if not t:
        return True
    if len(t) <= 6 and re.fullmatch(r"[-–—\s]*\d{1,4}[-–—\s]*", t):
        return True
    if not re.search(r"\w", t):
        return True
    return False


def _glossary_text(glossary: dict[str, str] | None) -> str:
    if not glossary:
        return ""
    lines = [f"- {k} -> {v}" for k, v in glossary.items()]
    return "\nGLOSSARY (use these translations exactly):\n" + "\n".join(lines)


def build_prompt(src_lang: str, tgt_lang: str, glossary: dict[str, str] | None) -> tuple[str, str]:
    system = (
        f"You are a professional book translator. Translate from {src_lang} "
        f"to {tgt_lang}. Preserve meaning, tone and register of a literary book. "
        "Keep names, numbers, URLs and inline emphasis markers (**bold**, *italic*) "
        "if present. Natural, fluent output in the target language.\n"
        "INPUT FORMAT: lines starting with 'Pn:' where n is a paragraph number.\n"
        "OUTPUT FORMAT: exactly one line per input paragraph, same numbering, "
        "e.g. 'P1: <translation>'. No extra lines, no commentary, no markdown."
        + _glossary_text(glossary)
    )
    return system, ""


def _parse_numbered(text: str, n_expected: int) -> dict[int, str]:
    out: dict[int, str] = {}
    for m in re.finditer(r"(?m)^\s*P(\d+)\s*:\s*(.+?)\s*$", text):
        i = int(m.group(1))
        if 1 <= i <= n_expected and m.group(2).strip():
            out.setdefault(i, m.group(2).strip())
    return out


def extract_terms(client: BahnhofClient, texts: list[str], tgt_lang: str,
                  max_terms: int = 25) -> dict[str, str]:
    """Terminologie-Lock: Eigennamen/Schlüsselbegriffe aus den ersten
    Buchseiten extrahieren und EINE konsistente Übersetzung festlegen."""
    sample = "\n\n".join(texts)[:6000]
    if len(sample.strip()) < 200:
        return {}
    out = client.chat(
        "You prepare a glossary for a book translation. From the following "
        "excerpt, list proper nouns, place names, organisations and recurring "
        f"key terms that need a consistent {tgt_lang} translation. Output ONLY "
        "lines 'term = translation', most important first, max "
        f"{max_terms} lines. Skip terms that remain identical in {tgt_lang}.",
        sample, temperature=0.1, max_tokens=1500)
    terms: dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip().lstrip("-•* ").strip('"')
        for sep in (" = ", " -> ", "="):
            if sep in line:
                a, b = line.split(sep, 1)
                a, b = a.strip(), b.strip()
                if a and b and len(a) < 60 and "\n" not in b:
                    terms.setdefault(a, b)
                break
    return terms


class _MiniBackend:
    """Übersetzungs-Backend über ein kleines Ollama-Modell (z.B.
    gemma3-translator, NLLB/MADLAD-artige Modelle). Ein Absatz pro Request,
    kein Reasoning-Overhead."""

    def __init__(self, ollama: OllamaClient, model: str, src: str, tgt: str,
                 terms: dict[str, str] | None = None):
        self.ollama = ollama
        self.model = model
        self.src = src
        self.tgt = tgt
        self.terms = terms or {}
        self.last_context = ""

    def translate_page(self, pd: PageData, prev_tail: list[str] | None = None,
                       next_head: list[str] | None = None) -> list[str] | None:
        src_paras = [p.text for p in pd.paras]
        if not src_paras:
            return []
        result = list(src_paras)
        got_any = False
        for i, t in enumerate(src_paras):
            if _is_untranslatable(t):
                continue
            ctx = ""
            if i == 0 and prev_tail:
                ctx = ("Context from the previous page (do NOT translate or "
                       "repeat): " + " ".join(prev_tail)[-300:] + "\n\n")
            gloss = ""
            if self.terms:
                gloss = ("GLOSSARY (use exactly these translations):\n"
                         + "\n".join(f"- {k} = {v}" for k, v in self.terms.items())
                         + "\n\n")
            try:
                out = self.ollama.chat(
                    f"{gloss}{ctx}Translate to {self.tgt}. Output ONLY the "
                    f"translation.\n\n{t}",
                    model=self.model, temperature=0.1)
            except LLMError as e:
                print(f"    WARN Mini-Modell: {e}")
                continue
            out = out.strip().strip('"')
            if out:
                result[i] = out
                got_any = True
            time.sleep(0.1)
        return result if got_any else None


class Translator:
    """Übersetzung über den LLM Bahnhof oder (Optional) ein Mini-Modell
    auf einem Ollama-Endpunkt (--engine ollama --ollama-model <name>)."""

    def __init__(self, client: BahnhofClient, src_lang: str, tgt_lang: str,
                 glossary: dict[str, str] | None = None, sleep: float = 0.0,
                 verbose: bool = True, mini_backend: "_MiniBackend | None" = None,
                 terms: dict[str, str] | None = None):
        self.client = client
        self.terms = terms or {}
        self.src = src_lang
        self.tgt = tgt_lang
        self.glossary = glossary
        self.sleep = sleep
        self.verbose = verbose
        self.mini = mini_backend
        self.system, _ = build_prompt(src_lang, tgt_lang, glossary)
        self.last_context = ""  # letzter übersetzter Absatz als Kontext

    # ------------------------------------------------------------------
    def translate_page(self, pd: PageData, prev_tail: list[str] | None = None,
                       next_head: list[str] | None = None) -> list[str] | None:
        if self.mini is not None:
            return self.mini.translate_page(pd, prev_tail, next_head)
        """Liefert die übersetzten Absätze einer Seite (Reihenfolge erhalten).
        Nicht übersetzbare Absätze werden 1:1 durchgereicht.
        Gibt None zurück, wenn das LLM komplett fehlgeschlagen ist
        (Seite gilt dann als 'nicht fertig' und wird beim Resume wiederholt)."""
        src_paras = [p.text for p in pd.paras]
        if not src_paras:
            return []

        idx_todo = [i for i, t in enumerate(src_paras) if not _is_untranslatable(t)]
        result = list(src_paras)
        if not idx_todo:
            return result

        numbered = "\n".join(f"P{i+1}: {src_paras[i]}" for i in idx_todo)
        parts = []
        if prev_tail:
            parts.append("END OF PREVIOUS PAGE: \"" + prev_tail[-1][-260:] + "\"")
        if next_head:
            parts.append("START OF NEXT PAGE: \"" + next_head[0][:200] + "\"")
        ctx = ""
        if parts:
            ctx = ("NEIGHBOR PAGE TEXT for continuity (do NOT translate or "
                   "repeat):\n" + "\n".join(parts) + "\n\n")
        gloss = ""
        if self.terms:
            gloss = ("GLOSSARY (use exactly these translations):\n"
                     + "\n".join(f"- {k} = {v}" for k, v in self.terms.items())
                     + "\n\n")
        user = (f"{gloss}{ctx}Translate these {len(idx_todo)} paragraphs to "
                f"{self.tgt}:\n\n" + numbered)

        est_tokens = int(sum(len(src_paras[i]) for i in idx_todo) * 1.5) + config.TOKEN_MARGIN

        parsed = self._ask(user, est_tokens)
        missing = [i for i in idx_todo if (i + 1) not in parsed]

        if missing:
            # 2. Versuch: strikter
            parsed2 = self._ask(
                user + "\n\nIMPORTANT: Output exactly P" + ", P".join(
                    str(i + 1) for i in idx_todo) + " lines. Nothing else.",
                est_tokens)
            parsed.update(parsed2)
            missing = [i for i in idx_todo if (i + 1) not in parsed]

        if missing:
            # Fallback: fehlende Absätze einzeln (zuverlässig, langsamer)
            if self.verbose:
                print(f"    {len(missing)} Absatz/Absätze einzeln nachübersetzen …")
            for i in missing:
                one = f"P1: {src_paras[i]}"
                p = self._ask(f"Translate this paragraph to {self.tgt}:\n\n{one}",
                              int(len(src_paras[i]) * 1.5) + config.TOKEN_MARGIN)
                if 1 in p:
                    parsed[i + 1] = p[1]
                time.sleep(0.3)

        got_any = False
        for i in idx_todo:
            if (i + 1) in parsed:
                result[i] = parsed[i + 1]
                self.last_context = parsed[i + 1][-300:]
                got_any = True

        if not got_any:
            return None  # LLM komplett fehlgeschlagen

        if self.sleep:
            time.sleep(self.sleep)
        return result

    def _ask(self, user: str, max_tokens: int) -> dict[int, str]:
        last_err = None
        for attempt in range(3):
            try:
                raw = self.client.chat(self.system, user,
                                       temperature=config.TEMPERATURE,
                                       max_tokens=max_tokens)
                return _parse_numbered(raw, 5000)
            except LLMError as e:
                last_err = e
                time.sleep(3 * (attempt + 1))
        if self.verbose:
            print(f"    WARN: LLM-Fehler nach 3 Versuchen: {last_err}")
        return {}


# ---------------------------------------------------------------------- Cache
def page_cache_key(job_id: str, pno: int, src_text: str, src: str, tgt: str,
                   glossary: dict | None, engine: str) -> str:
    h = hashlib.sha256()
    h.update(job_id.encode())
    h.update(str(pno).encode())
    h.update(src_text.encode("utf-8"))
    h.update(f"{src}>{tgt}>{engine}".encode())
    if glossary:
        h.update(json.dumps(glossary, sort_keys=True).encode())
    return h.hexdigest()[:16]


def save_page(pages_dir, pno: int, data: dict):
    p = pages_dir / f"p{pno:04d}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_page(pages_dir, pno: int) -> dict | None:
    p = pages_dir / f"p{pno:04d}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None
