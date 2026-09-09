import hashlib
from pathlib import Path

# Canonical extension sets, single source of truth shared with the parser.
PDF_EXTS = {".pdf"}
# Formats carrying directly extractable text (no PDF machinery needed).
TEXT_EXTS = {".txt", ".md"}
# Admitted so they are visible and flagged, but cqg cannot open them. Dropping them
# from the corpus would be a silent loss, which score-and-flag forbids.
UNSUPPORTED_EXTS = {".docx", ".pptx"}
SUPPORTED_EXTS = PDF_EXTS | TEXT_EXTS | UNSUPPORTED_EXTS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def triage_file(path: str) -> dict:
    p = Path(path)
    ext = p.suffix.lower()
    base = {"doc_id": p.stem, "type": ext.lstrip("."), "hash": _sha256(p), "path": str(p)}
    if ext in TEXT_EXTS:
        return {**base, "pages": None, "category": "text"}
    if ext not in PDF_EXTS:
        # Named rather than lumped with unreadable PDFs: "cqg cannot open this format"
        # is a different finding from "this PDF failed to extract".
        return {**base, "pages": None, "category": "unsupported_format"}
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
                # pypdf can raise on malformed PDFs; the image inventory stays best-effort.
                pass
    except Exception:
        # Unreadable/corrupted PDF: does not break corpus triage; flagged downstream.
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
    return [triage_file(str(f)) for f in sorted(Path(folder).iterdir())
            if f.suffix.lower() in SUPPORTED_EXTS]
