---
type: process-boundary
title: The raw_input / parsed_input Boundary
description: The persisted artifact that separates parsing from scoring — cqg parse turns raw sources into an editable parsed_input/, run and golden auto-detect which kind of folder they were given, and a hand edit of the extracted markdown is a first-class case rather than an accident.
tags: [parsing, boundary, parsed-input, human-in-the-loop, byte-exactness, provenance, non-regression]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-11T15:09:34.136Z
sources:
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-c8d879f00ddd07aa3b1256db
    resource: repo://src/cqg/models.py
  - id: openwiki-source-4d169df8f5a62ba2edae177b
    resource: repo://src/cqg/parse_store.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-e0c57be84bf0b2495447ad1f
    resource: repo://tests/test_cli_parse.py
  - id: openwiki-source-c6b71c8e750f25bb45856882
    resource: repo://tests/test_parse_store.py
  - id: openwiki-source-150acf1471520418887f0cfe
    resource: repo://tests/test_regression_parse_run.py
generated: { by: "claude-code", at: "2026-09-11T15:09:34.136Z" }
---

# The raw_input / parsed_input Boundary

Parsing and scoring used to be one indivisible act: `cqg run <folder>` opened every source
file, extracted it in memory, and judged the result in the same pass. The extracted text —
the string that actually reaches a RAG index, and the string every quality signal is
computed on — existed only inside a process and was never anyone's to inspect or correct.

This boundary makes it an artifact. `cqg parse` writes it to disk in a form a human can
read and edit; `cqg run` and `cqg golden` then accept **either** kind of folder. The split
is deliberately inert: it introduces no LLM call of any kind, which is what makes the
[non-regression comparison](#the-non-regression-contract) below interpretable — anything
that moves, moves because of the split.

## The subcommand

```
cqg parse <raw_dir> --out <parsed_dir> [--enrich] [--force]
```

It reads a raw corpus through the same [triage](document-parsing.md) the scoring path uses,
extracts each document with the same `parse_document`, and writes the result as two files.
The subcommand refuses two situations before writing anything:

- **the input is already a `parsed_input/`** — `<corpus_dir> est deja un parsed_input/ :
  rien a parser.`;
- **the output folder is the input folder** — writing the parsed markdown beside its own
  sources would make the folder ambiguous for every later command, so this fails rather
  than creating the mess it would then have to detect.

A third refusal comes from the corpus itself. `doc_id` is the file **stem**, so
`rapport.docx` sitting next to its PDF export — an ordinary shape for a client corpus —
would both claim `rapport.md`. One would be silently skipped as "already parsed", and
`--force` would overwrite rather than recover it. There is no honest way to pick a winner,
so the whole command fails before any file is written, naming both paths.

## Two files per document

| File | Role |
|---|---|
| `<doc_id>.md` | The markdown **as it will be ingested into RAG**. Editable by hand — that is the point |
| `<doc_id>.parse.json` | The sidecar: `blocks`, `images`, `parse_confidence`, `markdown_hash`, `schema_version` and `provenance` |

The division is the whole design. The markdown is the part a human has an opinion about; the
sidecar is the part parsing knows and prose cannot express.

**The sidecar is not optional.** The deterministic inventory counts *blocks* to decide which
criteria do not apply: a document with no table cannot be judged on its tables, so those
criteria become `na`. A markdown read without its sidecar would show zero tables and zero
images, flip the structure criteria to `na`, and move the document's score — for a reason
that has nothing to do with the quality of the document. That is exactly the drift the
[anti-fabrication invariants](../architecture/anti-fabrication-and-flagging.md) forbid, so a
markdown found alone is scored but **flagged**.

### Provenance carries no clock

`ParseProvenance` records the parser used, the source's name, type, `source_sha256` and page
count, the triage category, and whether enrichment ran. It deliberately records **no
timestamp**. `parsed_input/` is a reviewable, hand-editable artefact, and a clock value would
turn every `--force` re-parse into a diff nobody can read. Everything in the provenance is
anchored on the source bytes instead.

## Byte-exactness is the contract

The markdown is written with `write_bytes` on a UTF-8 encoding, and read back with
`read_bytes().decode("utf-8")` — never through universal-newline decoding, and no trailing
newline is appended.

This is not fastidiousness. That exact string is what `non_alpha_fraction`, `token_count`
and `duplicate_line_fraction` are computed on. A stray `\r` silently rewritten as `\n` on the
way in or out would shift all three, and the shift would surface as a score that moved for
no visible reason. A test asserts the round trip byte for byte, and a second one asserts
that the markdown scored on the split path is identical to the one a direct run scores —
because discovering a lost CR through a score diff costs hours, and discovering it here costs
one line.

Document identifiers survive the round trip unmangled too, spaces, accents and parentheses
included — `Le Cahier Ma Santé (AGA - AEP)` is a real corpus filename, not a hypothetical.

## Mode detection

`run` and `run_golden` do not take a flag saying which kind of folder they were handed. They
ask `is_parsed_input`, and the rule is deliberately narrow:

- a folder containing **at least one `*.parse.json`** is a `parsed_input/`;
- **a `.md` file never decides it.** `.md` is both a supported *source* format and the
  *output* of parsing, so its presence says nothing. A folder of hand-written notes is a
  perfectly legitimate raw corpus and stays one;
- a folder containing **both** sidecars and raw sources **raises**:
  `Dossier ambigu: <folder> contient a la fois des documents parses (...) et des sources
  brutes (...). Separez raw_input/ et parsed_input/.`

The last rule is the interesting one. Scoring such a folder as raw would re-parse the
markdown exports and ignore the sidecars; scoring it as parsed would drop the sources
entirely. Both are wrong, and neither is visibly wrong in the output. A loud failure beats
silently picking one of the two.

On a `parsed_input/`, scoring opens **no source file at all** — the markdown and its sidecar
are the whole input. Entries are listed sorted on the *file name* rather than the stem, to
match the order `triage_corpus` gives raw sources: that ordering drives the row order of
`corpus_report.xlsx` and the grouping of `corpus_redundancy.json`, neither of which should
depend on which path the corpus took.

## Reading an entry back

Reading is total: every state a folder can be in produces a document and a list of flags,
never an exception.

| Situation | Result |
|---|---|
| Markdown and sidecar agree | Scored normally, no flag |
| `markdown_hash` mismatch | `manually_edited`; text blocks recomputed, typed blocks kept |
| Markdown with no sidecar | `missing_sidecar`; scored on its prose, inventory prose-only |
| Sidecar with no markdown | `missing_markdown`; surfaced as an empty document, never dropped |
| Sidecar that is not valid JSON | `invalid_sidecar`; read with what is left |
| `schema_version` newer than this `cqg` | `sidecar_schema_unsupported:<n>` |
| Sidecar `doc_id` ≠ file name | `renamed:<original_doc_id>` |

An orphan sidecar is still *listed* by the folder walk, which is what makes
`missing_markdown` reachable at all: a document whose markdown was moved or deleted has to
be reported, not quietly absent from the report.

A markdown re-saved in another encoding is decoded with `errors="replace"`, so the damage
becomes U+FFFD — which `cid_failure_fraction` already counts, penalising `parse_confidence`
and flagging the document. That is the same precedent `_plain_text_extraction` set for
`.txt`/`.md` sources. Note the consequence: a re-encoded file is *also* a hash mismatch, so
it arrives flagged `manually_edited` as well, which is accurate — the file did change.

### Why the file name wins on a rename

When the sidecar's recorded `doc_id` disagrees with the file name, the **file name wins**,
and the original is reported as `renamed:<original_doc_id>`. Duplicating a parsed pair to
edit a variant is a natural human move; if the sidecar's `doc_id` won, both variants would
write the same `<doc_id>.score.json` and one would silently overwrite the other. The file
name is what indexes the folder and what names the score file, so it is what identity has to
follow. The disagreement is flagged rather than silently reconciled.

### Documents that were never scorable still cross

An `unsupported_format` document is written as an entry with an **empty markdown**, its
category preserved in the provenance. `run` reads that category back and raises
`unsupported_format:<type>` exactly as it would have on the raw folder. An unreadable
document crosses the same way and lands as `unreadable`. Splitting the pipeline must not be
how a document disappears from a report.

## The hand edit is a first-class case

The reason `<doc_id>.md` is a plain file is that someone is expected to fix it: a mangled
heading, a table that came out as prose, a paragraph the extractor split in the wrong place.
Two behaviours protect that work.

**Re-parsing never silently overwrites.** `parse` skips a document already present in the
output folder. The markdown may have been corrected by hand, and a silent re-parse would
throw that work away. `--force` is the explicit way to ask for the overwrite — and it is
meaningful only to `parse`, so passing it to `run` or `golden` says so and is ignored.

**A changed source is reported, never acted on.** On a skipped document, `parse` compares
the source's current sha256 with the one recorded in the provenance. A mismatch is collected
into `source_changed` and printed — `Source modifiee depuis le parsing (relancer avec
--force pour reparser): ...` — and nothing else happens. Choosing between the human's edit
and the new version of the source is the human's call, not the tool's.

**An edit rewrites the text, never the structure.** When the hash no longer matches, the
text blocks are recomputed from the markdown the human actually wrote, while every non-text
block — tables, images — and the image geometry are kept from the sidecar.

The reason is an anti-fabrication one. Re-deriving tables from prose is *impossible* on the
docling path: docling's table blocks come from pdfplumber geometry and never appear as pipe
tables in the markdown. And inventing them is precisely the mistake `_direct_extraction`
refuses to make for `.docx`/`.pptx` images. Between an inventory that is stale about one
human edit and an inventory that is fabricated, the code takes the first and says so with
`manually_edited`.

Two details of the recomputation follow the same discipline. Paragraphs are split on blank
lines **with CRLF accepted**, because a hand-edited markdown is exactly the one likely to
come back from a Windows editor, where a plain `\n\n` split would see one enormous
paragraph. And each recomputed block is given `page=0`, the sentinel the docling and docx
extractions already use: after an edit the page a paragraph came from is genuinely unknown,
and claiming page 1 would invent a location.

A test makes the consequence explicit rather than assumed: a `.docx` carrying a real table is
parsed, scored, then edited in its prose and scored again. The `manually_edited` flag
appears, the set of `na` criteria is *unchanged*, and the global score is identical — with a
second assertion confirming the table criteria were live in the first place, so the first
assertion cannot hold trivially.

## Enrichment moved with the parsing

[Image enrichment](image-enrichment.md) now runs inside `parse`, writing the enriched text
into `<doc_id>.md` and the crops under `<parsed_dir>/images/<doc_id>/`. Two reasons converge:
`enrich_document` needs the **source PDF** to crop from, and that is the file scoring must no
longer open; and `parsed_input/` is defined as the document *as it will be ingested*, which
is the enriched text.

The sidecar keeps the pre-enrichment blocks and image geometry — enrichment rewrites the
markdown only — and the provenance records `enriched: true`. A failing enrichment is caught
on its own and the entry is written un-enriched rather than lost.

`--enrich` therefore remains meaningful on `run` over a *raw* folder, and is refused with a
`RuntimeWarning` over a `parsed_input/`, where it has no object.

## Failures are reported, and the exit code says so

`parse` isolates each document, so one failure never costs the corpus. But `parsed_input/`
feeds the scoring step, which means a partial output that looks like a success is exactly how
a document silently disappears from a report. So `parse` prints every error it collected and
**exits non-zero**; a folder it refuses outright prints its explanatory message and exits with
its own distinct code. The messages are addressed to an operator and say what to do next,
which is worth more than a traceback.

## The non-regression contract

The split is only credible if it changes nothing. A dedicated regression test asserts that,
over a corpus of four documents — a text PDF, an illustrated PDF, a Markdown note and a
deliberately corrupt PDF — `parse` followed by `run <parsed_input>` produces `*.score.json`
files **strictly identical** to those of a direct `run <raw>`. It is parameterised over the
enriched and non-enriched cases, and the enriched case is the pointed one: the split run
scores with enrichment *off*, because `parse` did the enriching, so the equality is carried
entirely by the markdown `parse` wrote. The same equivalence has been verified on real PDFs.

That the lot introduces no LLM call is what makes the comparison mean something. With
judgment held fixed, any difference between the two paths could only have come from the
boundary itself.

## Related

- [Corpus Triage and Document Parsing](document-parsing.md) — the extraction this boundary persists
- [Image Enrichment](image-enrichment.md) — the stage that moved into `parse`
- [Anti-Fabrication and Score-and-Flag](../architecture/anti-fabrication-and-flagging.md) — the invariants the boundary flags serve
- [The run Pipeline](../workflows/run-pipeline.md) — the consumer that auto-detects the folder's mode
- [System Overview](../architecture/system-overview.md) — where the three subcommands sit
