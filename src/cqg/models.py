from typing import Literal
from pydantic import BaseModel

Status = Literal["scored", "na", "not_evaluated"]

class Block(BaseModel):
    kind: str
    text: str = ""
    page: int = 0
    section: str | None = None

class ImageRef(BaseModel):
    page: int
    idx: int
    x0: float
    top: float
    x1: float
    bottom: float
    placeholder: str

class ParsedDoc(BaseModel):
    doc_id: str
    markdown: str
    blocks: list[Block]
    parse_confidence: float
    images: list["ImageRef"] = []

class ParseProvenance(BaseModel):
    # What produced the parsed document, anchored on the source bytes. No timestamp:
    # parsed_input/ is a human-editable, reviewable artefact, and a clock value would
    # turn every --force re-parse into a diff nobody can read.
    parser: str
    source_name: str
    source_type: str
    source_sha256: str
    source_pages: int | None = None
    category: str = ""
    enriched: bool = False

class ParsedDocFile(BaseModel):
    # Sidecar of a parsed_input/ entry: everything a ParsedDoc carries EXCEPT the
    # markdown, which lives next to it in <doc_id>.md so a human can edit it.
    # markdown_hash is that file's sha256, which is how a hand edit is detected.
    schema_version: int = 1
    doc_id: str
    markdown_hash: str
    parse_confidence: float
    blocks: list[Block]
    images: list[ImageRef] = []
    provenance: ParseProvenance

class CriterionScore(BaseModel):
    id: str
    tag: Literal["D", "H", "L"]
    weight: int
    status: Status
    score: int | None = None
    justification: str
    evidence: str | None = None

class DocScore(BaseModel):
    doc_id: str
    global_pct: float
    level: str
    coverage_pct: float
    dimensions: dict[str, float]
    criteria: list[CriterionScore]
    worst_sections: list[str] = []
    flags: list[str] = []
    config_hash: str
