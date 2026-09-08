# Parsing benchmark — "Le Cahier Ma Santé (AGA - AEP).pdf" (222 pages)

Objective: preserve the guarantee tables as **structured and retrievable** text (RAG).
Environment: ~1.2 GB free RAM, no swap, no API key. Docling installed (CPU, ocr=off).

## Ground truth
Guarantee values (amounts in €, rates in %) reconstructed from the **character** stream
(clean, verified) via position-aware `extract_words`, on 5 sample pages (2, 42, 90,
108, 217). GT = 19 distinct amounts + 13 distinct rates.

## Decisive result: FLATTENING (label→value association destroyed)

> Correction (data integrity): a first version of this note attributed to the current
> parser a "doubled letters" rate of 31% (`HHOonSoPrIaTiArLeIsSATION`). That was a
> measurement ERROR: this figure came from `pdfplumber.extract_text()`, NOT from the real parser
> (`_pages_text_pdfminer`, pdfminer). The real parser is **not** corrupted.

The real defect is the one diagnosed in the handoff: the current parser (pdfminer)
**flattens the tables**. The text is clean (cid≈0, doubled letters = 1.4%) but the
columns are serialized separately: all the labels first, all the values
after. **The label→value association is lost.**

Evidence: in the output of the current parser, the label « Honoraires des médecins » and its
value « 100 % » are separated by **17,005 characters**. In RAG, a chunk containing the
label does not contain the rate → the guarantee is not retrievable in context.

| Candidate | Doubled letters | Clean values | Label→value association (RAG) | Verdict |
|---|---|---|---|---|
| **pdfminer (current parser)** | 1.4% | yes (amounts + %) | ❌ **destroyed** (flattening, ~17k chars.) | unusable in RAG on tables |
| pdfplumber `extract_tables` | — | no (9/19 amounts, `3327,,5500 €€`) | ❌ mixed-up cells (A/D grids) | worse |
| **Docling (ocr=off, tables=on)** | 1.34% | yes (19/19 amounts; loses `55%`, `000%`) | ✅ **preserved** (Markdown `\| … \|`) | ✅ retained |

### Visual evidence

Current parser (pdfminer) — labels and values separated (flattening):
```
HOSPITALISATION
Honoraires des médecins
Frais de séjour
   - En établissement conventionné
...   (the matching 100 % rates appear ~17,000 characters further down)
```

Docling — label → value association preserved:
```
| Médicaments à service médical rendu majeur ou important (ex-vignette blanche) | 100 % |
| Médicaments à service médical rendu modéré (ex-vignette bleue)                | 100 % |
```

On the A/D optical grid (page 217), Docling recovers **19/19** amounts cleanly
(`32,50 € 75,00 € 37,50 € 90,00 €…`), structured as a table.

### Honest nuance on the gain
Docling's gain is **not** "fixes unreadable text" (the current parser is clean)
but "**preserves the table structure → label/value association usable in RAG**", which
flattening destroys. Real trade-offs: Docling loses a few isolated values
(`55%`, `000%`) and duplicates some labels from adjacent rows — weaknesses that
the `/autoresearch` orchestration must target (e.g. complete Docling with the pdfminer values).

## Scaling up — measured memory floor (decisive)

Peak RSS of a **fresh** Docling convert (brand-new process) by number of pages:

| Pages / convert | Peak RSS | Fits under 1.2 GB? |
|---|---|---|
| 1 | **1092 MB** | ✅ (margin ~110 MB) |
| 2 | 1249 MB | ❌ |
| 3 | 1274 MB | ❌ |
| 5 | 1708 MB | ❌ |

- Convert of the **whole doc**: OOM (SIGKILL).
- Batch with a **reused converter**: leak 1625→2225 MB over 100 pages (RAM released
  only when the process exits).
- **Only batch=1 in a fresh subprocess fits** (~1092 MB). The footprint of the models alone
  is ~1 GB → 2 pages already overflow.

**Retained design (validated by measurement)**: `docling_worker` handles a `page_range`; `parse.py`
loops **1 page per fresh subprocess** (batch configurable via `parsing.docling_batch_pages`,
default **1** here), with a **per-page pdfminer fallback** if a batch OOMs (graceful degradation, never
a crash). Cost: ~37 min for 222 pages (models reloaded per page). On a machine ≥8 GB,
increase `docling_batch_pages` (e.g. 20) for speed.

## Cost / feasibility (1.2 GB RAM constraint)
- Docling: **peak RSS 1158 MB** out of 1202 MB available (fits, but almost no margin, no swap).
- ⚠️ **OOM = SIGKILL (137), NOT catchable by try/except.** A `try/except → legacy` fallback
  does NOT cover OOM (the process dies). For a default parser: isolate Docling in a
  **subprocess** (detect the death → legacy fallback), or document it + keep legacy reachable.
- Speed: ~8–20 s/page → **~30–60 min** for the 222 pages.
- `ocr=false` (requested) lightens the deps (no OCR engine); image vision = existing LLM path.
- Required install fixes: matched torch **CPU** + torchvision **+cpu**;
  `opencv-python-headless` (libGL absent on a headless server).

## Proposed autoresearch metric (Verify → number)
The real defect being **flattening** (association destroyed), the relevant metric
measures **label→value adjacency**, NOT doubled letters (the current parser and Docling
are tied at ≈1.4% there). `Metric: proportion of (guarantee label, rate/€) pairs
co-occurring within a window of N characters (higher_is_better)`. The flattened parser scores
~0 (separation ~17k chars.); Docling scores high (table `\| libellé \| valeur \|`). In addition:
recall of clean values vs GT (Docling must not regress on value coverage).

## Autoresearch iteration #1: orchestrated combination (result)

Metric = **label→value adjacency** (assoc) + **value recall** (must not regress),
on the sample pages. pdfminer baseline extracted directly.

| Strategy | assoc (label→value) | value_recall | distinct values |
|---|---|---|---|
| pdfminer (current) | 37.3% | 92.6% | 25 |
| Docling alone | 82.6% | 85.2% | 23 |
| **Docling + pdfminer merge** | **78.7%** | **100.0%** | **27** |

- Docling alone **doubles** the association (37→83%) but **loses 4 values**: `145%, 200%,
  220%, 400%` — precisely the **hospitalization rates** cited in the handoff (`220%(1)
  400%(1)`). A real weakness, not a cosmetic one.
- **Winning combination**: Docling as primary (structure) + a completeness pass for the
  missing values recovered from the native pdfminer text → **100% recall** while
  keeping a high association (78.7% >> 37.3%). This is the strategy that the
  `/autoresearch` loop must retain and refine (next iterations: reduce the duplication
  of Docling labels, attach the recovered values to their label rather than in an appendix).

Reproducible harness: `scratchpad/assoc_metric.py` (Verify), `scratchpad/combo.py`
(strategy comparison). `higher_is_better` metric on `assoc`, constraint
`value_recall == 100 %`.

## Existing repo policy (to be arbitrated)
Docling was **deliberately removed** from the `cqg` dependencies and locked down by 3 tests
(`test_parse_document_no_docling_symbols`, `test_docling_removed_from_declared_deps`,
parser allowlist). Deliberately lightweight core (no torch/models). PyMuPDF banned (AGPL).
