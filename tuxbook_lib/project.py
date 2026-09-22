"""Job-Verwaltung: Verzeichnisse, Manifest, Resume, Seitenbereiche."""
import hashlib
import json
import time
from pathlib import Path

from . import config


class CleanError(RuntimeError):
    """Benutzerfreundlicher Fehler (ohne Traceback ausgeben)."""


def parse_ranges(spec: str | None, page_count: int) -> list[int]:
    """'1-50,60,71-80' -> Liste von 0-basierten Seitenindizes."""
    if not spec:
        return list(range(page_count))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a) - 1, int(b) - 1
            out.extend(range(max(0, lo), min(hi, page_count - 1) + 1))
        else:
            p = int(part) - 1
            if 0 <= p < page_count:
                out.append(p)
    return sorted(set(out))


class Job:
    def __init__(self, name: str):
        self.name = name
        self.dir = config.JOBS_DIR / name
        self.pages_dir = self.dir / "pages"
        self.manifest_path = self.dir / "manifest.json"

    def ensure(self, settings: dict, source_pdf: Path | None = None) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.pages_dir.mkdir(exist_ok=True)
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        man = {
            "job": self.name,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "settings": settings,
            "source": str(source_pdf) if source_pdf else None,
            "source_sha256": (sha256_file(source_pdf) if source_pdf else None),
        }
        self.manifest_path.write_text(json.dumps(man, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        return man

    def load_manifest(self) -> dict | None:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return None

    def done_pages(self) -> set[int]:
        """Fertige Seiten: übersetzt UND mit aktueller Extraktions-Version."""
        from .extract import EXTRACT_VERSION
        out = set()
        if self.pages_dir.exists():
            for f in self.pages_dir.glob("p*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    if d.get("trans") is not None \
                            and d.get("xver") == EXTRACT_VERSION:
                        out.add(int(d["page"]))
                except Exception:
                    pass
        return out

    def output_path(self) -> Path:
        return config.OUT_DIR / f"{self.name}_{self._mode()}.pdf"

    def _mode(self) -> str:
        man = self.load_manifest() or {}
        return (man.get("settings", {}).get("mode") or "page")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_glossary(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    g: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ("=" not in line and "->" not in line and "\t" not in line):
            continue
        for sep in ("->", "=", "\t"):
            if sep in line:
                a, b = line.split(sep, 1)
                g[a.strip()] = b.strip()
                break
    return g
