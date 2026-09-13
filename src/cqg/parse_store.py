# src/cqg/parse_store.py
"""Read and write of `parsed_input/`: the boundary between parsing and scoring.

One parsed document = two files side by side:

- `<doc_id>.md`         the markdown as it will be ingested into RAG, editable by hand;
- `<doc_id>.parse.json` the sidecar (blocks, images, parse confidence, provenance).

The sidecar is not optional. `na_decisions` counts blocks, so a markdown without its
sidecar would see zero table and zero image and flip the structure criteria to `na` --
the score would move for a reason foreign to the quality of the document.

Bytes in, bytes out. The markdown is written and read as UTF-8 bytes, never through
universal-newline decoding: a stray CR silently rewritten as LF would change the very
string `non_alpha_fraction`, `token_count` and `duplicate_line_fraction` are computed on.
No trailing newline is added either, for the same reason.
"""
import hashlib
import re
from pathlib import Path
from typing import NamedTuple

from .models import Block, ParsedDoc, ParsedDocFile, ParseProvenance
from .triage import SUPPORTED_EXTS

MD_SUFFIX = ".md"
SIDECAR_SUFFIX = ".parse.json"

# Bumped whenever the sidecar gains a field a previous cqg cannot honour. Checked on
# read: a sidecar written by a newer version is flagged rather than silently
# half-understood, which is how a field nobody reads becomes a field nobody trusts.
SIDECAR_SCHEMA_VERSION = 1

# Raw source formats that can never be a `parsed_input/` output. `.md` is deliberately
# absent: it is both a supported source format and the output of parsing, so its
# presence alone says nothing about which kind of folder this is.
_RAW_ONLY_EXTS = SUPPORTED_EXTS - {MD_SUFFIX}


class ParsedEntry(NamedTuple):
    doc: ParsedDoc
    sidecar: ParsedDocFile | None
    flags: list[str]


def markdown_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def sidecar_path(md_path: str | Path) -> Path:
    p = Path(md_path)
    return p.with_name(p.stem + SIDECAR_SUFFIX)


def markdown_path(out_dir: str | Path, doc_id: str) -> Path:
    return Path(out_dir) / f"{doc_id}{MD_SUFFIX}"


def write_parsed_doc(doc: ParsedDoc, out_dir: str, provenance: ParseProvenance) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_file = markdown_path(out, doc.doc_id)
    md_file.write_bytes(doc.markdown.encode("utf-8"))
    side = ParsedDocFile(doc_id=doc.doc_id, markdown_hash=markdown_hash(doc.markdown),
                         parse_confidence=doc.parse_confidence, blocks=doc.blocks,
                         images=doc.images, provenance=provenance)
    side_file = sidecar_path(md_file)
    side_file.write_text(side.model_dump_json(indent=2), encoding="utf-8")
    return {"markdown": str(md_file), "sidecar": str(side_file)}


def is_parsed_doc_present(out_dir: str, doc_id: str) -> bool:
    md_file = markdown_path(out_dir, doc_id)
    return md_file.exists() and sidecar_path(md_file).exists()


def read_sidecar(md_path: str | Path) -> ParsedDocFile | None:
    side = sidecar_path(md_path)
    if not side.exists():
        return None
    return ParsedDocFile.model_validate_json(side.read_text(encoding="utf-8"))


def _load_sidecar(md_path: Path) -> tuple[ParsedDocFile | None, list[str]]:
    # A sidecar truncated or hand-edited into invalid JSON is a degraded document, not
    # a reason to lose the whole corpus: read what is left, flag the rest.
    try:
        return read_sidecar(md_path), []
    except Exception:
        return None, ["invalid_sidecar"]


def blocks_from_markdown(markdown: str, typed: list[Block]) -> list[Block]:
    """Text blocks re-derived from an edited markdown, typed blocks kept as parsed.

    Refines decision Q11, which said "recompute the blocks from the markdown". Taken
    literally that would return prose blocks only, and a document whose tables and
    images are invisible in its text would lose them from the inventory -- exactly the
    drift Q2 forbids. Every non-text kind is therefore kept (table and image are the
    ones extraction produces today): they are facts about the SOURCE. Re-deriving them
    from the prose is impossible on the docling path, whose table blocks come from
    pdfplumber geometry and never appear as pipe tables in the markdown, and inventing
    them is the mistake `_direct_extraction` refuses to make for docx/pptx images. So
    the text is re-read from what the human wrote, the typing stays what parsing found.
    """
    kept = [b for b in typed if b.kind != "text"]
    # Split on blank lines, CRLF included: a hand-edited markdown is exactly the one
    # likely to come back from a Windows editor, where a plain "\n\n" split would see
    # a single paragraph. page=0 rather than page=1: after an edit the page a paragraph
    # came from is unknown, and 0 is the sentinel _docling_extraction and
    # _docx_extraction already use for that. Claiming page 1 would invent a location.
    kept += [Block(kind="text", text=para.strip(), page=0)
             for para in re.split(r"(?:\r?\n){2,}", markdown) if para.strip()]
    return kept


def read_parsed_doc(md_path: str | Path) -> ParsedEntry:
    p = Path(md_path)
    doc_id = p.stem
    side, degraded = _load_sidecar(p)
    if not p.exists():
        # Orphan sidecar: the markdown was moved or deleted. Surfaced as an empty
        # document so the caller flags it, never as a document that quietly vanishes.
        doc = ParsedDoc(doc_id=doc_id, markdown="",
                        blocks=(side.blocks if side else []),
                        parse_confidence=(side.parse_confidence if side else 0.0),
                        images=(side.images if side else []))
        return ParsedEntry(doc=doc, sidecar=side, flags=["missing_markdown"])
    # errors="replace" rather than a raised exception, same precedent as
    # _plain_text_extraction: a markdown re-saved in another encoding becomes U+FFFD,
    # which cid_failure_fraction counts and flags, instead of losing the document.
    markdown = p.read_bytes().decode("utf-8", errors="replace")
    if side is None:
        # A markdown dropped in by hand is a real document, scored with what can be
        # read from it. Flagged because its inventory is prose-only: no table, image
        # or formula was ever parsed, so the structure criteria will fall to `na`.
        doc = ParsedDoc(doc_id=doc_id, markdown=markdown,
                        blocks=blocks_from_markdown(markdown, []),
                        parse_confidence=0.0, images=[])
        return ParsedEntry(doc=doc, sidecar=None, flags=degraded or ["missing_sidecar"])
    flags: list[str] = []
    if side.schema_version > SIDECAR_SCHEMA_VERSION:
        flags.append(f"sidecar_schema_unsupported:{side.schema_version}")
    blocks = side.blocks
    if markdown_hash(markdown) != side.markdown_hash:
        flags.append("manually_edited")
        blocks = blocks_from_markdown(markdown, side.blocks)
    if side.doc_id and side.doc_id != doc_id:
        # The file name wins, because it is what parsed_markdown_paths indexes and what
        # names the score file. A renamed or duplicated pair would otherwise report
        # under the original doc_id -- and two copies would overwrite one another's
        # score. Flagged rather than silently reconciled.
        flags.append(f"renamed:{side.doc_id}")
    doc = ParsedDoc(doc_id=doc_id, markdown=markdown, blocks=blocks,
                    parse_confidence=side.parse_confidence, images=side.images)
    return ParsedEntry(doc=doc, sidecar=side, flags=flags)


def parsed_markdown_paths(folder: str) -> list[Path]:
    """Every entry of a parsed_input/, orphan sidecars included, in stable order."""
    d = Path(folder)
    stems = {p.stem for p in d.glob(f"*{MD_SUFFIX}")}
    stems |= {p.name[:-len(SIDECAR_SUFFIX)] for p in d.glob(f"*{SIDECAR_SUFFIX}")}
    # Sorted on the file name, not the stem, to match triage_corpus, which sorts raw
    # sources the same way. Ordering drives the row order of corpus_report.xlsx and the
    # grouping of corpus_redundancy.json, neither of which should depend on the path taken.
    return sorted((markdown_path(d, s) for s in stems), key=lambda p: p.name)


def is_parsed_input(folder: str) -> bool:
    """True if the folder holds parsed documents rather than raw sources.

    Raises on a folder holding both: scoring it as raw would re-parse the markdown
    exports and ignore the sidecars, scoring it as parsed would drop the sources.
    A loud failure beats silently picking one of the two.
    """
    d = Path(folder)
    if not d.is_dir():
        return False
    sidecars = sorted(p.name for p in d.glob(f"*{SIDECAR_SUFFIX}"))
    if not sidecars:
        return False
    raw = sorted(p.name for p in d.iterdir()
                 if p.is_file() and p.suffix.lower() in _RAW_ONLY_EXTS)
    if raw:
        raise ValueError(
            f"Dossier ambigu: {folder} contient a la fois des documents parses "
            f"({', '.join(sidecars[:3])}) et des sources brutes ({', '.join(raw[:3])}). "
            "Separez raw_input/ et parsed_input/.")
    return True
