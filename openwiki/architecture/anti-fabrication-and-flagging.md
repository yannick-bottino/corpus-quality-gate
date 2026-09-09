---
type: correctness-invariant
title: Anti-Fabrication and Score-and-Flag
description: The two cross-cutting correctness boundaries of cqg — a score is emitted only when it is whole, in scale and justified, and nothing is ever deleted, only flagged for human review. Defines the three criterion states and the flag vocabulary used across the pipeline.
tags: [invariants, anti-fabrication, human-in-the-loop, error-handling, scoring, flags]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-09T21:41:51.597Z
sources:
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-f3702b5dc23472a869a57236
    resource: repo://src/cqg/enrich.py
  - id: openwiki-source-b16c375f2cb0d2db7954adcd
    resource: repo://src/cqg/golden_qa.py
  - id: openwiki-source-78a59ac162fb1ac39266402a
    resource: repo://src/cqg/inventory.py
  - id: openwiki-source-f3839253c7c5e3d67e28a4ad
    resource: repo://src/cqg/judge.py
  - id: openwiki-source-c8d879f00ddd07aa3b1256db
    resource: repo://src/cqg/models.py
  - id: openwiki-source-0d4ac7a15c4a3514756da39e
    resource: repo://src/cqg/report.py
  - id: openwiki-source-f2e05a5624d52b19421cdd43
    resource: repo://src/cqg/triage.py
  - id: openwiki-source-15ffe11df9b60121e2241bb7
    resource: repo://tests/test_cli_e2e.py
  - id: openwiki-source-96f4e8eabb9c2b7186fe059b
    resource: repo://tests/test_golden_qa.py
  - id: openwiki-source-11ac0e9139b67ec6a5c046b0
    resource: repo://tests/test_judge.py
  - id: openwiki-source-d3c9c57e1b60bfc378d0ee28
    resource: repo://tests/test_models.py
  - id: openwiki-source-9fc38c4696400c0068133e6e
    resource: repo://tests/test_report_scoring.py
generated: { by: "claude-code", at: "2026-09-09T21:41:51.597Z" }
---

# Anti-Fabrication and Score-and-Flag

Two rules govern every stage of `cqg`. They are not stylistic preferences; they are
correctness boundaries enforced at specific points in code, and they explain why several
stages look more defensive than a naive pipeline would.

- **Anti-fabrication** — the system never emits a number it cannot defend. A missing
  judgment is reported as missing, not filled in.
- **Score-and-flag, human-in-the-loop** — the system never deletes and never silently
  drops. A document that fails, or that could not be judged, is surfaced to a human
  reviewer with a reason attached.

This page defines both invariants and enumerates every place they are enforced. The
stage pages ([sectioned judgment](../scoring/llm-judgment.md),
[screening](../scoring/two-speed-screening.md),
[golden set](../workflows/golden-set-generation.md),
[enrichment](../ingestion/image-enrichment.md),
[reporting](../reporting/document-scoring-and-reports.md)) reference this page rather
than restating the rules.

## The three criterion states

Every one of the criteria in the registry resolves to exactly one of three states,
declared as a closed type in the shared data model:

| State | Meaning | Score |
|---|---|---|
| `scored` | The criterion was evaluated and the result is defensible. | An integer within the scale |
| `na` | The criterion does not apply: the object it judges is absent from the document. | `None` |
| `not_evaluated` | The criterion applies, but no defensible result was obtained. | `None` |

The distinction between `na` and `not_evaluated` carries the whole meaning of the
invariant. `na` is a *positive* finding — the inventory established that the document
contains no tables, so table criteria cannot apply. `not_evaluated` is an *admission* —
the criterion was in scope and the system declined to guess. Because the state set is a
`Literal`, the model layer rejects any other value at construction time rather than
letting an unexpected status flow into the report.

Crucially, `not_evaluated` is never a failure to be hidden. It is counted, and it drives
the coverage figure that the report surfaces to the reviewer: a document whose criteria
were mostly not evaluated scores a low coverage percentage and is flagged. Honesty about
missing judgment is made visible rather than averaged away.

## Enforcement point 1 — the scoring predicate

The single gate through which a criterion may become `scored` is the `_valid_scored`
predicate in the judge. It requires four conditions simultaneously:

1. the reported status is `scored`;
2. the score is an integer — and explicitly **not** a `bool`, which in Python would
   otherwise pass an `isinstance(..., int)` check and turn `True` into a score of 1;
3. the score lies within the registry scale;
4. the justification is non-empty.

A model response that claims `scored` but omits the score, returns a value outside the
scale, or supplies an empty justification is demoted to `not_evaluated`. A model that
returns `na` on its own initiative is also ignored — `na` is a decision the deterministic
inventory owns, not one the LLM is allowed to assert. Focused tests pin each of these
demotions individually.

The prompt sent to the model reinforces the rule in its own words, instructing it to mark
a criterion `not_evaluated` when it cannot judge it reliably and never to guess a score.
But the prompt is only advice; the predicate is the guarantee.

## Enforcement point 2 — the aggregation safety net

Judgment runs per section, so each criterion may collect several responses that must be
reduced to one. The aggregation applies `_valid_scored` twice, deliberately:

- **On input** — only sections whose response passes the predicate contribute. Sections
  that returned `not_evaluated`, an out-of-scale value, an empty justification, or that
  omitted the criterion entirely are discarded rather than coerced.
- **On output** — the aggregated result is re-validated before being returned. The
  in-code comment marks this as a case that should not happen, since the median of valid
  in-scale scores is itself in scale; it is kept as an ultimate safety net.

When no section produced a compliant response, the criterion becomes `not_evaluated` with
the explicit justification `"Non evalue: aucune section n'a produit de note conforme."`
The degenerate second path returns `"Non evalue: agregat non conforme."` Neither path
invents a value.

## Enforcement point 3 — the light route

The [screening stage](../scoring/two-speed-screening.md) can route a document past the LLM
entirely to conserve budget. Skipping the judgment does not license inventing its result.
When `skip_llm` is set, deterministic and `na` decisions are preserved, and every
qualitative criterion is emitted as `not_evaluated` carrying the justification
`"Route light (crible) : jugement LLM non execute."`

A test asserts both halves of this at once: zero LLM calls are made, *and* the qualitative
criteria come back `not_evaluated` even though the mock provider was configured to return
a perfectly valid score of 5 had it been asked. The saving is real and the silence is
recorded.

The same discipline applies to the other non-judged states. A criterion whose evaluation
depends on an external reference grid that the project does not ship is emitted as
`not_evaluated` with the justification `"Referentiel de questions/cas d'usage absent."`,
and an inventory-excluded criterion as `na` with
`"Objet absent du document (inventaire)."` Deterministically resolved criteria carry
`"Signal deterministe."` In every case the report states how the value was obtained.

## Enforcement point 4 — the golden set coverage fallback

The [golden Q&A workflow](../workflows/golden-set-generation.md) applies the same rule to
generated answers. An answer survives only if the model explicitly marked it as covered
**and** the answer text is non-empty. Anything else — `couvert` absent, set to anything
other than `oui`, or an empty answer — collapses to the marker
`"Non couvert par le document"` with `couvert` forced to `non`.

This fallback is applied twice, once for per-document questions and once again for the
retrieval-grounded corpus-wide answers, so no generation path can bypass it. Every
generated row also starts life with `statut_validation` set to `a_valider`: the golden set
is a proposal awaiting human validation, never an established truth.

## Enforcement point 5 — machine-written prose is labelled

When [image enrichment](../ingestion/image-enrichment.md) is enabled, VLM-generated
descriptions are injected into the markdown that will be scored and later ingested. Every
such description is wrapped in a tag that names it as unverified:
`[Image (description automatique, non verifiee): {desc}]`.

The label is not decorative. The run counts its occurrences and attaches the count to the
document as a flag, so a reviewer can see how much of the evaluated text was written by a
machine rather than extracted from the source. Failures are labelled too, as
`[Image non decrite: {type}]`, and an empty description deliberately leaves the original
placeholder in place rather than being interpreted as "nothing there".

## Per-document error isolation

Score-and-flag also governs failure handling. Each document is processed inside its own
`try`/`except` in the run orchestration, and there are exactly four exits — all of which
produce a persisted score record:

**Unsupported format.** A file in a format `cqg` cannot open — currently `.docx` and
`.pptx` — is short-circuited *before* parsing to a `DocScore` at 0.0 flagged
`unsupported_format:<ext>`, without the file ever being opened.

This is a distinct finding from the one below, and keeping them apart matters. "I cannot
open this format" and "I opened this document and got nothing usable" call for different
actions from a reviewer: the first means convert or export the file, the second means the
document itself is damaged. Reporting both as `unreadable` told the reviewer the wrong
thing. Nor are these files simply excluded from the accepted extensions — dropping them
would be a silent loss, which score-and-flag forbids. They are admitted so they are
visible, flagged so they are actionable, and never opened.

**Empty extraction.** When parsing yields no usable text, the document short-circuits to a
`DocScore` at 0.0 with level `Inadapté` and the flag `unreadable`. This path deliberately
skips both metric computation and judgment, for two stated reasons: no LLM call is spent
on empty content, and the document does not pollute duplicate detection. That second point
is a real mechanism — only documents with non-empty markdown are appended to the list
handed to corpus redundancy, so a set of unreadable files cannot register as a cluster of
identical documents.

**Exception.** Any other failure is caught and converted into an equivalent `DocScore`
carrying the flag `processing_error: <ExceptionType>`. The exception type is recorded, the
loop continues, and the run result reports the error alongside the others. One bad
document never brings down the corpus.

**Normal completion.** The document is scored and flagged on its merits.

Only the exception path counts towards the run's error tally: an unsupported format and an
unreadable document are both expected outcomes, not failures. A run reporting zero errors
can still contain documents that were never scored, which is exactly why the flags carry
the reason.

An end-to-end test runs a valid PDF and a deliberately corrupted one through the pipeline
together and asserts that both produce score files, that the corpus count is 2, and that
the corrupt file carries `unreadable` — the parsing chain is resilient enough that a
corrupt PDF is short-circuited rather than raising. Nothing is dropped in either case.

## The flag vocabulary

Flags are the contract with the human reviewer: each one is a machine-readable reason to
look at a document. They are joined with `|` into the `flags` column of the report.

| Flag | Attached by | Meaning |
|---|---|---|
| `unsupported_format:<ext>` | run orchestration | A format `cqg` cannot open; flagged before parsing, the file is never opened |
| `unreadable` | run orchestration | Parsing produced no usable text; scored 0.0 without any LLM call |
| `processing_error: <ExceptionType>` | run orchestration | The document raised; the type is recorded and the run continues |
| `screen:light (<reasons>)` | run orchestration | The document took the light route; the screen's reasons are inlined |
| `auto_descriptions:<n>` | run orchestration | `n` unverified machine-written image descriptions entered the evaluated text |
| `low_coverage` | document scoring | Coverage fell below the configured threshold |
| `low_parse_confidence` | document scoring | Extraction confidence fell below 0.5 |

The reasons interpolated into `screen:light (...)` are the screen's own French reason
strings — `extraction_degradee`, `signaux_propres`, `gros_document_extraction_saine`,
`cas_limite` — joined with `; `. They are documented on the
[screening page](../scoring/two-speed-screening.md).

## Why this shape

The two invariants reinforce each other. Anti-fabrication guarantees that anything the
report asserts is defensible; score-and-flag guarantees that anything it cannot assert is
still visible. Together they make the output safe to act on: a reviewer can trust every
number that appears, and can see exactly where numbers are missing and why. A pipeline
that guessed to fill its coverage, or that dropped documents it could not handle, would
produce a cleaner-looking report that means considerably less.

## Related

- [Sectioned LLM Judgment](../scoring/llm-judgment.md) — where the predicate and the aggregation run
- [Two-Speed Screening](../scoring/two-speed-screening.md) — what the light route decides
- [Document Scoring and Corpus Outputs](../reporting/document-scoring-and-reports.md) — how coverage and flags reach the report
- [Golden Q&A Set Generation](../workflows/golden-set-generation.md) — the coverage fallback
- [Image Enrichment](../ingestion/image-enrichment.md) — the unverified-description tag
- [The run Pipeline](../workflows/run-pipeline.md) — the orchestration that applies error isolation
