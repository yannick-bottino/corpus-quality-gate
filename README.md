# Corpus Quality Gate (cqg)

Intrinsic document quality evaluator, run BEFORE RAG ingestion. Scores and flags each
document (reference-free, document-level: neither ground truth nor queries required), aggregated
at corpus level. Principle: **score-and-flag, human-in-the-loop** (nothing is deleted, everything
is flagged for review). Target corpus: heterogeneous and multimodal, bilingual FR/EN — digital
PDFs, plain text (`.txt`, `.md`) and office documents (`.docx`, `.pptx`).

## Installation

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows ; on Unix: source .venv/bin/activate
pip install -e .
```

Python 3.11+. MIT / Apache-2.0 / BSD dependencies only (commercial use). The license
gate is verifiable: `python scripts/check_licenses.py`.

## Usage

Two subcommands. No API key in plain text: keys are read from environment variables
(`*_api_key_env` fields of the config).

```bash
# 1) Corpus quality verdict
python main.py run    <corpus_dir> --config config/config.example.yaml --out <sortie> --enrich

# 2) Reference question/answer set (golden set) for business validation
python main.py golden <corpus_dir> --config config/config.example.yaml --out <sortie>
```

(After `pip install -e .`, the `cqg run ...` / `cqg golden ...` command is also available.)

## Pipeline

```
triage (pypdf, python-pptx)                                 # classify, count pages/slides
  -> parse                                                  # extractor chosen by extension
  -> enrich (image -> text, VLM, injected BEFORE the eval)  # optional (--enrich), PDF only
  -> screen (two-speed triage)                              # degraded/clean doc -> "light" route
  -> deterministic metrics (Gopher/RedPajama, block integrity, content redundancy)
  -> sectioned LLM judgment (100% document coverage, one batched call per section)
  -> Excel/CSV report + corpus redundancy
```

Extraction is chosen by extension, never by the triage category:

| Input | Extractor |
|---|---|
| `.pdf` | **Docling** in a batched subprocess (default), automatic fallback to pdfminer.six + pdfplumber |
| `.txt`, `.md` | direct read, `utf-8-sig` + NFKC |
| `.docx`, `.pptx` | python-docx / python-pptx — headings, tables, speaker notes; no PDF machinery |

Key points built in:
- **Parsing robustness**: detection of `(cid:NNN)` font-mapping failures and penalization
  of `parse_confidence` (a half-unreadable document no longer comes out with high confidence),
  with a pdfplumber re-extraction attempt.
- **Sectioned judgment with overlap**: the document is split into overlapping
  sections (RAG-chunking style, tunable) and judged at 100%, instead of a single excerpt.
- **Two-speed triage**: a manifestly degraded or manifestly clean document is
  routed to light judgment (flagged, without spending the full LLM budget).
- **Anti-fabrication**: three states `scored | na | not_evaluated`. A score is retained
  only if whole, within the scale, AND justified. Never a guessed score.
- **Every input produces a row**: nothing is silently dropped. A document that failed to
  extract is flagged `unreadable`, one that raised `processing_error`, a lightly judged one
  `screen:light`. Read the `flags` column rather than the error count.

## Outputs

`run` (in `--out`):
- `corpus_report.xlsx`: tabs **Synthese** (score, level, coverage, flags per document),
  **Detail** (the 57 criteria with status / score / justification / evidence), **Remediation**.
- `synthese.csv`, `detail.csv`, `remediation.csv`, `<doc>.score.json`, `<doc>.enriched.md`,
  `corpus_redundancy.json`, `cost.json` (LLM calls and prompt volume per document).

Each `<doc>.score.json` carries a `config_hash`: a fingerprint of the scoring configuration
*and* of the criteria grid's content, so two runs are only comparable when it matches.

`golden` (in `--out`):
- `golden_qa.xlsx` / `golden_qa.csv`: reference Q&A set, columns
  `question / reponse / sources / couvert / statut_validation / commentaire_beta`. Questions in
  natural end-user language. Variable count (auto according to information density, or fixed via
  the config). Includes **corpus-wide** questions (answer crossing several documents),
  anchored by retrieval over the full text. Answer kept only if covered by the
  documents, otherwise "Non couvert par le document".

## Configuration

Documented template: `config/config.example.yaml` (`config/config.claude_cli.yaml` drives the
judgment through the local Claude CLI instead of an HTTP provider). Sections:

| Section | What it sets |
|---|---|
| `llm` | provider mock / openai / azure_openai / anthropic + `api_key_env`, model, excerpt budget |
| `judge` | section size and overlap for sectioned judgment |
| `parsing` | `parser: docling \| legacy`, and the Docling page-batch size |
| `enrichment` | image VLM (independent of the judge LLM), minimum image size |
| `golden` | profile, policy, number of questions, corpus-wide questions + retrieval parameters |
| `thresholds` | coverage below which a document is flagged |
| `paths` | working directory — the only section excluded from `config_hash` |

Portable in batch (e.g. Azure OpenAI) via the `llm.provider` field of the configuration.

## Tests

```bash
python -m pytest -q
```

Run from the repository root: one test reads `pyproject.toml` by a relative path.

## Documentation

- **[`openwiki/`](openwiki/quickstart.md)** — the repository wiki: pipeline stages, parsing and
  extraction, scoring and the criteria registry, reporting, configuration, operations. Start at
  [`openwiki/quickstart.md`](openwiki/quickstart.md).
- [`docs/GUIDE-run-docling-complet.md`](docs/GUIDE-run-docling-complet.md) — Docling setup,
  batch sizing and measured memory figures.
- [`docs/benchmark-docling-cahier-ma-sante.md`](docs/benchmark-docling-cahier-ma-sante.md) —
  the parsing benchmark behind the Docling default.
