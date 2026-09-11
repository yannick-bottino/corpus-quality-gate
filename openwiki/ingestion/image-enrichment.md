---
type: pipeline-stage
title: Image Enrichment
description: The optional stage that converts a document's images into text before evaluation — cropping each image out of the PDF, describing it with a vision model independent of the judge LLM, and substituting the description into the markdown that is actually scored and ingested.
tags: [enrichment, vlm, images, multimodal, anti-fabrication, human-in-the-loop]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-11T06:45:44.636Z
sources:
  - id: openwiki-source-bf4bd188e5cad9eab90456b4
    resource: repo://config/config.example.yaml
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-f3702b5dc23472a869a57236
    resource: repo://src/cqg/enrich.py
  - id: openwiki-source-c19eabdc855679b7af548ca1
    resource: repo://src/cqg/llm/manual.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-15ffe11df9b60121e2241bb7
    resource: repo://tests/test_cli_e2e.py
  - id: openwiki-source-ff80dcfb97b14b00d06a2087
    resource: repo://tests/test_enrich.py
  - id: openwiki-source-30660c9911c84372885f3d7f
    resource: repo://tests/test_llm.py
  - id: openwiki-source-c3bd80e13bca0fabc8af5c04
    resource: repo://tests/test_parse.py
generated: { by: "claude-code", at: "2026-09-09T22:03:23.095Z" }
---

# Image Enrichment

A multimodal PDF carries meaning its extracted text does not: diagrams, charts, tables
rendered as pictures, screenshots with embedded labels. To a text-only quality gate — and
to a text-only RAG pipeline — that content is simply absent.

Enrichment closes the gap. It renders each referenced image, asks a vision model to
describe it, and writes the description into the markdown in the image's place. It is
**optional**, enabled either by the `--enrich` flag or by `enrichment.enabled` in
configuration.

## Enrich *before* evaluation

The ordering is the stage's central design decision, and it is stated explicitly in the run
orchestration: the document's markdown is **replaced** by the enriched markdown before
metrics, screening, and judgment run.

The reasoning is that quality should be scored on *what will actually be ingested into
RAG*, not on raw text still full of opaque placeholders. A document whose diagrams have
been described is genuinely more usable downstream, and the score should reflect that. The
inverse ordering — score first, enrich afterwards — would systematically under-rate
illustrated documents relative to how they will really perform.

The enriched markdown is also persisted as `<doc_id>.enriched.md` so a reviewer can inspect
exactly what was judged. A test confirms both halves: the enriched file is written, and it
contains the injected description text.

## The placeholder round trip

Enrichment depends on a contract established during
[parsing](document-parsing.md):

1. **Parsing emits a placeholder.** Every image found becomes an `ImageRef` carrying the
   page, an index, a bounding box in PDF points, and a `placeholder` string of the form
   `[[IMAGE:p=<page>;idx=<n>]]`. That exact token is written into the markdown at the
   image's reading position.
2. **Enrichment substitutes text for the token.** For each `ImageRef`, the stage replaces
   its placeholder in the markdown with one of three outcomes.
3. **The result replaces the document's markdown** before scoring.

The placeholder is therefore a *join key* between two stages that never share an object
beyond `ParsedDoc`. It is also what makes the deferred manual workflow possible: as long as
the token survives in the text, the description can still be filled in later.

**This contract is PDF-only.** Cropping needs a bounding box in PDF points on a page that
can be rasterized, and only the PDF extraction chain produces one. Word and PowerPoint
documents count their pictures as `Block(kind="image")` — so the image-related criteria
still see them — but emit no `ImageRef` and therefore no placeholder, which makes
enrichment a silent no-op for them. That is deliberate: PowerPoint's EMU coordinates
describe a slide rather than a PDF page and Word exposes no page geometry at all, so
filling those fields would hand the cropper numbers that produce wrong crops. Text
documents are in the same position for the simpler reason that they have no images.

Rendering crops the image out of the page rather than extracting the embedded image
stream: the page is rasterized at a scale factor, and the bounding box — pdfplumber
coordinates in points, top-left origin — is scaled to pixels and cropped. The crop is saved
as a PNG under a per-document image directory. Rendering the page and cropping is robust to
how the image was embedded in the PDF, which extracting streams is not.

## Three outcomes per image

Exactly one of three things happens to each `ImageRef`, and the distinctions are load-bearing.

**Decorative — skipped.** If either side of the bounding box is below `min_side_pts`, the
image is treated as decorative (a rule, a bullet glyph, a logo fragment) and its placeholder
is replaced with `[Image decorative ignoree]`. No render and no model call is made, so
decorative artwork costs nothing. **Size is the sole criterion for this decision.**

**Described.** The image is rendered and sent to the vision model. A non-empty description
is injected wrapped in the tag
`[Image (description automatique, non verifiee): {desc}]`.

**Failed.** Any exception during rendering or description is caught and the placeholder is
replaced with `[Image non decrite: {type}]`, naming the exception type. One unreadable
image never fails the document — the same
[score-and-flag](../architecture/anti-fabrication-and-flagging.md) discipline the rest of
the pipeline follows.

### An empty description is not "decorative"

There is a fourth case that deliberately produces *no* substitution. If the model returns an
empty description for an image that passed the size filter, the placeholder is **left
intact**.

This is an explicit invariant, commented in both `enrich_document` and
`apply_descriptions` and pinned by two separate tests that assert the placeholder survives
and that the text `decorative ignoree` does **not** appear. Conflating "not described yet"
with "not worth describing" would silently discard real content and, worse, would make the
loss invisible — the document would read as though the image had been assessed and
dismissed. Keeping the placeholder marks the image as outstanding work, which is exactly
what the manual workflow depends on.

## Unverified descriptions are auditable

Every injected description is labelled `description automatique, non verifiee` — machine
written, not human checked. The label is not cosmetic: the run **counts** its occurrences in
the enriched markdown and attaches the count to the document as the flag
`auto_descriptions:<n>`.

That flag is the audit trail. Because enrichment happens before evaluation, the document's
score rests in part on text no human has verified, and a reviewer needs to know how much.
A document scoring well on the strength of twenty unverified machine descriptions warrants
different scrutiny than one scoring well on extracted text. A test asserts the flag is
raised on an end-to-end run with enrichment enabled.

## Manual mode: the human-in-the-loop round trip

`ManualVLM` implements the same client interface but describes nothing itself. It exists so
descriptions can be produced by a human or by an offline session, and it turns the
enrichment stage into a two-pass workflow.

**Pass 1 — collect.** `describe_image` records each image it is asked about (path, context,
placeholder) and returns the empty string. By the invariant above, every placeholder
survives the enrichment pass untouched. At the end of the run the orchestration calls
`flush()` if the client supports it, writing the accumulated manifest to disk and returning
its path in the run result under `image_manifest` — without that call there would be no
record of what needs describing.

**Pass 2 — fill and inject.** A human fills the `description` fields in the manifest JSON.
There are then two ways to apply them:

- **`apply_descriptions`** — injects the filled descriptions into an existing markdown
  string directly, using the same tag. A test walks this full round trip: enrich leaves the
  placeholder, flush writes the manifest, a description is filled in, and applying it leaves
  no residual placeholder.
- **Re-run.** `ManualVLM` re-reads an existing manifest at construction and indexes any
  filled descriptions by placeholder. On a second run `describe_image` returns the stored
  description, so enrichment injects it *during* the normal pass — and therefore
  **before evaluation**, preserving the enrich-before-eval property without a separate
  apply step. A manifest that cannot be parsed is treated as absent rather than fatal.

The empty-description invariant is what makes both passes safe: a placeholder still unfilled
after pass 2 stays a placeholder and can be filled on the next iteration.

## The VLM is independent of the judge

The vision client is built from `enrichment.vlm` when present, falling back to the main
`llm` block. Two consequences follow:

- A different provider or model can describe images than judges text — useful when only one
  of the two needs vision, or when a cheaper model suffices for descriptions.
- The client is constructed **only when enrichment is active**, so an enrichment API key is
  not required for a plain `run`.

Image description calls are also excluded from the judgment call counter by the cost
instrumentation, keeping `cost.json` a measure of judgment spend. See
[LLM Provider Abstraction](../integrations/llm-providers.md).

## Related

- [Corpus Triage and Document Parsing](document-parsing.md) — where placeholders and bounding boxes originate
- [The Docling Subprocess Boundary](docling-subprocess.md) — why pdfplumber still supplies image geometry on the Docling route
- [Anti-Fabrication and Score-and-Flag](../architecture/anti-fabrication-and-flagging.md) — the unverified-content invariant
- [LLM Provider Abstraction](../integrations/llm-providers.md) — the client interface and the manual provider
- [Configuration and Secrets](../operations/configuration-and-secrets.md) — the `enrichment` block
- [The run Pipeline](../workflows/run-pipeline.md) — where enrichment sits in the sequence
