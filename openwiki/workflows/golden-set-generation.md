---
type: workflow
title: Golden Q&A Set Generation
description: The cqg golden subcommand — producing a reference question/answer set for business validation, with a density-driven question count, corpus-wide questions grounded by retrieval over full text, and a coverage fallback that refuses to fabricate an answer.
tags: [golden-set, qa-generation, retrieval, embeddings, business-validation, anti-fabrication]
sources:
  - id: openwiki-source-2b78d174ffa5735999d50b8b
    resource: repo://config/golden_qa_policy.md
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-41b6896f669c97b4b685276f
    resource: repo://src/cqg/corpus_index.py
  - id: openwiki-source-b16c375f2cb0d2db7954adcd
    resource: repo://src/cqg/golden_qa.py
  - id: openwiki-source-f3839253c7c5e3d67e28a4ad
    resource: repo://src/cqg/judge.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-b5bb35ef6f2a60707bddb75d
    resource: repo://tests/test_corpus_index.py
  - id: openwiki-source-81792d29bf652c27ca85a4c6
    resource: repo://tests/test_golden_cli.py
  - id: openwiki-source-96f4e8eabb9c2b7186fe059b
    resource: repo://tests/test_golden_qa.py
generated: { by: "claude-code", at: "2026-09-09T21:41:51.597Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-09T21:41:51.597Z
---

# Golden Q&A Set Generation

`cqg golden` produces a different deliverable from `cqg run`. Where `run` answers *is this
corpus fit to ingest?*, `golden` produces a **reference question/answer set** that a business
owner reads, checks, and signs off — the artifact against which a future RAG system can be
evaluated.

The output is deliberately shaped for that audience: questions in natural end-user language,
answers grounded in the documents, and a validation column awaiting a human.

## The output contract

Both `golden_qa.xlsx` (sheet `golden_qa`) and `golden_qa.csv` carry these eight columns,
verbatim:

```
id | origine | question | reponse | sources | couvert | statut_validation | commentaire_beta
```

- **`origine`** — where the question came from: `document` or `profil` for per-document
  questions, `corpus` for cross-document ones.
- **`couvert`** — `oui` or `non`: whether the documents actually answer the question.
- **`reponse`** — the answer, or the marker `"Non couvert par le document"`.
- **`statut_validation`** — always initialized to `a_valider`. Every row is a *proposal*
  awaiting human validation, never an established fact.
- **`commentaire_beta`** — initialized empty, reserved for the reviewer's notes.

`id` is prefixed by origin: the document id for per-document rows, `corpus-` for
cross-document ones.

The CSV shares the [export safeguards](../reporting/document-scoring-and-reports.md) of the
main report — formula-injection neutralization, `;` delimiter with proper quoting, and
`utf-8-sig` so Excel renders accents.

## The orchestration

`run_golden` triages and parses the corpus, generates per-document questions for each
document that yielded text, then optionally adds corpus-wide questions. Plain-text documents
(`.txt`, `.md`) are parsed like PDFs and are therefore perfectly good golden-set sources.

Two robustness properties, both consistent with
[score-and-flag](../architecture/anti-fabrication-and-flagging.md):

- **A format `cqg` cannot open is skipped before parsing** — the loop checks the triage
  category and moves on, rather than attempting an extraction that can only yield nothing.
- **A document that fails or parses empty is skipped**, not fatal — the `continue` is
  commented as exactly that: a failing document does not bring down the rest of the corpus.
- **The whole corpus-level stage is wrapped**, so a failure there still returns the
  per-document rows already generated.

Note the asymmetry with `run`: a skipped document leaves **no trace** in the golden output.
There is no flag mechanism here, because the deliverable is a question set rather than a
corpus verdict. Use `cqg run` to find out which documents were unreadable.

## Per-document generation

One LLM call per document, over a **truncated** prefix of its markdown. This is a
deliberate cost/benefit choice distinct from judgment's full coverage: a golden set samples
representative questions, and reading the whole document is not needed to produce them.

The prompt imposes four things:

**A user profile.** Questions are framed from a configured point of view, so the same
document yields different questions for different audiences.

**A question count.** Either fixed, or the default `auto`, which hands the decision to the
model based on **information density**: a sparse document should yield few questions
(3–4), a dense one more (up to 12–15), with no fixed number imposed. Fixing an integer
instead requests exactly that many varied questions. Tests assert that `auto` produces a
density instruction and that an integer produces an exact-count instruction.

**A style constraint.** This is the most heavily specified part of the prompt, and worth
understanding. Questions must be **complete, natural sentences as a real user would type
them to a support chatbot** — everyday language, punctuation, a question mark. Keywords,
term lists and telegraphic style are explicitly forbidden, and the French prompt supplies
both counter-examples and correct forms: it forbids writing `'Delai prescription ?'` and
requires `'Quel est le delai de prescription pour agir ?'`.

The constraint exists because a golden set is only useful if it resembles real traffic. A
model left to itself tends to emit terse, keyword-shaped queries, which would produce a
benchmark that measures the wrong thing. The same style block is applied to corpus-wide
questions.

**An answering policy.** A configurable French policy governing how answers must be written
— citing references, flagging caveats and exclusions, naming the product, staying concise
and action-oriented, and never inventing. It ships two ways: a `policy` block in
configuration, and `config/golden_qa_policy.md`, which is explicitly marked as **editable by
business owners** (`éditable par les métiers`). A built-in French default applies when
neither is supplied.

## Corpus-wide questions: two stages, grounded by retrieval

The distinctive part of the workflow. A question whose answer spans several documents —
comparison, cross-reference, a contradiction between sources — is exactly what stresses a
RAG system, and cannot be produced from one document at a time.

It runs as **two separate LLM stages** with a retrieval step between them.

### Precondition

At least **two documents** are required; with fewer, generation returns an empty list
immediately. A "cross-document" question over one document would be a category error.
Corpus-level generation is enabled by default and can be switched off.

### Stage 1 — propose

The model receives a **map of the corpus**: each document's id followed by a short synopsis
(a truncated prefix). It is asked to *propose only, not answer*, and each question must
require at least two documents — comparison, relation, cross-reference, coherence or
contradiction. The same style constraint and question-count logic apply.

The synopsis is enough to see *what topics exist where*, which is all that is needed to
imagine a cross-cutting question.

### Retrieval — the grounding step

For each proposed question, the system retrieves the top-*k* chunks **across the whole
corpus** from an index built over the documents' **full text**, each chunk tagged with its
source document id.

### Stage 2 — answer

The model answers **using only the retrieved excerpts**, each prefixed with its bracketed
document id. The prompt states the absolute rule that nothing may be fabricated, and that if
the excerpts do not contain the answer it must return the marker.

### Why sources are the retrieved doc_ids

This is the design's key property. The `sources` column lists the document ids **actually
mobilized by the retrieval**, deduplicated in stable order — not the documents the model
claims to have used, and not the synopsis map.

The consequence is that a corpus question is **multi-document by construction**: its answer
was literally composed from chunks belonging to several documents, and the sources column is
a record of that fact rather than an assertion about it. The stage-1 synopsis only inspires
the question; the answer is grounded in full text.

A test verifies exactly this — two documents on different risks yield a corpus row whose
`sources` contains both ids joined by `; `.

## The retrieval index

`corpus_index.py` implements the grounding mechanism.

- **Chunking with overlap** — the same windowing logic as
  [judgment's sectioning](../scoring/llm-judgment.md), with clamped overlap and union
  coverage. A test confirms the first chunk plus subsequent tails reconstruct the text.
- **Offline static embeddings** — a `model2vec` static model, chosen because it embeds
  without a network call or GPU at query time. Loaded lazily into a module-level cache so
  the cost is paid once per process.
- **Each chunk keeps its `doc_id`**, which is what makes cross-document attribution possible
  at all.
- **Cosine ranking** — embeddings and query are L2-normalized with an epsilon guard against
  division by zero, similarity is a dot product, and the top *k* are returned with scores.
- **Empty index is safe** — retrieving from an index with no entries returns an empty list
  rather than raising, so a corpus that produced no chunks degrades quietly.

The `encoder` parameter is injectable on every function, which is how the tests run the full
retrieval path with a trivial character-frequency encoder — no model download, deterministic
results, and a genuine end-to-end exercise of chunking, indexing and ranking.

## Anti-fabrication

The [anti-fabrication rule](../architecture/anti-fabrication-and-flagging.md) applies at both
generation paths, independently. An answer is kept **only if** the model marked `couvert` as
`oui` **and** the answer text is non-empty. Every other case — absent flag, any other value,
empty text — collapses to `couvert = "non"` and the marker `"Non couvert par le document"`.

Applying it twice rather than factoring it into one shared helper means neither path can
bypass it. A test drives an uncovered question through and asserts the marker.

The practical value: a golden set is a *reference*. A fabricated answer in it would not
merely be wrong — it would become the standard against which a future system is judged,
silently encoding a falsehood into every later evaluation.

## Related

- [Anti-Fabrication and Score-and-Flag](../architecture/anti-fabrication-and-flagging.md) — the coverage fallback in context
- [System Overview](../architecture/system-overview.md) — how `golden` relates to `run`
- [LLM Provider Abstraction](../integrations/llm-providers.md) — the `judge` capability both stages use
- [Configuration and Secrets](../operations/configuration-and-secrets.md) — the `golden` block and its retrieval parameters
- [Document Scoring and Corpus Outputs](../reporting/document-scoring-and-reports.md) — the shared export safeguards
- [Sectioned LLM Judgment](../scoring/llm-judgment.md) — the same overlapping-window logic
