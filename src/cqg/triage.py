import hashlib
from pathlib import Path

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def triage_file(path: str) -> dict:
    p = Path(path)
    ext = p.suffix.lower()
    base = {"doc_id": p.stem, "type": ext.lstrip("."), "hash": _sha256(p), "path": str(p)}
    if ext != ".pdf":
        return {**base, "pages": None, "category": "non_pdf"}
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(p))
        pages = len(reader.pages)
        words, images = 0, 0
        for pg in reader.pages:
            words += len((pg.extract_text() or "").split())
            try:
                images += len(pg.images)
            except (KeyError, AttributeError, TypeError, ValueError, OSError):
                # pypdf peut lever sur des PDF mal formes ; l'inventaire d'images reste best-effort.
                pass
    except Exception:
        # PDF illisible/corrompu : ne casse pas le triage du corpus ; flague en aval.
        return {**base, "pages": None, "category": "unreadable"}
    wpp = words / pages if pages else 0
    ipp = images / pages if pages else 0
    if wpp < 10:
        cat = "scanned"
    elif wpp > 100 and ipp < 25:
        cat = "born_digital"
    else:
        cat = "mixed"
    return {**base, "pages": pages, "category": cat}

def triage_corpus(folder: str) -> list[dict]:
    exts = {".pdf", ".docx", ".pptx", ".txt", ".md"}
    return [triage_file(str(f)) for f in sorted(Path(folder).iterdir())
            if f.suffix.lower() in exts]
