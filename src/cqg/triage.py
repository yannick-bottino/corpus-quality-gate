import hashlib
from pathlib import Path

# Canonical extension sets, single source of truth shared with the parser.
PDF_EXTS = {".pdf"}
# Formats carrying directly extractable text (no PDF machinery needed).
TEXT_EXTS = {".txt", ".md"}
# Office formats: structured text extracted directly by python-docx / python-pptx,
# no PDF machinery and no conversion step.
OFFICE_EXTS = {".docx", ".pptx"}
SUPPORTED_EXTS = PDF_EXTS | TEXT_EXTS | OFFICE_EXTS


def _slide_count(path: Path) -> int | None:
    from pptx import Presentation
    try:
        return len(Presentation(str(path)).slides)
    except Exception:
        # Triage is an inventory, not an extraction verdict: an unreadable deck
        # degrades to an unknown page count here and gets its unreadable verdict
        # from the parser, uniformly with .docx (which triage never opens).
        return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def triage_file(path: str) -> dict:
    p = Path(path)
    ext = p.suffix.lower()
    base = {"doc_id": p.stem, "type": ext.lstrip("."), "hash": _sha256(p), "path": str(p)}
    if ext in TEXT_EXTS:
        return {**base, "pages": None, "category": "text"}
    if ext in OFFICE_EXTS:
        # `pages` feeds the per-page density check in parse confidence, so it must
        # only ever carry a real count. A deck has a true slide count; Word
        # pagination is a renderer artefact python-docx cannot report, and a
        # fabricated value would feed that check a meaningless number.
        return {**base, "pages": _slide_count(p) if ext == ".pptx" else None,
                "category": "office"}
    if ext not in PDF_EXTS:
        # Named rather than lumped with unreadable PDFs: "cqg cannot open this format"
        # is a different finding from "this document failed to extract". No shipped
        # extension lands here today; it is the honest landing for a format admitted
        # into SUPPORTED_EXTS ahead of its parser.
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
