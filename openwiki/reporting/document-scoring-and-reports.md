---
type: pipeline-stage
title: Document Scoring and Corpus Outputs
description: How criterion results become a document verdict and the corpus deliverables — two-level weighted aggregation into a global percentage and level, the coverage meter and its flags, and the Excel/CSV exports plus the redundancy and cost artifacts, with their injection and encoding safeguards.
tags: [reporting, scoring, excel, csv, aggregation, coverage, redundancy, security]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-09T21:41:51.597Z
sources:
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-f3839253c7c5e3d67e28a4ad
    resource: repo://src/cqg/judge.py
  - id: openwiki-source-ada6bc0d2c90f334a8174d7f
    resource: repo://src/cqg/llm/instrument.py
  - id: openwiki-source-0807e73ac7196a324665fd8b
    resource: repo://src/cqg/redundancy.py
  - id: openwiki-source-487a7b025a60961dcab9ff1a
    resource: repo://src/cqg/registry/criteria_registry.yaml
  - id: openwiki-source-9d2f2d9e2d1816a6a6d4bd67
    resource: repo://src/cqg/registry/loader.py
  - id: openwiki-source-0d4ac7a15c4a3514756da39e
    resource: repo://src/cqg/report.py
  - id: openwiki-source-15ffe11df9b60121e2241bb7
    resource: repo://tests/test_cli_e2e.py
  - id: openwiki-source-414d25e40d7d980f8f1cd5fe
    resource: repo://tests/test_redundancy.py
  - id: openwiki-source-1fb869e707757275b0a8994a
    resource: repo://tests/test_report_export.py
  - id: openwiki-source-9fc38c4696400c0068133e6e
    resource: repo://tests/test_report_scoring.py
generated: { by: "claude-code", at: "2026-09-09T21:41:51.597Z" }
---

# Document Scoring and Corpus Outputs

This is the terminal stage: individual `CriterionScore`s become a `DocScore`, and the
collected `DocScore`s become the deliverables a human actually opens.

## Two-level weighted aggregation

The global percentage is built in two steps, and keeping them distinct is what lets the
grid express both "this criterion matters more than that one" and "this whole dimension
matters more than that one".

**Step 1 — within a dimension.** For each dimension, the numerator accumulates
`criterion_weight × score` and the denominator accumulates `criterion_weight × scale_max`
across that dimension's contributing criteria. The ratio, as a percentage, is the
dimension's score. A dimension with nothing to contribute is simply absent from the result
rather than recorded as zero.

**Step 2 — across dimensions.** The global percentage is the mean of the dimension
percentages weighted by the registry's `dimension_weights` — importantly, **only over
dimensions that actually produced a score**. The denominator is the sum of weights of
present dimensions, not of all declared ones. A document whose entire dimension went
unevaluated is not penalized as though it had scored zero there; that absence is reported
through coverage instead.

**Only `scored` criteria with a non-null score contribute** to either level. `na` and
`not_evaluated` rows enter neither numerator nor denominator. This is the arithmetic
expression of [anti-fabrication](../architecture/anti-fabrication-and-flagging.md): a
missing judgment does not become a zero, because a zero is a *claim* about quality and the
system has no basis for it.

### Levels

The percentage is bucketed into a level:

| Level | Threshold |
|---|---|
| `Excellent` | ≥ 90 |
| `Acceptable` | ≥ 70 |
| `Insuffisant` | ≥ 50 |
| `Inadapté` | below 50 |

These are the verbatim French labels used in the output; note that only `Inadapté` carries
an accent. `Inadapté` is also the level assigned directly by the run orchestration to
`unreadable`, `unsupported_format` and `processing_error` documents.

Those documents are not absent from the report: each still produces a `<doc_id>.score.json`
and a `Synthese` row carrying its flag. A file `cqg` could not open is visible in the
deliverable rather than missing from it — which is the whole point of
[score-and-flag](../architecture/anti-fabrication-and-flagging.md).

### A criterion outside the registry is ignored, not fatal

If a `CriterionScore` arrives whose id the registry does not know, it is skipped rather
than raising. The in-code comment is explicit that this is a choice: an unknown criterion is
ignored rather than crashing the batch.

This is deliberate robustness at a real seam. Criterion identity crosses two trust
boundaries — the registry is editable YAML, and criterion ids come back from LLM responses.
A registry edit mid-corpus, or a model inventing an id, would otherwise destroy an entire
run's results at the very last step, after all the LLM budget had been spent.

## Coverage: the anti-fabrication meter

Coverage is the second number on every document, and it measures something the global score
deliberately cannot:

```
coverage = scored / (scored + not_evaluated)
```

`na` criteria are **excluded from both terms**. That is the crucial distinction: a document
with no tables is not penalized for its table criteria being inapplicable, but a document
whose criteria could not be judged *is* marked down. Only a `scored` row with an actual
score value counts in the numerator — a test pins that a `scored` row with a null score is
excluded, keeping coverage consistent with the score.

When the denominator is zero — every criterion `na`, or an empty list — coverage is
**100.0 by convention**, documented as such in the code.

Coverage is where the pipeline's honesty becomes visible. Every mechanism that declines to
guess pushes it down:

- a [light-route](../scoring/two-speed-screening.md) document has *all* its qualitative
  criteria `not_evaluated`, so its coverage collapses;
- criteria depending on an unshipped external reference grid are permanently
  `not_evaluated`, setting a ceiling on any document's coverage;
- a criterion no section could judge lands in the same bucket.

Below the configured threshold, the flag `low_coverage` is raised. A second flag,
`low_parse_confidence`, is raised when extraction confidence is under 0.5. Both join the
run-level flags described in the
[flag vocabulary](../architecture/anti-fabrication-and-flagging.md).

The pairing matters when reading a report: **a high score with low coverage is a weak
signal, not a good result.** It means few criteria were judged and those happened to score
well.

## The deliverables

### `corpus_report.xlsx`

Three sheets, with these verbatim names and headers:

- **`Synthese`** — one row per document:
  `doc_id | score_global_% | niveau | couverture_% | flags`, with flags joined by `|`.
- **`Detail`** — one row per criterion per document:
  `doc_id | critere_id | critere | tag | poids | status | score | justification | preuve`.
  This is where the audit trail lives: every criterion's status, its justification, and its
  supporting evidence. Labels are resolved from the registry.
- **`Remediation`** — the actionable extract.

The `Remediation` sheet answers "what do I fix first?". A row qualifies **only if the
criterion is `scored` with a score of 2 or less** — a genuinely poor result, not a missing
one. `not_evaluated` criteria are deliberately absent: an unjudged criterion is not a known
defect, and mixing the two would send reviewers chasing gaps instead of problems. Rows are
sorted by document, then by **descending criterion weight**, so the heaviest fixable
criterion on each document comes first. Its columns are
`doc_id | critere_id | critere | poids | score_actuel`.

Each sheet is mirrored as a CSV (`synthese.csv`, `detail.csv`, `remediation.csv`), and each
document also gets a `<doc_id>.score.json` containing the full `DocScore` — the complete
machine-readable record including every criterion and the `config_hash`.

### Export safeguards

Both the corpus report and the [golden set](../workflows/golden-set-generation.md) share
the same protections, and they are correctness and security measures rather than polish:

- **Formula-injection neutralization.** A string value beginning with `=`, `+`, `-` or `@`
  is prefixed with an apostrophe so a spreadsheet renders it as text. Without this, content
  extracted from an untrusted PDF and written into a cell could execute when the workbook is
  opened. Applied to *every* cell in both the workbook and the CSVs.
- **Delimiter, quote and newline escaping.** The CSVs use `;` as the delimiter and are
  written through `csv.writer`, which quotes any value containing the delimiter, a quote, or
  a line break. Justifications and evidence are free text extracted from documents, so
  values containing all three are routine; naive string joining would silently corrupt the
  column structure.
- **UTF-8 with BOM.** CSVs are written as `utf-8-sig` specifically so Excel renders accented
  characters correctly, which it does not reliably do for plain UTF-8.

`None` is normalized to an empty string rather than the text `None`.

### Corpus-level artifacts

Two further files are written by the run orchestration itself, not by the report module.

**`corpus_redundancy.json`.** Cross-document duplicate detection over extracted text, in two
tiers:

- *Exact duplicates* — documents are bucketed by the SHA-256 of their whitespace-normalized,
  lowercased text; any bucket with more than one member is a duplicate group. This is
  content-based, so two files with different names and identical content are caught.
- *Near duplicates* — an optional semantic pass using `semhash`, which needs an embedding
  model that may not be downloadable offline. Its unavailability **degrades silently and
  recorded**: `near_duplicates` stays empty and `near_duplicates_status` carries a reason
  string such as `"skipped: semhash indisponible"`, `"skipped: aucun document"`, or
  `"skipped: <ExceptionType>"`. A consumer can always tell whether the pass ran, which a
  bare empty list could not convey.

Recall that only documents with non-empty markdown reach this stage, so unreadable files
cannot register as a spurious duplicate cluster.

**`cost.json`.** Per-document `n_calls` and `prompt_chars`, sourced from the counting
wrapper around the judge LLM and reset before each document. Because sectioned judgment
makes one call per section, this is a direct readout of the judgment cost model. See
[LLM Provider Abstraction](../integrations/llm-providers.md).

(It once doubled as a way to detect that sectioning had changed between runs, because the
[run fingerprint](../operations/configuration-and-secrets.md) did not cover `judge`
settings. That gap is closed — the fingerprint now covers them directly.)

## Related

- [The Criteria Registry](../scoring/criteria-registry.md) — the weights and dimensions driving aggregation
- [Sectioned LLM Judgment](../scoring/llm-judgment.md) — where the criterion results come from
- [Two-Speed Screening](../scoring/two-speed-screening.md) — the main cause of depressed coverage
- [Anti-Fabrication and Score-and-Flag](../architecture/anti-fabrication-and-flagging.md) — why absent judgment is never a zero
- [The run Pipeline](../workflows/run-pipeline.md) — the orchestration writing the corpus artifacts
- [LLM Provider Abstraction](../integrations/llm-providers.md) — the source of the cost counters
