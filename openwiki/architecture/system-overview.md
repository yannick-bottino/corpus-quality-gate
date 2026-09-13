---
type: system-architecture
title: System Overview
description: What Corpus Quality Gate (cqg) is and how its parts fit together — a reference-free, document-level quality gate run before RAG ingestion, exposing parse, run and golden subcommands over a shared parsing, persistence and data-model layer.
tags: [architecture, overview, rag, document-quality, entrypoints, data-model]
sources:
  - id: openwiki-source-833e692518af9eeaf8564cc6
    resource: repo://main.py
  - id: openwiki-source-05ccef8d4cf1698187f20464
    resource: repo://pyproject.toml
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-f3702b5dc23472a869a57236
    resource: repo://src/cqg/enrich.py
  - id: openwiki-source-c8d879f00ddd07aa3b1256db
    resource: repo://src/cqg/models.py
  - id: openwiki-source-4d169df8f5a62ba2edae177b
    resource: repo://src/cqg/parse_store.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-f2e05a5624d52b19421cdd43
    resource: repo://src/cqg/triage.py
  - id: openwiki-source-15ffe11df9b60121e2241bb7
    resource: repo://tests/test_cli_e2e.py
generated: { by: "claude-code", at: "2026-09-11T15:09:34.136Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-11T15:09:34.136Z
---

# System Overview

**Corpus Quality Gate** (`cqg`) evaluates the *intrinsic* quality of documents **before**
they are ingested into a Retrieval-Augmented Generation pipeline. It answers a question
that comes earlier than retrieval quality: *is this corpus fit to be ingested at all?*

The target corpus is heterogeneous and multimodal digital PDFs, bilingual French/English.
Plain-text formats (`.txt`, `.md`) and office formats (`.docx`, `.pptx`) are scored
alongside them — every admitted extension has a parser behind it. Word and PowerPoint are
read directly with `python-docx` and `python-pptx`, which are declared dependencies, and
never routed through the PDF chain. See
[Corpus Triage and Document Parsing](../ingestion/document-parsing.md).

## What "reference-free and document-level" means

The evaluation requires **neither ground truth nor queries**. There is no expected-answer
set to compare against and no query workload to replay. Each document is scored on its own
observable properties — how cleanly it extracts, how it is structured, whether it carries
metadata, how well it would chunk — and the corpus verdict is an aggregation of those
per-document scores plus a cross-document redundancy check.

This is a deliberate positioning. It means the gate can run on day zero of a project,
before anyone has written a single evaluation question, and it means a poor score points
at a *document* to fix rather than at a retrieval parameter to tune.

## Governing principles

Two invariants shape nearly every design decision in the codebase, and they are
documented once on their own page:
**[Anti-Fabrication and Score-and-Flag](anti-fabrication-and-flagging.md)**.

- **Score-and-flag, human-in-the-loop.** Nothing is ever deleted. Everything questionable
  is surfaced with a machine-readable reason for a human to review.
- **Anti-fabrication.** A score is emitted only if it is whole, within scale, and
  justified. A guessed score is never emitted; missing judgment is reported as missing.

Read that page before the stage pages — it explains why parsing never raises, why the
screening stage leaves criteria unevaluated instead of estimating them, and why a failing
document still produces a score file.

## Two entrypoints, one CLI

The command-line interface is a single argument parser exposing three subcommands —
`parse`, `run` and `golden` — a corpus directory, and four options (`--config`, `--out`,
`--enrich`, `--force`). It is reachable two ways:

- **`python main.py parse|run|golden ...`** — a root shim that inserts `src/` onto the
  import path before importing the CLI. This is what makes the repository runnable
  *without installing it*, which matters for a quick evaluation on a machine where
  creating and populating a virtualenv is not worth it.
- **`cqg parse|run|golden ...`** — the console script declared in the project manifest,
  pointing at the same `main` function. Available after `pip install -e .`, which is also
  what puts the `src/`-layout package on the path properly.

`--force` is meaningful only to `parse`, where it authorises re-parsing a document already
present in the output folder; its help text states exactly that.

Both routes converge on the same function, so behaviour is identical; only the import
mechanics differ. The project requires Python 3.11+ and uses a `src/` layout with
setuptools package discovery.

## The three workflows

`cqg` does three distinct jobs over the same documents.

### `parse` — the parsed corpus

Extraction, split out of scoring and made a persisted artifact. `cqg parse <raw_dir> --out
<parsed_dir>` turns a folder of raw sources into a `parsed_input/`: one editable
`<doc_id>.md` per document — the markdown *as it will be ingested into RAG* — beside a
`<doc_id>.parse.json` sidecar holding the blocks, images, parse confidence and provenance.
Image [enrichment](../ingestion/image-enrichment.md) belongs to this stage, because it
needs the source PDF that scoring must no longer touch. An existing entry is never
overwritten without `--force`, since the markdown may have been corrected by hand. See
**[The parsed_input/ Boundary](../ingestion/parsed-input-boundary.md)**.

### `run` — the corpus quality verdict

The scoring pipeline. It stages as:

```
triage → parse → [enrich] → deterministic metrics → screen → sectioned LLM judgment
       → document score → Excel/CSV report + corpus redundancy + cost
```

Each stage decides something and hands on an artifact; a document can be short-circuited
at several points. The orchestration, its three exit paths, and the ordering decisions are
covered on **[The run Pipeline](../workflows/run-pipeline.md)**; the individual stages have
their own pages, linked from there.

`run` auto-detects which kind of folder it was given. On a raw folder the chain above runs
unchanged, parsing on the fly. On a `parsed_input/` the first two stages are already done:
the markdown and its sidecar are read back and scored, and no source file is ever opened.
A folder holding both kinds raises rather than being guessed at.

The evaluation grid itself is data, not code: a YAML registry of criteria, weighted by
dimension, that drives what gets judged and how the score is composed. See
**[The Criteria Registry](../scoring/criteria-registry.md)**.

### `golden` — the reference Q&A set

A separate deliverable aimed at business validation rather than at engineers: a set of
reference question/answer pairs, phrased as a real end user would type them, generated
from the documents and marked for human sign-off. It includes corpus-wide questions whose
answer spans several documents, grounded by retrieval over the full text. See
**[Golden Q&A Set Generation](../workflows/golden-set-generation.md)**.

`golden` auto-detects raw versus parsed folders on exactly the same rule as `run`, through
the same shared helper. It shares the triage and parsing layer and the LLM abstraction with
`run`, but not the scoring machinery — `golden` produces no criterion scores.

## The shared data model

A small set of Pydantic models is the vocabulary every stage exchanges. Knowing who owns
each type makes the pipeline much easier to follow.

**Produced by parsing, consumed by everything downstream:**

- **`ParsedDoc`** — the unit of work after extraction. It carries the document identifier,
  the extracted `markdown` (the text that will actually be judged), the list of `blocks`,
  a `parse_confidence` in `[0, 1]`, and the image references. Everything after parsing
  operates on this object, and only on this object — no stage re-reads the PDF except
  image enrichment, which needs the original file to crop from.
- **`Block`** — a typed fragment: a kind (`text`, `table`, `image`, `unreadable`, …),
  optional text, and a page. Blocks are what the *inventory* counts to decide which
  criteria are not applicable, and what the block-integrity signal measures. A block with
  a kind but no text is normal and meaningful, not a defect — an image block legitimately
  carries no text.
- **`ImageRef`** — a located image: page, index, bounding box, and the `placeholder` token
  written into the markdown in its place. The placeholder is the join key that lets
  [enrichment](../ingestion/image-enrichment.md) substitute a description back into the
  text at the right position.

**Produced by `parse`, consumed by `run` and `golden`** — the on-disk form of the two
above, owned by the `parse_store` layer:

- **`ParsedDocFile`** — the sidecar: everything a `ParsedDoc` carries *except* the
  markdown, which lives next to it in `<doc_id>.md` so a human can edit it. It adds a
  `schema_version` and a `markdown_hash`, the sha256 of that file, which is how a hand edit
  is detected on the way back in.
- **`ParseProvenance`** — what produced the entry, anchored on the source bytes: the
  parser used, the source file's name, type, `source_sha256` and page count, the triage
  category, and whether enrichment ran. It deliberately carries **no timestamp**:
  `parsed_input/` is a human-editable, reviewable artefact, and a clock value would turn
  every `--force` re-parse into a diff nobody can read.

**Produced by scoring, consumed by reporting:**

- **`CriterionScore`** — one criterion's verdict for one document: its registry identity
  (id, tag, weight), its `status`, an optional integer `score`, a `justification`, and
  optional `evidence`. This is the atom the report's detail sheet is built from.
- **`DocScore`** — the document verdict: global percentage, level, coverage percentage,
  per-dimension percentages, the full list of `CriterionScore`s, `flags`, and the
  `config_hash` that stamps which configuration produced it.

**Binding them:** the `Status` literal — `scored | na | not_evaluated` — is declared once
and used by both `CriterionScore` and, transitively, every consumer. Because it is a
closed type, an unexpected status is rejected at construction rather than propagating into
a report.

Note that `DocScore` is constructible directly, not only through the scoring path: the run
orchestration builds one by hand for unsupported, unreadable and failed documents, which is
exactly how score-and-flag guarantees that every input produces an output record.

`parse_store` is the layer that serialises and reads these types back. It is the only
module that knows the on-disk layout of a `parsed_input/`, and it is where the format is
decided: the markdown is written and read as **UTF-8 bytes**, never through
universal-newline decoding, and no trailing newline is appended — because that exact string
is what the deterministic metrics are computed on, and a CR silently rewritten as LF would
change them.

## Configuration and provenance

Behaviour is parameterized by a YAML configuration covering the judge LLM, section sizing,
parsing and batching, enrichment, golden generation, and thresholds. **No API key is ever
stored in plaintext** — the configuration holds the *name* of an environment variable and
the provider resolves it at runtime. Every `DocScore` carries a `config_hash` stamping the
run. Both are covered on
**[Configuration and Secrets](../operations/configuration-and-secrets.md)**.

## Dependency posture

The project constrains itself to permissively licensed dependencies (MIT / Apache-2.0 /
BSD) for commercial use, and that constraint is *checkable* rather than aspirational — a
script inspects the installed distributions and exits non-zero on a violation, with a test
guarding it. See
**[Testing and the License Gate](../operations/testing-and-license-gate.md)**.

## Where to go next

| To understand | Read |
|---|---|
| Why the system behaves defensively everywhere | [Anti-Fabrication and Score-and-Flag](anti-fabrication-and-flagging.md) |
| The scoring pipeline end to end | [The run Pipeline](../workflows/run-pipeline.md) |
| The artifact between parsing and scoring | [The parsed_input/ Boundary](../ingestion/parsed-input-boundary.md) |
| The reference Q&A deliverable | [Golden Q&A Set Generation](../workflows/golden-set-generation.md) |
| The evaluation grid | [The Criteria Registry](../scoring/criteria-registry.md) |
| How to configure a run and supply credentials | [Configuration and Secrets](../operations/configuration-and-secrets.md) |
