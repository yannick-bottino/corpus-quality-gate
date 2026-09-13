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

Three subcommands. No API key in plain text: keys are read from environment variables
(`*_api_key_env` fields of the config).

```bash
# 1) Parsing: raw sources -> parsed_input/ (the markdown as it will be ingested)
python main.py parse  <raw_dir>    --config config/config.example.yaml --out <parsed_input> [--enrich] [--force]

# 2) Corpus quality verdict
python main.py run    <corpus_dir> --config config/config.example.yaml --out <sortie> --enrich

# 3) Reference question/answer set (golden set) for business validation
python main.py golden <corpus_dir> --config config/config.example.yaml --out <sortie>
```

`run` and `golden` take as `<corpus_dir>` **either** a folder of raw sources (parsed on the
fly, behaviour unchanged) **or** a `parsed_input/` (pure scoring, no source file is ever
touched). `parse` takes a raw folder only, and refuses a folder that is already a
`parsed_input/`.

(After `pip install -e .`, the `cqg parse ...` / `cqg run ...` / `cqg golden ...` command is
also available.)

## `parsed_input/`

The boundary between parsing and scoring. One parsed document = two files side by side:

| File | Content |
|---|---|
| `<doc_id>.md` | the markdown as it will be ingested into RAG, editable by hand |
| `<doc_id>.parse.json` | sidecar: `blocks`, `images`, `parse_confidence`, `markdown_hash`, `provenance` |

The sidecar is not optional. `na_decisions` counts blocks, so a markdown without its
sidecar would show zero table and zero image and flip the structure criteria to `na` — the
score would move for a reason foreign to the quality of the document.

Detection is automatic: a folder holding `*.parse.json` files is a `parsed_input/`. A `.md`
on its own never marks a folder as parsed, being both a supported source format and an
output of parsing. A folder holding both sidecars and raw sources (`.pdf`, `.docx`,
`.pptx`, `.txt`) is refused with an explicit error rather than guessed: scoring it as raw
would re-parse the markdown and ignore the sidecars, scoring it as parsed would drop the
sources.

`parse` skips a document already present in the output folder; `--force` re-parses it.
Editing the markdown by hand is a first-class case, and a silent re-parse would destroy
that work. When the source has changed since the parsing (source hash compared with the
sidecar provenance), `parse` reports it on stdout and never re-parses on its own: choosing
between the human edit and the new source version is the human's call, made with `--force`.

If the `.md` has been edited by hand, `run` detects it (`markdown_hash` comparison), flags
the document `manually_edited` and recomputes the text blocks from the edited markdown. The
typed blocks (`table`, `image`) and the image geometry stay as parsed: they are facts about
the SOURCE, which an edit to the prose cannot re-derive.

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

`cqg parse` covers the chain from `triage` through `enrich` and stops at `parsed_input/`;
`cqg run` picks it up at `screen`. Given a raw folder, `run` still runs the whole chain in
one go, `--enrich` included: the split opens a possible stop, it does not impose one. On a
`parsed_input/`, `--enrich` has no object — a warning says so and the option is ignored
(the VLM client is not even built, so no API key is demanded to do nothing).

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
  `screen:light`. On a `parsed_input/`, a hand-edited markdown is flagged `manually_edited`,
  a markdown dropped in without its sidecar `missing_sidecar`, a sidecar whose markdown was
  moved or deleted `missing_markdown`. An unsupported format and an unreadable document
  cross the parsing boundary too and are flagged exactly as they are on a raw folder.
  Read the `flags` column rather than the error count.

## Outputs

`parse` (in `--out`, which is the `parsed_input/`):
- `<doc_id>.md` and `<doc_id>.parse.json` per document — the enriched markdown when
  enrichment is on, since the enrichment happens here;
- `images/<doc_id>/`: the cut-out images, written only when enrichment is on and the
  document has images.

`run` (in `--out`):
- `corpus_report.xlsx`: tabs **Synthese** (score, level, coverage, flags per document),
  **Detail** (the 57 criteria with status / score / justification / evidence), **Remediation**.
- `synthese.csv`, `detail.csv`, `remediation.csv`, `<doc>.score.json`, `<doc>.enriched.md`,
  `corpus_redundancy.json`, `cost.json` (LLM calls and prompt volume per document).

`<doc>.enriched.md` only appears on a run over a raw folder with enrichment on. On a
`parsed_input/` the enriched markdown is `<doc_id>.md` itself, written by `parse`.

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

Documented template: `config/config.example.yaml`. Sections:

| Section | What it sets |
|---|---|
| `llm` | judge provider + `api_key_env`, model, excerpt budget |
| `judge` | section size and overlap for sectioned judgment |
| `parsing` | `parser: docling \| legacy`, and the Docling page-batch size |
| `enrichment` | image VLM (independent of the judge LLM), minimum image size |
| `thresholds` | coverage below which a document is flagged |
| `paths` | working directory — the only section excluded from `config_hash` |
| `golden` | profile, policy, number of questions, corpus-wide questions + retrieval parameters |

Providers accepted by `llm.provider` and by `enrichment.vlm.provider`:
`mock`, `openai`, `azure_openai`, `anthropic`, `claude_cli` (judges through the local Claude
CLI, no HTTP key — see `config/config.claude_cli.yaml`) and `manual` (writes an image
manifest to fill in offline, for enrichment).

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
