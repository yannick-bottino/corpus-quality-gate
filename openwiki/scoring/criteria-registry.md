---
type: contract
title: The Criteria Registry
description: The YAML registry that drives cqg's whole evaluation grid — how a criterion is declared, what each field changes downstream in judgment scope, weighted scoring and report columns, how the loader validates it, and where the extension seam is.
tags: [registry, criteria, contract, yaml, scoring, extension-seam]
sources:
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-6b1845a66655ac54d0d4b6d0
    resource: repo://src/cqg/deterministic.py
  - id: openwiki-source-78a59ac162fb1ac39266402a
    resource: repo://src/cqg/inventory.py
  - id: openwiki-source-f3839253c7c5e3d67e28a4ad
    resource: repo://src/cqg/judge.py
  - id: openwiki-source-487a7b025a60961dcab9ff1a
    resource: repo://src/cqg/registry/criteria_registry.yaml
  - id: openwiki-source-9d2f2d9e2d1816a6a6d4bd67
    resource: repo://src/cqg/registry/loader.py
  - id: openwiki-source-0d4ac7a15c4a3514756da39e
    resource: repo://src/cqg/report.py
  - id: openwiki-source-5fa58a97f0a0e23a76dda820
    resource: repo://tests/test_registry.py
generated: { by: "claude-code", at: "2026-09-09T21:41:51.597Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-11T06:45:44.636Z
---

# The Criteria Registry

`src/cqg/registry/criteria_registry.yaml` declares the **57 evaluation criteria** that the
whole pipeline scores against. It is the source of truth for the grid, and it is *data*:
the criteria are not enumerated anywhere in code, and no stage hardcodes a criterion's
weight, dimension, or scale.

This page documents the registry as a **contract** — what each field obliges downstream
code to do. The criteria themselves are not enumerated here; read the YAML for those.

The labels are a **faithful copy of an external French reference grid**, and they are
reproduced verbatim in the report's `critere` column. They must never be translated or
"corrected" — for example criterion `1.1` reads
`"Titre explicite et representatif du contenu"`, unaccented exactly as shown.

## Shape of the file

The file declares three things:

- **`scale_max`** — the top of the scoring scale (5). Every score is an integer in
  `1..scale_max`.
- **`dimension_weights`** — a map from dimension key to integer weight.
- **`criteria`** — the list of criterion declarations.

The eight dimensions and their weights, as declared:

| Dim | Theme | Weight |
|---|---|---|
| 1 | Metadata | 2 |
| 2 | Content quality | 5 |
| 3 | Readability | 4 |
| 4 | Structure | 4 |
| 5 | Fragmentability / chunking | 5 |
| 6 | Reliability and temporality | 5 |
| 7 | Disambiguation | 3 |
| 8 | Queryability | 3 |

The weights total 31, and a test pins that total — a cheap guard that catches an
accidental edit to the balance of the grid. Dimension keys are **strings**, not integers.

## The criterion contract, field by field

Each criterion declares six fields, and each one obliges a different part of the pipeline.

### `id`

The identity used everywhere: as the key the LLM is asked to answer under, as the lookup
into deterministic scores and N/A decisions, and as the `critere_id` column. Ids are
dotted, dimension-first (`1.1`, `3.4`), but nothing parses them — the `dimension` field is
authoritative, not the id prefix.

### `dimension`

Selects the weighted bucket the criterion's score accumulates into during
[document scoring](../reporting/document-scoring-and-reports.md). It must be a key present
in `dimension_weights`.

**This is not validated at load time.** The loader accepts a criterion whose dimension is
not declared, and the failure surfaces later as a `KeyError` while computing the global
percentage — after the LLM budget has already been spent. Worth knowing when editing the
registry: add the dimension weight before adding criteria that reference it.

### `weight`

The criterion's relative importance *within* its dimension (values range 1–5). It enters
both sides of the dimension ratio: the numerator as `weight × score`, the denominator as
`weight × scale_max`. It is also the sort key for the `Remediation` sheet, which orders by
descending weight so the heaviest fixable problem surfaces first.

### `tag` — `D` / `H` / `L`

Declares *how* the criterion is meant to be resolved:

- **`D`** — deterministic: resolvable from a computed signal.
- **`H`** — hybrid: a signal informs a judgment.
- **`L`** — pure judgment.

The tag is carried through to the report's `tag` column so a reader can see the nature of
each verdict.

> **The tag alone does not route a criterion.** Dispatch requires *both* that the tag is
> `D` **and** that a deterministic score was actually produced for that id. Of the 13
> `D`-tagged criteria, only 8 have a scorer in
> [`deterministic.py`](deterministic-signals.md); the remaining five fall through to LLM
> judgment despite their tag. The tag is therefore descriptive intent — a statement about
> what the criterion *could* be resolved from — while the deterministic scorer map is the
> actual dispatch key. A criterion is promoted to deterministic resolution simply by adding
> a scorer for its id, with no registry change.

### `external_dep`

Marks a criterion whose evaluation depends on an external reference grid — typical RAG
questions or business use cases — that the project does not ship. Four criteria carry it,
and a test pins that exact set, so removing the dependency is a deliberate act rather than
a silent drift.

The consequence is unconditional: such a criterion is **excluded from LLM scope and always
emitted as `not_evaluated`**, with the justification
`"Referentiel de questions/cas d'usage absent."` It is never judged and never guessed.
This places a permanent ceiling on any document's
[coverage](../reporting/document-scoring-and-reports.md) — expected, and readable in the
report rather than hidden.

### `na_possible`

Gates whether the [inventory](deterministic-signals.md) is permitted to mark the criterion
not-applicable. Eight criteria carry it, all in the readability dimension: those judging
images, figures, tables, links and formulas — precisely the objects a document may
legitimately not contain.

The gate is a **whitelist intersection**. The inventory proposes a set of N/A ids from what
it counted, then intersects it with the ids the registry declares `na_possible`. The
registry has the final say: the inventory cannot invent an N/A for a criterion the grid
says must always be judged.

## Loading and validation

`load_registry` reads the YAML and constructs Pydantic models, so field types and required
fields are enforced at load. It performs one explicit semantic check beyond that: **ids must
be unique**, otherwise it raises `ValueError("Ids de criteres dupliques dans le registre")`.

That check matters because ids are used as dictionary keys throughout — in the per-criterion
response map, in deterministic scores, in the label lookup. A duplicate would silently
shadow one criterion with another rather than failing, so it is caught at the door.

Note what is *not* validated: dimension references (above), and that criteria exist for
every declared dimension.

## The extension seam

The registry path is a **package-relative default with an override parameter**:
`load_registry(path=None)` falls back to the file shipped beside the loader module.

That signature is the extension seam for supplying a different grid — a client-specific
rubric, a reduced grid for a fast pass, or a translated one. Because every consumer takes
the `Registry` object as an argument rather than importing the file, swapping grids requires
no changes to judgment, scoring, or reporting.

`registry_fingerprint()` sits alongside it and takes the same optional path override,
returning a short content hash of the grid file. This is what stamps the grid into
[run provenance](../operations/configuration-and-secrets.md): because the fingerprint
follows the file's **content**, editing the criteria changes the `config_hash` of every
document scored afterwards.

That property matters more here than anywhere else in the configuration. The grid drives
every score — a changed weight, a changed scale, a criterion added or removed — so an edited
grid must not share a fingerprint with the old one. The component was previously a
hardcoded literal, which meant exactly that: two runs against materially different grids
were stamped identically and looked comparable.

One caveat remains for anyone using the seam: the run orchestration calls
`load_registry()` with no argument, so an alternative grid is not selectable from
configuration today.

## How the registry propagates

| Consumer | What it reads |
|---|---|
| [Inventory](deterministic-signals.md) | `na_possible` — as the whitelist for N/A decisions |
| [Judgment](llm-judgment.md) | The full criteria list to compute LLM scope, `label` for the prompt, `scale_max` for the anti-fabrication bound |
| [Document scoring](../reporting/document-scoring-and-reports.md) | `dimension`, `weight`, `scale_max`, `dimension_weights` for the two-level aggregation |
| [Reporting](../reporting/document-scoring-and-reports.md) | `label` to resolve the `critere` column |

The criteria are iterated in registry order when building results, so the order of the
`Detail` sheet is the order of the YAML file.

## Related

- [Deterministic Signals and Metrics](deterministic-signals.md) — the scorers and the N/A inventory
- [Sectioned LLM Judgment](llm-judgment.md) — how scope is computed from the registry
- [Document Scoring and Corpus Outputs](../reporting/document-scoring-and-reports.md) — the two-level weighting
- [System Overview](../architecture/system-overview.md) — the registry's place in the system
- [Configuration and Secrets](../operations/configuration-and-secrets.md) — how the grid fingerprint enters run provenance
