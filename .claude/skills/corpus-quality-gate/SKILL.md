---
name: corpus-quality-gate
description: >-
  Evaluates the intrinsic quality of a document corpus before RAG ingestion
  (score-and-flag, reference-free, document-level). Produces one JSON record per
  document and an Excel/CSV report per corpus. Use this skill to audit a corpus,
  qualify documents before RAG, or generate a golden Q&A set.
---

# Corpus Quality Gate

Python tool `cqg`. Two usage modes over the same core.

Accepted inputs: `.pdf`, `.txt`, `.md`, `.docx`, `.pptx`. Every admitted file produces a
report row — a document that fails to extract is flagged, never dropped.

## In session (demo)
1. `pip install -e .`
2. Copy `config/config.example.yaml`, keep `provider: mock` (or wire up a real LLM).
3. `cqg run <corpus_dir> --config config/config.example.yaml --out workdir/out`
4. Artifacts in `workdir/out/`: `<doc>.score.json`, `corpus_report.xlsx`, the CSVs,
   `corpus_redundancy.json`, `cost.json`.

Add `--enrich` to describe images with a VLM before scoring, so the quality verdict is
computed on the text that will actually be ingested.

## In batch (Azure OpenAI or another enterprise endpoint)
In `config.yaml`, set `llm.provider: azure_openai`, `base_url`, `model`, and the name of the
environment variable holding the key (`api_key_env`). No code change. `claude_cli` judges
through the local Claude CLI instead, with no HTTP key — see `config/config.claude_cli.yaml`.

## Parsing
PDFs go through Docling in a batched subprocess by default, falling back automatically to
pdfminer.six + pdfplumber; set `parsing.parser: legacy` to skip Docling entirely (much
faster, no ML models). Office and plain-text formats are read directly and never touch the
PDF chain.

## Golden Q&A
See `src/cqg/golden_qa.py`; the answering policy is editable in
`config/golden_qa_policy.md` (references, caveats, product named, etc.). An answer is kept
only if the document covers it, otherwise "Non couvert par le document".

## Reference
Full documentation in `openwiki/` — start at `openwiki/quickstart.md`.
