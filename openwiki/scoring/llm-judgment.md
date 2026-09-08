---
type: pipeline-stage
title: Sectioned LLM Judgment
description: How cqg scores qualitative criteria — the document is split into overlapping sections covering 100% of its text, each section is judged in one batched LLM call over all in-scope criteria, and per-criterion results are aggregated across sections by median under anti-fabrication validation.
tags: [judgment, llm, chunking, aggregation, median, anti-fabrication, cost]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T21:30:42.164Z
sources:
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-6b1845a66655ac54d0d4b6d0
    resource: repo://src/cqg/deterministic.py
  - id: openwiki-source-f3839253c7c5e3d67e28a4ad
    resource: repo://src/cqg/judge.py
  - id: openwiki-source-5ae9caedcf7eaa19f9cf0d18
    resource: repo://tests/test_judge_batch.py
  - id: openwiki-source-11ac0e9139b67ec6a5c046b0
    resource: repo://tests/test_judge.py
generated: { by: "claude-code", at: "2026-09-08T21:30:42.164Z" }
---

# Sectioned LLM Judgment

This stage resolves the criteria that computation cannot: the qualitative ones requiring
an actual reading of the document. It is the only expensive stage, and its design is
dominated by two goals in tension — **judge the whole document**, and **do not spend an
unbounded number of LLM calls doing it**.

The resolution is: split the document into overlapping sections, judge *all* in-scope
criteria in **one call per section**, then aggregate across sections.

## Scope: which criteria reach the LLM

Not every criterion is judged. Scope is everything that is **none of** the following:

1. marked N/A by the [inventory](deterministic-signals.md) — the object it judges is absent;
2. flagged `external_dep` in the [registry](criteria-registry.md) — it needs a reference
   grid the project does not ship;
3. tagged `D` **and** already resolved by a deterministic scorer.

Condition 3 is a conjunction, and that matters: a `D`-tagged criterion with no deterministic
scorer *does* reach the LLM. The tag states intent; the presence of a produced score is what
actually removes a criterion from scope. See
[the registry](criteria-registry.md) for the consequences.

## Sectioning: 100% coverage with overlap

`_split_sections` walks the markdown in windows of `section_chars`, advancing by a stride of
`size - overlap`.

- **Overlap defaults proportionally** — one tenth of the section size when not specified,
  the usual proportion in RAG chunking. Passing `0` yields adjoining windows.
- **Overlap is clamped** to `0 <= overlap < size`, guaranteeing a stride of at least 1 so the
  walk always progresses. Without the clamp, an overlap equal to the size would loop forever.
- **Every section is at most `section_chars`** long, and empty markdown yields no sections at
  all rather than one empty one.

The coverage property is **union, not partition**: every character of the document lands in
at least one section, and characters in an overlap region land in two. Tests pin both forms
— with zero overlap the concatenated sections reconstruct the text exactly, and with overlap
the first section plus each subsequent section's tail beyond the overlap reconstructs it,
while consecutive sections genuinely share their boundary region.

### Why overlap exists

Evidence for a criterion is often a contiguous passage — a version block, a table caption, a
disambiguating definition. A hard boundary can cut such a passage in half, leaving both
neighbouring sections with a fragment that supports no confident judgment. With overlap, a
passage shorter than the overlap width is **fully visible in at least one window**.

This is the same reasoning that motivates overlap in RAG chunking, applied to judgment
rather than retrieval, and the same windowing logic appears in the
[golden set's corpus index](../workflows/golden-set-generation.md).

The alternative it replaced is still in the codebase: `_representative_excerpt` samples a
document down to a character budget by taking a head plus distributed windows. It is
**explicitly retained for the baseline test suite and is no longer on the coverage path** —
sectioning superseded it. Its own tests confirm it samples through to the document's end,
which is exactly the weakness that motivated moving to full coverage: a *sample* can always
miss the evidence.

## The batched call

Each section produces **exactly one** LLM call covering every in-scope criterion. The prompt
is built in French and:

- frames the task as evaluating a **section** of a document for a RAG system;
- states the scale from the registry;
- lists each criterion as `- <id> : <label>`, appending `(signal deterministe: <hint>)`
  when [`h_signals`](deterministic-signals.md) supplies one;
- instructs the model that if it cannot reliably evaluate a criterion on this section it
  must set `not_evaluated` — **`Ne devine jamais une note.`**;
- specifies a JSON object keyed by criterion id, each value carrying `status`, `score`,
  `justification` and `evidence`.

The response is dispatched through `judge_batch`, an optional capability of the
[client contract](../integrations/llm-providers.md). Only dict-valued entries for in-scope
criteria are collected; anything else is dropped silently, so a malformed or hallucinated
key cannot corrupt the run.

The prompt's instruction not to guess is *advice*. The guarantee is the validation below.

### Cost model

**LLM calls per document = number of sections.** Nothing else in the stage calls the model.
This is a deliberately legible cost driver: doubling `section_chars` roughly halves the call
count, and the relationship is directly observable in `cost.json`, which records calls and
prompt characters per document. A test pins it exactly — a 20,000-character document at
8,000-character sections makes exactly 3 calls.

The pairing with [screening](two-speed-screening.md) completes the budget story: screening
decides *whether* to pay at all, sectioning decides *how much*.

## Aggregation across sections

Each criterion collects up to one response per section, which must be reduced to a single
verdict.

**Only compliant sections contribute.** A response is admitted only if it passes
`_valid_scored` — status `scored`, an integer score (explicitly not a `bool`) within the
scale, and a non-empty justification. Responses that are `not_evaluated`, out of scale,
empty-justified, or absent are **discarded, not coerced**. A test proves an out-of-scale
section is simply outvoted by a valid one.

**The score is the median** of the contributing scores. The median is chosen for robustness:
a single section that misjudges a criterion — because it happened to contain unrepresentative
content — cannot drag the document's verdict, whereas a mean would. An even-count median is
rounded to the nearest integer, so a document with two sections scoring 2 and 4 scores 3.

**The justification and evidence come from the section whose score is closest to the
median**, with ties resolved to the **earliest** section. This keeps the reported rationale
attached to an actual section's reasoning rather than being synthesized, and makes the
choice deterministic.

**No compliant section yields `not_evaluated`**, with the justification
`"Non evalue: aucune section n'a produit de note conforme."` The aggregate is then
re-validated as a final safety net, which would return
`"Non evalue: agregat non conforme."` — a path the code notes should be unreachable. See
[Anti-Fabrication](../architecture/anti-fabrication-and-flagging.md).

## The five terminal outcomes

`score_document` returns exactly one `CriterionScore` per registry criterion, in registry
order. Each takes one of five paths, evaluated in this order:

| # | Condition | Status | Justification |
|---|---|---|---|
| 1 | Marked N/A by inventory | `na` | `"Objet absent du document (inventaire)."` |
| 2 | `external_dep` in registry | `not_evaluated` | `"Referentiel de questions/cas d'usage absent."` |
| 3 | `D`-tagged with a deterministic score | `scored` | `"Signal deterministe."` |
| 4 | Light route active | `not_evaluated` | `"Route light (crible) : jugement LLM non execute."` |
| 5 | Otherwise | aggregated | From the section closest to the median |

Ordering matters: N/A precedes external-dependency, and both precede the light-route branch,
so a light-route document still keeps its inventory and deterministic verdicts. Only the
qualitative criteria go unevaluated — which is exactly the point of the light route, and
which mechanically depresses that document's
[coverage](../reporting/document-scoring-and-reports.md).

When the light route is active, the section loop is skipped entirely: **no call is made, not
even one**. A test asserts zero calls with a mock primed to return a valid score.

## Related

- [Anti-Fabrication and Score-and-Flag](../architecture/anti-fabrication-and-flagging.md) — the validation predicate and its enforcement points
- [Two-Speed Screening](two-speed-screening.md) — what decides whether this stage runs
- [The Criteria Registry](criteria-registry.md) — scope, labels, and the scale bound
- [Deterministic Signals and Metrics](deterministic-signals.md) — the source of `na`, `d_scores` and `h_signals`
- [LLM Provider Abstraction](../integrations/llm-providers.md) — the `judge_batch` capability and cost metering
- [Document Scoring and Corpus Outputs](../reporting/document-scoring-and-reports.md) — what happens to these results
- [The run Pipeline](../workflows/run-pipeline.md) — where this stage sits
