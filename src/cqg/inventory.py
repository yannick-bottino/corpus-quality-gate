# src/cqg/inventory.py
import re
from .models import ParsedDoc
from .registry.loader import Registry

_IMG = {"3.1", "3.2", "3.3"}
_FIG = {"3.3"}
_TAB = {"3.4", "3.8", "3.9"}
_FORM = {"3.6"}
_LINK = {"3.5"}

def block_inventory(doc: ParsedDoc) -> dict:
    kinds = [b.kind.lower() for b in doc.blocks]
    return {
        "tables": sum("table" in k for k in kinds),
        "figures": sum("figure" in k or "picture" in k for k in kinds),
        "images": sum("image" in k or "picture" in k or "figure" in k for k in kinds),
        "formulas": sum("formula" in k or "equation" in k for k in kinds),
        "links": len(re.findall(r"\]\(", doc.markdown)) + len(re.findall(r"(?<!\]\()https?://", doc.markdown)),
        "sections": sum(k in ("title", "section_header", "heading") for k in kinds),
    }

def na_decisions(doc: ParsedDoc, reg: Registry) -> set[str]:
    inv = block_inventory(doc)
    na: set[str] = set()
    if inv["images"] == 0:
        na |= _IMG | _FIG
    if inv["tables"] == 0:
        na |= _TAB
    if inv["formulas"] == 0:
        na |= _FORM
    if inv["links"] == 0:
        na |= _LINK
    valid = {c.id for c in reg.criteria if c.na_possible}
    return na & valid
