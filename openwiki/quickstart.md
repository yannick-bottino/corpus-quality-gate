---
type: quickstart
title: Quickstart
description: Entry point to the Corpus Quality Gate wiki — what cqg does, how to install and run both subcommands, what artifacts they produce, and which page answers each common question.
tags: [quickstart, getting-started, cli, navigation, installation]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T21:30:42.164Z
sources:
  - id: openwiki-source-bf4bd188e5cad9eab90456b4
    resource: repo://config/config.example.yaml
  - id: openwiki-source-152a88b414832cd1539f749f
    resource: repo://docs/GUIDE-run-docling-complet.md
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-0d4ac7a15c4a3514756da39e
    resource: repo://src/cqg/report.py
generated: { by: "claude-code", at: "2026-09-08T21:30:42.164Z" }
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

## The two commands

Both take a corpus directory. After `pip install -e .` the `cqg` console script works
identically to `python main.py`.

```bash
# 1) Corpus quality verdict
python main.py run <corpus_dir> --config config/config.example.yaml --out <out_dir> [--enrich]

# 2) Reference Q&A set (golden set) for business validation
python main.py golden <corpus_dir> --config config/config.example.yaml --out <out_dir>
```

`--out` defaults to `./workdir/out`, `--config` to `config/config.example.yaml`. `--enrich`
applies to `run` only and turns on image description before evaluation.

The shipped template selects the `mock` provider, so both commands run end to end with **no
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
| `<doc_id>.enriched.md` | With `--enrich`: the text actually scored |

Levels are `Excellent` / `Acceptable` / `Insuffisant` / `Inadapté`.

**`golden`**, in `--out`: `golden_qa.xlsx` and `golden_qa.csv`, columns
`id | origine | question | reponse | sources | couvert | statut_validation | commentaire_beta`.
Rows start at `a_valider`; an answer not covered by the documents reads
`"Non couvert par le document"`.

## Reading a report

Two numbers per document, and they must be read together:

- **`score_global_%`** — quality across the criteria that were judged.
- **`couverture_%`** — how many applicable criteria were actually judged.

**A high score with low coverage is a weak signal, not a good result.** Check the `flags`
column: `unreadable`, `processing_error:`, `screen:light (…)`, `auto_descriptions:`,
`low_coverage`, `low_parse_confidence`.

## Where to read next

| Your question | Page |
|---|---|
| What is this system and how do the pieces fit? | [System Overview](architecture/system-overview.md) |
| Why is a criterion `not_evaluated` instead of scored? What does a flag mean? | [Anti-Fabrication and Score-and-Flag](architecture/anti-fabrication-and-flagging.md) |
| What happens to a document, stage by stage? | [The run Pipeline](workflows/run-pipeline.md) |
| A document parsed badly, or came out `unreadable` | [Corpus Triage and Document Parsing](ingestion/document-parsing.md) |
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

**The run fingerprint does not cover everything.** `config_hash` stamps each score file but
excludes the `judge`, `parsing` and `enrichment` blocks — so two runs with different section
sizing or a different parser can share a hash while producing different scores. See
[Configuration and Secrets](operations/configuration-and-secrets.md) before comparing runs.
