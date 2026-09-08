# OpenWiki brief — Corpus Quality Gate (cqg)

Write the wiki in English. Code comments, docstrings, the README, and `docs/` were
translated to English on 2026-09-08; commit messages before that date are French.

French that remains is deliberate and load-bearing — never "correct" it, and quote it
verbatim when the wiki refers to it:

- **Business output labels**: Excel sheets `Synthese` / `Detail` / `Remediation`, the
  golden-set columns `question / reponse / sources / couvert / statut_validation /
  commentaire_beta`, and the value `"Non couvert par le document"`.
- **LLM prompt content**: the prompt strings in `golden_qa.py` and `judge.py`,
  `_GOLDEN_POLICY_DEFAUT` in `cli.py`, the `policy:` block in `config/config.example.yaml`,
  and `config/golden_qa_policy.md`.
- **The 57 criteria labels** in `criteria_registry.yaml` — a faithful copy of an external
  reference grid.
- **`_MONTHS_FR`** in `deterministic.py` — required to detect French dates in French PDFs.
- Verbatim PDF extracts used as evidence in `docs/benchmark-docling-cahier-ma-sante.md`.

## What this repository is

`cqg` scores the *intrinsic* quality of documents **before** they are ingested into
a RAG pipeline. It is reference-free and document-level: no ground truth and no
queries are required. Its operating principle is **score-and-flag, human-in-the-loop**
— nothing is ever deleted, everything questionable is surfaced for human review.
Target corpus: heterogeneous, multimodal digital PDFs, bilingual FR/EN.

Two CLI subcommands: `run` (corpus quality verdict) and `golden` (reference Q&A set
for business validation).

## What matters most — prioritize these

1. **The `run` pipeline end to end**: triage → parse → enrich → screen → deterministic
   metrics → sectioned LLM judgment → Excel/CSV report + corpus redundancy. Document
   what each stage decides, what it emits, and how a document is routed between them.
2. **Anti-fabrication invariants.** The three states `scored | na | not_evaluated`, and
   the rule that a score is kept only if it is whole, within the scale, AND justified.
   A guessed score is never emitted. This is a correctness boundary, not a detail.
3. **Parse robustness.** `(cid:NNN)` font-mapping failure detection, its effect on
   `parse_confidence`, and the pdfplumber re-extraction attempt. Docling is the default
   parser and runs as a batched subprocess (`docling_worker.py`) — cover that boundary.
4. **Two-speed triage** (`screen.py`): how a manifestly degraded or manifestly clean
   document is routed to light judgment to conserve LLM budget.
5. **Sectioned judgment with overlap** (`judge.py`): the RAG-style overlapping chunking
   that yields 100% document coverage, and the per-section batched LLM call.
6. **The criteria registry.** `src/cqg/registry/criteria_registry.yaml` drives the 57
   criteria. Document the registry as a contract — how criteria are declared, loaded,
   and mapped onto report columns — not as a dumped list of all 57 entries.
7. **The `golden` workflow** (`golden_qa.py`, `corpus_index.py`): variable question
   count, cross-document questions grounded by retrieval over full text, and the
   "Non couvert par le document" fallback.
8. **Configuration and secrets.** No API key is ever stored in plaintext; keys are read
   from environment variables named by the `*_api_key_env` config fields. Cover the
   config schema (`config.py`) and the difference between `config.example.yaml` and
   `config.claude_cli.yaml`.
9. **LLM provider abstraction** (`src/cqg/llm/`): the `base` contract and the
   `providers` / `claude_cli` / `manual` / `mock` implementations, plus what
   `instrument.py` records into `cost.json`.

## Organize around workflows, not directories

Group pages by system and workflow — ingestion & parsing, quality scoring, judgment,
reporting, golden set generation, configuration & providers, operations & testing —
rather than mirroring `src/cqg/`. Modules are the evidence, not the outline.

## Out of scope — do not document

- `e2e_out/` and `e2e_out_cli/` — generated run outputs, gitignored.
- `.venv/`, `__pycache__/`, `*.egg-info/`, `.codegraph/`.
- The 57 criteria enumerated one by one.
- Anything outside this Git repository (the parent workspace's `outputs/`,
  `test_data/`, and session-handoff notes are not part of `cqg`).

## Useful context for accuracy

- Python 3.11+, installed with `pip install -e .`; entry points are `main.py` and the
  `cqg` console script.
- Dependency licenses are constrained to MIT / Apache-2.0 / BSD for commercial use, and
  the gate is enforceable via `scripts/check_licenses.py` — treat this as a real
  project constraint, and cover `tests/test_licenses.py` as the check that guards it.
- `docs/` already holds a Docling run guide and a Docling benchmark. Reference them
  rather than restating their content.
