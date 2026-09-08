# Autoresearch — optimizing the parsing of guarantee tables

Autonomous iteration loop (Karpathy style: Goal + mechanical metric + Verify + a loop
that keeps whatever improves) applied to the parsing of `Le Cahier Ma Santé (AGA - AEP).pdf`.

> `/autoresearch` (repo `uditgoenka/autoresearch`) is an **iteration harness**, not a
> PDF tool. It is not installed in this environment and its `/autoresearch` command cannot
> be invoked directly within a session (commands are loaded at startup).
> We therefore follow its protocol manually: Goal / Metric / Verify / loop.

## Goal
Maximize the **RAG usability** of the guarantee tables: preserve the
label→value association (rates %, amounts €), without losing any values.

## Metric (Verify → number)
The real defect of the legacy parser is not corruption (clean text, cid≈0) but
**flattening**: the columns are serialized separately, a label is separated from its
value by ~17,000 characters. The metric therefore measures **label→value adjacency**:

- `assoc_rate` = % of lines carrying a value that ALSO carry a label (≥2 words).
  `higher_is_better`. Flattened → ~37%; structured tables → ~83%.
- Constraint: `value_recall` must not regress (Docling alone loses values).

Verify: `python outputs/autoresearch/verify_parse_quality.py <parser>`
Fast fixture: `sample_tables.pdf` (5 dense pages: pages 2/42/90/108/217) — avoids
reparsing the 222 pages at every iteration.

## Typical invocation
```
/autoresearch Goal: "maximiser assoc libellé→valeur des tableaux sans perdre de valeurs" \
              Scope: src/cqg/parse.py \
              Metric: "assoc_rate" Direction: higher_is_better \
              Verify: "python outputs/autoresearch/verify_parse_quality.py docling" \
              Guard: ".venv/bin/python -m pytest -q"
```

## Results

### Iteration #0 — baseline vs Docling (via `parse_document`)
| Parser | assoc | value_recall | distinct |
|---|---|---|---|
| legacy (pdfminer, former default) | 37.3% | — | 25 |
| docling (new default) | 82.6% | 85.2% | 23 |

Docling **doubles** the association. Weakness: loses `145% 200% 220% 400%` (hospitalization
rates) and duplicates labels from adjacent rows.

### Iteration #1 — orchestrated combination
| Strategy | assoc | value_recall | distinct |
|---|---|---|---|
| docling + pdfminer completeness merge | 78.7% | **100%** | 27 |

Docling as primary (structure) + a pass recovering the missing values from the
native pdfminer text → 100% recall while keeping assoc >> baseline. **This is the target
strategy.** Next iterations: attach the recovered values to their label (rather
than in an appendix) to bring assoc back up towards that of Docling alone; deduplicate the labels.

## Integration status
- Docling = **default parser** (`parsing.parser: docling`), isolated in a **subprocess**
  (`src/cqg/docling_worker.py`): an OOM (SIGKILL, ~1.15 GB out of 1.2 GB) is detected via the
  returncode and switches to `legacy` without crashing the pipeline.
- `parser: legacy` = lightweight fallback (pdfminer + pdfplumber), kept and tested.
- The iteration #1 combination (merge) still has to be wired in as a parser strategy.

## Files
- `verify_parse_quality.py` — Verify (metric).
- `sample_tables.pdf` — 5-page fixture.
- `../benchmark-docling-cahier-ma-sante.md` — full benchmark (corrected, honest).
