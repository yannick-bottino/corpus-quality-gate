---
type: pipeline-stage
title: Two-Speed Screening
description: The deterministic gate that routes each document before the expensive LLM judgment — manifestly degraded and manifestly clean documents take a light route that skips the LLM and flags them, while borderline documents receive the full judgment.
tags: [screening, routing, cost-control, triage, invariants, mattr]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-09T22:03:23.095Z
sources:
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-f3839253c7c5e3d67e28a4ad
    resource: repo://src/cqg/judge.py
  - id: openwiki-source-0d4ac7a15c4a3514756da39e
    resource: repo://src/cqg/report.py
  - id: openwiki-source-c68b4fcfcbfc7045e09425f5
    resource: repo://src/cqg/screen.py
  - id: openwiki-source-978bdc187683aafb96b74a0e
    resource: repo://src/cqg/signals.py
  - id: openwiki-source-81cf9f57b4380dad067c7e02
    resource: repo://tests/test_screen.py
generated: { by: "claude-code", at: "2026-09-08T21:30:42.164Z" }
---

# Two-Speed Screening

Judgment is the only expensive stage in `cqg`: its cost scales with document length, one
LLM call per section. Screening is the gate that decides **whether that spend is worth
making for a given document**, using only the deterministic signals already computed.

The premise is that two very different kinds of document do not need an expensive reading:

- one that is **manifestly degraded** — spending dozens of calls reading unreadable text
  produces judgments about the extraction, not about the document;
- one that is **manifestly clean** — every signal is green, and the deterministic evidence
  is already sufficient.

Everything in between — the genuinely ambiguous case, where a judgment actually adds
information — gets the full treatment.

## Light never means deleted

Before the rules, the invariant. **The light route is a routing decision, not a verdict.**
It never deletes and never downgrades. Concretely it means:

- no LLM call is made for that document — [not even one](llm-judgment.md);
- its qualitative criteria are emitted `not_evaluated` with the justification
  `"Route light (crible) : jugement LLM non execute."`, never a guessed score;
- its inventory (`na`) and deterministic verdicts are still produced normally;
- the document is **flagged** `screen:light (<reasons>)`, carrying the screen's own reasons
  into the report;
- and because `not_evaluated` criteria form the coverage denominator, its
  [coverage](../reporting/document-scoring-and-reports.md) collapses, which typically also
  raises `low_coverage`.

So a light-route document arrives at the reviewer clearly marked as *not fully assessed*,
with the reason attached. The saving is real and the omission is visible — the
[score-and-flag](../architecture/anti-fabrication-and-flagging.md) posture applied to
budget.

## The rules, in evaluation order

Order is significant: the first rule short-circuits both of the others.

### 1. Large document with healthy extraction → `full`

```
n_tokens >= LARGE_DOC_TOKENS  AND  parse_confidence >= 0.5
                              AND  non_alpha <= 0.40
                              AND  mattr >= 0.05
```
Reason: `gros_document_extraction_saine`.

**This is the page's central invariant**, and it exists to correct a specific measurement
artifact.

The global type-token ratio falls mechanically as a document lengthens — vocabulary
saturates while the token denominator keeps growing. The code cites the measured case: a
222-page document with an entirely healthy vocabulary produced a global TTR of **0.0042**, a
value otherwise indistinguishable from unreadable text. Screened on that number alone, the
largest and often most valuable document in a corpus would be routed light and never
properly judged — the exact inverse of what anyone wants.

So for a large document the screen **demands several concordant signals before any
downgrade**. As long as the extraction is healthy — acceptable parse confidence, reasonable
non-alpha fraction, and a healthy *window-normalized* TTR — the document is judged on
substance.

The guardrail cuts both ways, and both are deliberate:

- it prevents a false `light` from the degradation rule;
- it also **short-circuits the clean-signals shortcut**, so a large document is never
  skipped for being *too clean* either. A large document deserves a complete judgment.

A genuinely degraded large document still falls through: its window-normalized TTR is low,
so the guardrail's condition fails and rule 2 catches it. Two tests pin exactly this pair —
a large healthy document routes `full` despite a low global TTR, and a large genuinely
degraded one still routes `light`.

### 2. Degraded extraction → `light`

```
parse_confidence < 0.5  OR  non_alpha > 0.40  OR  mattr < 0.05
```
Reason: `extraction_degradee (parse_confidence=…, non_alpha=…, mattr=…)` — the reason string
**interpolates the measured values**, so the report shows not just that a document was
downgraded but on what numbers.

Three independent signals, any one sufficient: low
[parse confidence](../ingestion/document-parsing.md) (already penalized for `(cid:NNN)`
failures), a high non-alphabetic fraction (symbol soup), or a near-zero windowed vocabulary
(repeated or unreadable text).

### 3. All signals green → `light`

```
non_alpha < 0.30  AND  duplicate_line_fraction < 0.15  AND  mattr > 0.15
```
Reason: `signaux_propres`.

A manifestly clean *small* document — rule 1 already claimed the large ones. The
deterministic signals are trusted and the LLM budget is conserved.

### 4. Otherwise → `full`

Reason: `cas_limite`. The borderline case, where a judgment genuinely adds information.

## Why MATTR, not TTR

Every rule above uses `mattr`, the window-normalized ratio, rather than the global
`type_token_ratio`. This is the direct consequence of the artifact described in rule 1:
using the global ratio would systematically confuse **"long document"** with **"near-zero
vocabulary"**.

The global TTR is read only as a **fallback default** when `mattr` is absent from the
signals dict — retained for compatibility with older callers and tests, not as a routing
input in its own right. See [Deterministic Signals](deterministic-signals.md).

## Why `block_integrity` is deliberately excluded

The screen has access to `block_integrity` — the share of blocks carrying text — and
pointedly **does not use it**. The exclusion is documented at length in the code, because
the signal looks like a degradation measure and is not one.

Blocks come in typed kinds, and image and table blocks legitimately carry **no text**. A
document rich in images and tables therefore has a low block-integrity ratio *by
construction*, reflecting how illustrated it is rather than how well it extracted. Using it
as a degradation signal would route essentially **every illustrated document to light** —
and since the target corpus is explicitly heterogeneous, multimodal PDFs, that would
misroute much of the corpus this tool exists to evaluate.

A regression test guards it directly: an image-rich document with low block integrity but
otherwise clean signals must not be classified as degraded.

## Interaction with cost

Screening and [sectioning](llm-judgment.md) are complementary levers, and the split is
clean: **screening decides whether to pay, sectioning decides how much.** Both surface in
`cost.json` — a light-route document records zero judgment calls, which is directly
verifiable per document.

The routing decision itself is pure and side-effect-free: it takes a `ParsedDoc` and the
metrics dict and returns a route and its reasons. Attaching the flag is the run
orchestration's job, and skipping the LLM is the judge's, driven by the `skip_llm` argument.
That separation is why the rules are straightforward to test in isolation — all seven
screening tests call the function directly with a synthetic metrics dict.

## Related

- [Deterministic Signals and Metrics](deterministic-signals.md) — where every input signal comes from, and why MATTR exists
- [Sectioned LLM Judgment](llm-judgment.md) — what the light route skips
- [Anti-Fabrication and Score-and-Flag](../architecture/anti-fabrication-and-flagging.md) — why skipping never means guessing
- [Document Scoring and Corpus Outputs](../reporting/document-scoring-and-reports.md) — how the route shows up in coverage and flags
- [Corpus Triage and Document Parsing](../ingestion/document-parsing.md) — the source of `parse_confidence`
- [The run Pipeline](../workflows/run-pipeline.md) — where the route is applied and flagged
