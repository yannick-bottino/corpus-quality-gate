---
type: workflow
title: The run Pipeline
description: End-to-end orchestration of the cqg run subcommand — how each document is sequenced through triage, parsing, optional enrichment, deterministic metrics, screening, sectioned judgment and scoring, the three exit paths, and the corpus artifacts written at the end.
tags: [pipeline, orchestration, workflow, control-flow, error-handling, cost]
sources:
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-ada6bc0d2c90f334a8174d7f
    resource: repo://src/cqg/llm/instrument.py
  - id: openwiki-source-c19eabdc855679b7af548ca1
    resource: repo://src/cqg/llm/manual.py
  - id: openwiki-source-bf3b15b22d143311cdbe443a
    resource: repo://src/cqg/llm/providers.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-9d2f2d9e2d1816a6a6d4bd67
    resource: repo://src/cqg/registry/loader.py
  - id: openwiki-source-0d4ac7a15c4a3514756da39e
    resource: repo://src/cqg/report.py
  - id: openwiki-source-f2e05a5624d52b19421cdd43
    resource: repo://src/cqg/triage.py
  - id: openwiki-source-15ffe11df9b60121e2241bb7
    resource: repo://tests/test_cli_e2e.py
  - id: openwiki-source-c3bd80e13bca0fabc8af5c04
    resource: repo://tests/test_parse.py
  - id: openwiki-source-81cf9f57b4380dad067c7e02
    resource: repo://tests/test_screen.py
generated: { by: "claude-code", at: "2026-09-09T22:03:23.095Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-09T22:03:23.095Z
---

# The run Pipeline

`cqg run` produces the corpus quality verdict. This page is the spine: it covers the
orchestration in `cli.run` — the ordering decisions, the control flow, and what each
document's journey actually produces. Each stage has its own page, linked at the point it
appears.

```
triage ─▶ parse ─▶ [enrich] ─▶ deterministic metrics ─▶ screen ─▶ [judge] ─▶ score
                                                                              │
                     corpus report + redundancy + cost ◀────────── all documents
```

## Setup, before any document

The orchestration reads configuration once and builds everything the loop needs.

- **The registry** is loaded, defining the criteria grid. See
  [The Criteria Registry](../scoring/criteria-registry.md).
- **The judge LLM** is built from the `llm` block, defaulting to `mock`, and immediately
  wrapped in the counting instrument that meters judgment spend.
- **The run fingerprint** `config_hash` is computed once and stamped into every document's
  score — including documents that never reach scoring. Its registry component is derived
  from the criteria file's *content*, so an edited grid produces a different fingerprint.
- **The output directory** is created up front, so partial results survive an interrupted run.
- **Configuration values are read at this level** and passed down as arguments: the coverage
  threshold, `max_doc_chars`, `section_chars` and `section_overlap`, the parser choice and
  batch size. Stages receive plain arguments rather than the config dict, which is why they
  are testable in isolation. Defaults are applied here at the call sites — see
  [Configuration and Secrets](../operations/configuration-and-secrets.md).

### The VLM is built conditionally

Enrichment is on if **either** `--enrich` was passed **or** `enrichment.enabled` is set.
Only then is the vision client constructed, from `enrichment.vlm` when present and otherwise
from the main `llm` block.

The conditional construction is the point: because a provider resolves its credential at
construction, building the VLM unconditionally would make an enrichment API key a
prerequisite for *every* run, including runs that never describe an image. Deferring it
keeps the plain path credential-free. See
[Image Enrichment](../ingestion/image-enrichment.md).

## The per-document loop

[Triage](../ingestion/document-parsing.md) enumerates and classifies the corpus, and the
loop walks its records in sorted order. Everything below happens inside a `try`/`except`
scoped to a single document.

### 1. Parse

[Parsing](../ingestion/document-parsing.md) produces a `ParsedDoc`. It never raises — the
worst case is an empty-markdown document at confidence 0.0.

### 2. Enrich, *before* evaluation

If enrichment is active and the document has images, each image is described and the
descriptions are written into the markdown, which is persisted as `<doc_id>.enriched.md`
and **replaces the document's markdown** for everything downstream.

The ordering is deliberate and commented as such: quality is scored on **what will actually
be ingested into RAG**, not on raw text still carrying opaque placeholders. Scoring first
and enriching afterwards would systematically under-rate illustrated documents relative to
how they will really perform.

The count of unverified machine-written descriptions is captured here and becomes the flag
`auto_descriptions:<n>`, so a score partly resting on unverified text is auditable.

### 3. Deterministic metrics

[Metrics](../scoring/deterministic-signals.md) are computed on the (possibly enriched)
markdown: text-quality signals, the N/A inventory, and directly-resolved criterion scores.
No LLM involved.

### 4. Screen

[Screening](../scoring/two-speed-screening.md) uses those signals to choose a route:
`light` or `full`.

### 5. Judge

The counter is **reset**, then [judgment](../scoring/llm-judgment.md) runs with
`skip_llm` set when the route is `light`. Immediately afterwards the per-document cost is
recorded as `n_calls` and `prompt_chars`.

The reset/record pairing is what makes `cost.json` **per-document rather than cumulative**;
without it every document would report the corpus running total. Because judgment makes one
call per section, `n_calls` is a direct readout of the cost model — and a light-route
document records zero.

### 6. Score and flag

[Document scoring](../reporting/document-scoring-and-reports.md) aggregates criteria into a
`DocScore`, raising `low_coverage` and `low_parse_confidence` itself. The orchestration then
appends its own flags: `screen:light (<reasons>)` if the document took the light route, and
`auto_descriptions:<n>` if machine descriptions entered the text.

## Four exit paths

Every document leaves the loop by exactly one of four routes, and **all four write a score
file**. This is [score-and-flag](../architecture/anti-fabrication-and-flagging.md) made
concrete: no input is ever silently dropped.

| Path | Trigger | Result | Also |
|---|---|---|---|
| **Unsupported format** | Triage category is `unsupported_format` | `DocScore` at 0.0, level `Inadapté`, flag `unsupported_format:<ext>` | Checked **before** parsing — the file is never opened. Unreachable for any shipped extension |
| **Unreadable** | Empty markdown after parsing | `DocScore` at 0.0, level `Inadapté`, flag `unreadable` | Skips metrics, screening and judgment entirely — **no LLM call on empty content**; excluded from duplicate detection |
| **Processing error** | Any exception in the block | `DocScore` at 0.0, level `Inadapté`, flag `processing_error: <ExceptionType>` | Appended to the run's `errors` list with the message |
| **Normal** | Everything succeeded | Full `DocScore` with dimensions, criteria and flags | — |

Three details worth noting.

The unsupported-format path is the **only consumer of the triage category**, and it is
currently inert. Every extension triage admits — `.pdf`, `.txt`, `.md`, `.docx`, `.pptx` —
now has a parser, so nothing reaches this exit through a normal corpus walk. It is kept
deliberately: it is the honest landing for a format admitted into `SUPPORTED_EXTS` ahead of
its parser, and a test drives it through triage directly so the contract does not quietly
stop being exercised.

The layering it expresses still holds. The category decides *whether to attempt*
extraction, while the parser decides *how* — and reaching this verdict never opens the
file. Note what it does **not** cover: a `.docx` that is corrupt or password-protected is a
supported format that failed to read, so it takes the unreadable path below instead.

The unreadable path is a deliberate short-circuit rather than a consequence: it is commented
as skipping metrics and judgment *specifically* to avoid spending an LLM call on empty
content, and it appends nothing to the parsed-text list, so a corpus of unreadable files
cannot register as a cluster of identical documents in
[redundancy detection](../reporting/document-scoring-and-reports.md).

And **`n_errors` counts only the exception path**. An `unreadable` document and an
unsupported format are both normal, expected outcomes rather than errors — so a run
reporting zero errors may still contain documents that were never scored. Read the flags,
not just the error count.

An end-to-end test drives both failure paths together: a valid PDF and a corrupt one in one
corpus, asserting two score files, and that the corrupt one carries `unreadable` while the
valid one scores normally.

## After the loop

With every document scored, the orchestration writes the corpus deliverables:

- **`corpus_report.xlsx`** with sheets `Synthese`, `Detail` and `Remediation`, plus the
  matching `synthese.csv`, `detail.csv` and `remediation.csv`;
- **`corpus_redundancy.json`** — exact and near-duplicate detection over the extracted text
  of documents that produced any;
- **`cost.json`** — per-document judgment calls and prompt characters.

All three are covered on
[Document Scoring and Corpus Outputs](../reporting/document-scoring-and-reports.md).

The function returns a summary — report paths, document count, error count and details, and
the redundancy and cost paths — and, **in manual enrichment mode only**, flushes the image
manifest and adds its path as `image_manifest`. That flush is guarded by a capability check
rather than a provider check, and it matters: without it there would be no record of which
images still need describing.

The CLI then prints a one-line French summary naming the document count and the workbook
path.

## Artifacts produced

| Artifact | When |
|---|---|
| `<doc_id>.score.json` | Every document, on all four exit paths |
| `corpus_report.xlsx`, `synthese.csv`, `detail.csv`, `remediation.csv` | Always |
| `corpus_redundancy.json`, `cost.json` | Always |
| `<doc_id>.enriched.md`, `images/<doc_id>/*.png` | Enrichment active and the document has images |
| Image manifest | Manual VLM mode |

## Related

- [System Overview](../architecture/system-overview.md) — how `run` relates to `golden`
- [Anti-Fabrication and Score-and-Flag](../architecture/anti-fabrication-and-flagging.md) — the invariants behind the exit paths
- [Corpus Triage and Document Parsing](../ingestion/document-parsing.md) · [Image Enrichment](../ingestion/image-enrichment.md) — stages 1–2
- [Deterministic Signals](../scoring/deterministic-signals.md) · [Two-Speed Screening](../scoring/two-speed-screening.md) · [Sectioned LLM Judgment](../scoring/llm-judgment.md) — stages 3–5
- [Document Scoring and Corpus Outputs](../reporting/document-scoring-and-reports.md) — stage 6 and the corpus artifacts
- [Configuration and Secrets](../operations/configuration-and-secrets.md) — the values read during setup
