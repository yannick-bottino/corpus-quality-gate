---
type: pipeline-stage
title: Deterministic Signals and Metrics
description: The reference-free measurements cqg computes from extracted text before any LLM is involved — text-quality signals including length-robust MATTR, the block inventory that decides which criteria are not applicable, and the regex-driven scores for deterministically resolvable criteria.
tags: [metrics, signals, deterministic, ttr, mattr, inventory, na-decisions]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-09T22:03:23.095Z
sources:
  - id: openwiki-source-6b1845a66655ac54d0d4b6d0
    resource: repo://src/cqg/deterministic.py
  - id: openwiki-source-78a59ac162fb1ac39266402a
    resource: repo://src/cqg/inventory.py
  - id: openwiki-source-f3839253c7c5e3d67e28a4ad
    resource: repo://src/cqg/judge.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-c68b4fcfcbfc7045e09425f5
    resource: repo://src/cqg/screen.py
  - id: openwiki-source-978bdc187683aafb96b74a0e
    resource: repo://src/cqg/signals.py
  - id: openwiki-source-d5fdcd1a25f2863fbf86f964
    resource: repo://tests/test_deterministic.py
  - id: openwiki-source-43c130da5632d490e465b3ed
    resource: repo://tests/test_inventory.py
  - id: openwiki-source-348912dd3d0e7f05ba63cd33
    resource: repo://tests/test_signals.py
generated: { by: "claude-code", at: "2026-09-09T22:03:23.095Z" }
---

# Deterministic Signals and Metrics

Before a single LLM call is made, `cqg` measures what it can measure by computation alone.
These measurements do three jobs: they resolve some criteria outright, they decide which
criteria do not apply, and they give [screening](two-speed-screening.md) the evidence it
needs to route the document.

Everything here is cheap, deterministic, and reproducible — the opposite of the judgment
stage, and a deliberate counterweight to it.

## The metrics contract

`compute_metrics` returns a four-key dict, and that shape is the contract consumed
downstream:

| Key | Contents | Consumed by |
|---|---|---|
| `na` | Sorted ids of criteria not applicable to this document | [Judgment](llm-judgment.md), to exclude them from scope |
| `signals` | The seven text-quality measurements | [Screening](two-speed-screening.md) |
| `d_scores` | `{criterion_id: score}` for deterministically resolved criteria | [Judgment](llm-judgment.md), which emits them as `scored` directly |
| `h_signals` | Per-criterion deterministic hints for the LLM prompt | Judgment's prompt builder |

**`h_signals` is currently an extension seam, not a live feature.** It is returned empty,
commented as being filled in by later enrichment so the LLM can adjust hybrid (`H`)
criteria. The consuming side is fully wired: the prompt builder looks up each criterion's
hint and, when present, appends `(signal deterministe: <hint>)` to that criterion's line.
Populating the dict is all that is needed to activate signal-informed judgment for `H`-tagged
criteria — which is precisely what the `H` tag anticipates.

## Text-quality signals

Seven measurements, all computed on the document's markdown (the *enriched* markdown when
[enrichment](../ingestion/image-enrichment.md) ran, since that is what will be ingested):

- **`non_alpha_fraction`** — share of characters that are not letters. High values indicate
  symbol soup: `(cid:NNN)` tokens, mojibake, or a table rendered as punctuation. Empty text
  returns 1.0, the maximally suspicious value, rather than 0.
- **`mean_words_per_sentence`** — readability proxy from sentence-terminator splitting.
- **`duplicate_line_fraction`** — raw repeated-line share.
- **`type_token_ratio`** — global vocabulary richness: unique tokens over total tokens.
- **`mattr`** — the length-robust variant (below).
- **`n_tokens`** — word-token count, a size proxy sharing the TTR tokenization.
- **`block_integrity`** — share of blocks carrying text.

The `cid_failure_fraction` signal lives in the same module but is consumed earlier, during
[parsing](../ingestion/document-parsing.md), where it drives re-extraction and the
confidence penalty.

### Why MATTR exists alongside TTR

This is the most consequential measurement decision in the module.

The global type-token ratio **decreases mechanically with document length**. Vocabulary
saturates — a document eventually stops introducing new words — while the denominator, total
token count, keeps growing. A long document therefore scores a low TTR *regardless of its
actual quality*.

The effect is not marginal. The code records a measured case: a 222-page document with a
perfectly healthy vocabulary produced a global TTR of **0.0042** — a value indistinguishable
from genuinely unreadable text. Taken at face value it would have condemned the document.

**MATTR** (Mean Segmental TTR) removes the length dependence: the token stream is cut into
fixed windows, the TTR of each window is computed, and the mean is returned. Because every
window has the same denominator, the measure reflects vocabulary richness rather than
length. Healthy text keeps a high MATTR at any length; genuinely degraded text — repeated or
unreadable — stays low in *every* window. For text shorter than one window, MATTR reduces
exactly to the global TTR, which a test pins directly.

A second test constructs the pathology explicitly: 300 unique tokens repeated to 60,000
tokens collapses the global TTR below 0.01 while MATTR stays healthy. This distinction is
what [screening](two-speed-screening.md) relies on to avoid mistaking "long" for "degraded",
and the global TTR is retained only as a fallback for older callers.

## The N/A inventory

`na_decisions` answers "which criteria cannot apply to this document?" — a
[different question from "which could not be judged"](../architecture/anti-fabrication-and-flagging.md),
and one answered by counting rather than guessing.

`block_inventory` counts from two sources:

- **Block kinds**, matched by substring so parser vocabularies vary safely (`figure` and
  `picture` both count as figures; images count `image`, `picture` *or* `figure`, so a
  figure implies an image). Tables, formulas (`formula` or `equation`) and section headers
  are counted the same way.
- **The markdown itself**, for links — both markdown link syntax and bare URLs, with the
  bare-URL pattern using a negative lookbehind so a markdown link is not counted twice.

Because the count is driven by block kinds rather than by the source format, office
documents participate on the same terms as PDFs: the
[Word and PowerPoint extractors](../ingestion/document-parsing.md) emit
`Block(kind="table")` and `Block(kind="image")` for the tables and pictures they find, so a
deck with figures does not get its image criteria wrongly marked N/A. Their table text also
reaches the markdown as pipe tables, so the text-side signals see it too.

Four inventory conditions each map to a group of criteria: no images marks the image and
figure criteria, no tables the table criteria, no formulas the formula criterion, no links
the link criterion. All of them fall in the readability dimension — the criteria that judge
objects a document may legitimately not contain.

**The proposal is then intersected with the registry's `na_possible` whitelist.** The
[registry has the final say](criteria-registry.md): the inventory cannot mark N/A a criterion
the grid says must always be judged. A test pins both directions — image criteria are marked
N/A when no image exists, and criterion `1.1` never is, because it is not `na_possible`.

## Deterministic criterion scores

Eight criteria are resolved by pattern matching, without any LLM. The judge emits these
directly as `scored` with the justification `"Signal deterministe."`

They look for **explicit textual evidence of document governance** — the kind of thing a
regular expression genuinely can settle, because its presence or absence is a fact about the
text rather than a matter of judgment:

- authorship attribution;
- version markers and dates, in several forms;
- an update or review cadence;
- a lifecycle status (validated, draft, archived, obsolete);
- a change history or revision table;
- FAQ structure;
- content duplication.

The gradations follow a consistent shape. Most criteria are **binary — 5 if the evidence is
present, 1 if not.** The versioning criteria are **three-valued**: 5 when *both* a version
marker and a date are found, 3 when only one is, 1 when neither. That middle value is
meaningful — a document dated but unversioned is genuinely better governed than one with
neither, and worse than one with both. Content duplication grades on a measured fraction:
5 at zero duplication, 3 below a small tolerance, 1 above it.

The FAQ criterion illustrates the design well: it accepts *either* an explicit marker
(the literal term, or French equivalents) *or* structural evidence — at least five lines
ending in a question mark. A document can be FAQ-shaped without labelling itself as one, and
a test pins that structural path.

### `_MONTHS_FR` is load-bearing

Date detection must handle French textual dates, because the target corpus is bilingual and
the French documents write dates in words. The month alternation is preserved verbatim,
with both accented and unaccented variants since extracted PDF text is inconsistent:

```
(?:janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t
 |septembre|octobre|novembre|d[eé]cembre)
```

This must never be translated or "corrected" — replacing it with English month names would
silently stop detecting dates in exactly the documents the tool was built for. It matches
both `1er janvier 2026` and a bare `Juin 2025`, and a test asserts a French textual date
alone lifts the versioning criterion to at least 3.

## Boilerplate exclusion in duplicate detection

The naive duplicate-line fraction has a false positive that matters at scale: a page header
or footer repeated on every page of a 200-page PDF makes the document look massively
duplicated, when in fact it is normally formatted.

`_content_duplicate_fraction` corrects this with two filters before measuring:

1. **Short lines are dropped** — below a minimum length, a line carries too little content
   for its repetition to mean anything (page numbers, single words, fragments).
2. **Lines occurring more than a threshold number of times are excluded entirely** as
   boilerplate. The reasoning is that content genuinely duplicated within a document repeats
   a *few* times; a line appearing on every page is structural furniture, not duplicated
   content.

Only the survivors are measured for repetition. The in-code comment names this as the fix
for a specific false positive on the content-duplication criterion, and a test pins it: a
header repeated five times alongside one unique paragraph yields a duplicate fraction of
exactly **0.0**.

The raw `duplicate_line_fraction` signal is *not* replaced — it remains available to
screening, which uses it as a coarse degradation hint where boilerplate sensitivity matters
less.

## Related

- [Corpus Triage and Document Parsing](../ingestion/document-parsing.md) — where the text and blocks come from, and where `cid_failure_fraction` is used
- [Two-Speed Screening](two-speed-screening.md) — the main consumer of the signals
- [Sectioned LLM Judgment](llm-judgment.md) — the consumer of `na`, `d_scores` and `h_signals`
- [The Criteria Registry](criteria-registry.md) — the `na_possible` whitelist and the `D`/`H` tags
- [The run Pipeline](../workflows/run-pipeline.md) — where this stage sits
