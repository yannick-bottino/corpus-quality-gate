---
type: quickstart
title: Quickstart
description: Entry point to the Corpus Quality Gate wiki — what cqg does, how to install and run its three subcommands, the one-shot and parse-then-score ways to work, what artifacts they produce, and which page answers each common question.
tags: [quickstart, getting-started, cli, navigation, installation]
sources:
  - id: openwiki-source-bf4bd188e5cad9eab90456b4
    resource: repo://config/config.example.yaml
  - id: openwiki-source-152a88b414832cd1539f749f
    resource: repo://docs/GUIDE-run-docling-complet.md
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-4d169df8f5a62ba2edae177b
    resource: repo://src/cqg/parse_store.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-0d4ac7a15c4a3514756da39e
    resource: repo://src/cqg/report.py
  - id: openwiki-source-f2e05a5624d52b19421cdd43
    resource: repo://src/cqg/triage.py
  - id: openwiki-source-15ffe11df9b60121e2241bb7
    resource: repo://tests/test_cli_e2e.py
  - id: openwiki-source-150acf1471520418887f0cfe
    resource: repo://tests/test_regression_parse_run.py
generated: { by: "claude-code", at: "2026-09-11T15:09:34.136Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-11T15:09:34.136Z
---

# Quickstart

**Corpus Quality Gate** (`cqg`) scores the intrinsic quality of documents **before** they
are ingested into a RAG pipeline. It is reference-free and document-level: no ground truth
and no queries required. Its operating principle is **score-and-flag, human-in-the-loop** —
nothing is deleted, everything questionable is surfaced for review.

## Install

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: . .venv/Scripts/activate
pip install -e .
```

Python 3.11+. Dependencies are restricted to MIT / Apache-2.0 / BSD for commercial use, and
the constraint is checkable:

```bash
python scripts/check_licenses.py     # prints "Licences OK", or exits 1
python -m pytest -q                  # run from the repository root
```

## The three commands

All take a corpus directory. PDFs, plain-text files (`.txt`, `.md`) and office documents
(`.docx`, `.pptx`) are all parsed and scored. After `pip install -e .` the `cqg` console script works
identically to `python main.py`.

```bash
# 1) Corpus quality verdict
python main.py run <corpus_dir> --config config/config.example.yaml --out <out_dir> [--enrich]

# 2) Reference Q&A set (golden set) for business validation
python main.py golden <corpus_dir> --config config/config.example.yaml --out <out_dir>

# 3) Extraction only: turn raw sources into an editable parsed_input/
python main.py parse <raw_dir> --out <parsed_dir> [--enrich] [--force]
```

`--out` defaults to `./workdir/out`, `--config` to `config/config.example.yaml`. `--enrich`
turns on image description and applies to `parse` and to `run` over a raw folder. `--force`
applies to `parse` only, and re-parses a document already present in the output folder.

### One shot, or parse then score

`run` accepts **either** a raw folder or a `parsed_input/`, and works out which it was given.
That yields two ways to work:

```bash
# One shot — unchanged. Existing commands keep working exactly as before.
python main.py run <raw_dir> --out <out_dir>

# Split — extract once, inspect or correct the text, then score it.
python main.py parse <raw_dir>    --out parsed_input/
#   ... open parsed_input/<doc_id>.md, fix a mangled table, save ...
python main.py run   parsed_input/ --out <out_dir>
python main.py golden parsed_input/ --out <golden_dir>
```

The split exists because `parsed_input/<doc_id>.md` is *the text that will be ingested into
RAG* — the thing worth reading and correcting before it is judged. Scoring a corrected
document flags it `manually_edited` rather than hiding the edit, and re-running `parse` never
overwrites your correction without `--force`. Keep `raw_input/` and `parsed_input/` as
separate folders: a folder holding both is refused rather than guessed at. See
[The parsed_input/ Boundary](ingestion/parsed-input-boundary.md).

Splitting changes **no score**: a regression test requires `parse` + `run` to produce score
files strictly identical to a direct `run`.

The shipped template selects the `mock` provider, so every command runs end to end with **no
API key** as a smoke test. For real judgment, either set a provider and its credential
environment variable, or use `config/config.claude_cli.yaml`, which needs no key at all.

> **No API key is ever stored in configuration.** The config holds the *name* of an
> environment variable; the provider reads the value from the environment at runtime.

## What you get

**`run`**, in `--out`:

| Artifact | Contents |
|---|---|
| `corpus_report.xlsx` | Sheets `Synthese` (`doc_id`, `score_global_%`, `niveau`, `couverture_%`, `flags`), `Detail` (per criterion: `status`, `score`, `justification`, `preuve`), `Remediation` (criteria scored ≤ 2, heaviest first) |
| `synthese.csv`, `detail.csv`, `remediation.csv` | The same three sheets as CSV |
| `<doc_id>.score.json` | Full machine-readable score for each document |
| `corpus_redundancy.json` | Exact and near-duplicate detection across the corpus |
| `cost.json` | LLM calls and prompt characters per document |
| `<doc_id>.enriched.md` | Raw folder with `--enrich`: the text actually scored |

Levels are `Excellent` / `Acceptable` / `Insuffisant` / `Inadapté`.

**`parse`**, in `--out`: `<doc_id>.md` (the markdown as it will be ingested, editable) and
`<doc_id>.parse.json` (its sidecar: blocks, images, parse confidence, markdown hash and
provenance) per document, plus `images/<doc_id>/*.png` when `--enrich` is on. The command
prints how many documents were written and skipped, names any whose source changed since the
last parse, and **exits non-zero** if any document failed — a partial `parsed_input/` that
looks like a success is how a document disappears from a later report.

**`golden`**, in `--out`: `golden_qa.xlsx` and `golden_qa.csv`, columns
`id | origine | question | reponse | sources | couvert | statut_validation | commentaire_beta`.
Rows start at `a_valider`; an answer not covered by the documents reads
`"Non couvert par le document"`.

## Reading a report

Two numbers per document, and they must be read together:

- **`score_global_%`** — quality across the criteria that were judged.
- **`couverture_%`** — how many applicable criteria were actually judged.

**A high score with low coverage is a weak signal, not a good result.** Check the `flags`
column: `unsupported_format:`, `unreadable`, `processing_error:`, `screen:light (…)`,
`auto_descriptions:`, `low_coverage`, `low_parse_confidence`.

Scoring a `parsed_input/` can add `manually_edited`, `missing_sidecar`, `missing_markdown`,
`invalid_sidecar`, `sidecar_schema_unsupported:` and `renamed:` — all reporting the state of
the parsed entry rather than the quality of the document.

## Where to read next

| Your question | Page |
|---|---|
| What is this system and how do the pieces fit? | [System Overview](architecture/system-overview.md) |
| Why is a criterion `not_evaluated` instead of scored? What does a flag mean? | [Anti-Fabrication and Score-and-Flag](architecture/anti-fabrication-and-flagging.md) |
| What happens to a document, stage by stage? | [The run Pipeline](workflows/run-pipeline.md) |
| A document parsed badly, or came out `unreadable` | [Corpus Triage and Document Parsing](ingestion/document-parsing.md) |
| I want to correct the extracted text before it is scored | [The parsed_input/ Boundary](ingestion/parsed-input-boundary.md) |
| Parsing is slow, or is being killed for memory | [The Docling Subprocess Boundary](ingestion/docling-subprocess.md) · [`docs/GUIDE-run-docling-complet.md`](../docs/GUIDE-run-docling-complet.md) |
| Images are ignored or descriptions are missing | [Image Enrichment](ingestion/image-enrichment.md) |
| I want to change the criteria, weights, or scale | [The Criteria Registry](scoring/criteria-registry.md) |
| Where do the non-LLM scores and N/A decisions come from? | [Deterministic Signals and Metrics](scoring/deterministic-signals.md) |
| A document was flagged `screen:light` and barely judged | [Two-Speed Screening](scoring/two-speed-screening.md) |
| How are qualitative criteria scored? Why is judgment costing this much? | [Sectioned LLM Judgment](scoring/llm-judgment.md) |
| How is the global score computed? What is in the report? | [Document Scoring and Corpus Outputs](reporting/document-scoring-and-reports.md) |
| I need to add or switch an LLM provider | [LLM Provider Abstraction](integrations/llm-providers.md) |
| How do I configure a run, or supply credentials? | [Configuration and Secrets](operations/configuration-and-secrets.md) |
| How do I generate the reference Q&A set? | [Golden Q&A Set Generation](workflows/golden-set-generation.md) |
| What do the tests cover? What is the license gate? | [Testing and the License Gate](operations/testing-and-license-gate.md) |

## Two things worth knowing early

**The default parser is heavy.** Docling runs out-of-process, one subprocess per page batch,
and the default batch size of 1 is tuned for a memory-constrained machine — correct but
slow. On a machine with comfortable RAM, raise `parsing.docling_batch_pages`. Setup, batch
sizing and measured figures are in
[`docs/GUIDE-run-docling-complet.md`](../docs/GUIDE-run-docling-complet.md); set
`parsing.parser: legacy` for a fast pass without it.

**Every input produces a row.** Nothing is silently dropped: a document that fails to
extract — a broken PDF, a corrupt `.docx` — is flagged `unreadable`, and a
document that raised is flagged `processing_error:`. Only the second counts towards the
run's error tally, so read the `flags` column rather than the error count to see what was
actually scored. See
[Anti-Fabrication and Score-and-Flag](architecture/anti-fabrication-and-flagging.md).
