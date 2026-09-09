---
type: pipeline-stage
title: Corpus Triage and Document Parsing
description: How a folder of files becomes ParsedDoc objects — enumeration and classification, the layered Docling/pdfminer/pdfplumber extraction chain, (cid:NNN) font-mapping failure detection with its re-extraction attempt, and how parse_confidence is computed and penalized.
tags: [parsing, triage, ingestion, pdf, extraction, confidence, robustness]
sources:
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-0807e73ac7196a324665fd8b
    resource: repo://src/cqg/redundancy.py
  - id: openwiki-source-0d4ac7a15c4a3514756da39e
    resource: repo://src/cqg/report.py
  - id: openwiki-source-978bdc187683aafb96b74a0e
    resource: repo://src/cqg/signals.py
  - id: openwiki-source-f2e05a5624d52b19421cdd43
    resource: repo://src/cqg/triage.py
  - id: openwiki-source-15ffe11df9b60121e2241bb7
    resource: repo://tests/test_cli_e2e.py
  - id: openwiki-source-c3bd80e13bca0fabc8af5c04
    resource: repo://tests/test_parse.py
  - id: openwiki-source-348912dd3d0e7f05ba63cd33
    resource: repo://tests/test_signals.py
  - id: openwiki-source-f5f06ff27486b680ea499ebd
    resource: repo://tests/test_triage.py
generated: { by: "claude-code", at: "2026-09-09T21:41:51.597Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-09T21:41:51.597Z
---

# Corpus Triage and Document Parsing

This is the front door of both workflows. It turns a directory of files into `ParsedDoc`
objects carrying the markdown that every later stage judges. It is also the most defensive
code in the project, because the input is untrusted: real-world PDF corpora contain
corrupt files, scanned images, and documents whose fonts refuse to map to characters.

The stage has four steps: **enumerate → classify → extract → score confidence**.

## Enumerate and classify

Triage walks the corpus directory **non-recursively** in sorted order, giving a stable,
reproducible document order across runs. The admitted extensions are declared in
`triage.py` as canonical sets — the single source of truth, shared with the parser:

| Set | Extensions | Meaning |
|---|---|---|
| `PDF_EXTS` | `.pdf` | The full extraction chain |
| `TEXT_EXTS` | `.txt`, `.md` | Text carried directly; parsed without PDF machinery |
| `UNSUPPORTED_EXTS` | `.docx`, `.pptx` | Admitted so they are visible, but never opened |

`SUPPORTED_EXTS` is their union and is what the directory walk filters on.

Every file yields a record with a `doc_id` (the filename stem), a type, a **SHA-256 hash of
the full file bytes**, and a path. Note that `doc_id` is the *stem*, so two files differing
only by extension would collide on identity and on output filenames.

For PDFs, triage then opens the file with pypdf and counts pages, words, and embedded
images to assign a category from words-per-page (`wpp`) and images-per-page (`ipp`):

| Category | Condition | Interpretation |
|---|---|---|
| `unreadable` | pypdf could not open the file | Corrupt or not a real PDF |
| `scanned` | `wpp < 10` | Almost no extractable text — an image-only document |
| `born_digital` | `wpp > 100` **and** `ipp < 25` | Text-rich, lightly illustrated |
| `mixed` | everything else | Text-and-image heavy, or in the ambiguous middle band |

Non-PDF input is classified before any of that, by extension alone:

| Category | Extensions | Meaning |
|---|---|---|
| `text` | `.txt`, `.md` | Parseable; scored like any other document |
| `unsupported_format` | `.docx`, `.pptx` | Admitted and flagged; the file is never opened |

The image count is deliberately best-effort: pypdf can raise on malformed image
dictionaries, so that inner loop swallows a specific set of exceptions and continues with
a lower count rather than failing the document. Likewise a PDF that pypdf cannot open at
all returns the `unreadable` category instead of raising — corpus triage never breaks on
one bad file.

### The parser takes no category

`parse_document` used to accept a `category` argument that appeared only in its signature
and was never read. It has been removed: the extraction strategy is chosen from the
`parser` setting and from runtime failures, never from the triage verdict.

Everything past `path` is now **keyword-only**, and that is not cosmetic. Both call sites
previously passed `item["category"]` *positionally* as the second argument, so dropping the
parameter alone would have silently bound a category string to `pages` — a failure that
surfaces far from its cause, since the resulting `TypeError` inside `_confidence` is
swallowed by the Docling fallback handler. Keyword-only makes that class of positional
drift impossible rather than merely fixed once, and a test pins the signature.

The triage category is no longer unconsumed, though: it routes the unsupported-format case
in the [run orchestration](../workflows/run-pipeline.md). That is the right layer for it —
classification decides *whether to attempt* extraction, not *how* to extract.

The SHA-256 content hash triage computes for every file still has no consumer. It remains
available for future deduplication or caching; content-level duplicate detection is done
separately over extracted text in
[corpus redundancy](../reporting/document-scoring-and-reports.md).

### The non-PDF extensions

`.txt` and `.md` are **parsed and scored like any other document**. They need no PDF
machinery: `_plain_text_extraction` reads the file, applies the same NFKC normalization,
and splits it on blank lines into text blocks. No new dependency was required.

The decoding choice carries a quiet design win. The file is read as `utf-8-sig` — which
strips a BOM — with `errors="replace"`, so decoding damage becomes U+FFFD replacement
characters. Those are *already counted* by `cid_failure_fraction`, the same signal built for
PDF font-mapping failures. A mis-decoded text file therefore has its `parse_confidence`
penalized and is flagged for review by the existing mechanism, instead of passing as clean
text. One mechanism, two failure modes.

A text `ParsedDoc` traverses the rest of the pipeline safely because the downstream stages
operate on a markdown string, not on a PDF. Two details make it work: `pages` is `None`, so
the per-page confidence cap simply does not apply; and the image list is empty, which makes
[enrichment](image-enrichment.md) a no-op. A test asserts that a text document never reaches
Docling, pdfminer or pdfplumber.

`.docx` and `.pptx` are a different matter: `cqg` cannot open them. They are still admitted
by triage — dropping them would be a silent loss, which
[score-and-flag](../architecture/anti-fabrication-and-flagging.md) forbids — but they are
short-circuited in the run orchestration with the flag `unsupported_format:<ext>` **before**
any parsing is attempted, so the file is never opened. That is deliberately distinct from
`unreadable`, which means the document *was* opened and yielded nothing.

Supporting them properly would require `python-docx` and `python-pptx` as runtime
dependencies, which is a decision with
[license-gate](../operations/testing-and-license-gate.md) consequences and was left out of
scope.

## The extraction chain

Extraction is layered, and each layer exists to cover a failure mode of the one before it.

```
parser == "docling"?
  └─ Docling subprocess, per page batch      ── on any exception ──┐
                                                                    ▼
  legacy: pdfminer text + pdfplumber typing
    ├─ empty markdown? ──────────────────────────────────┐
    ├─ cid fraction above threshold? → try pdfplumber-only, keep the better one
    └─ success                                            ▼
                                          pdfplumber-only (fallback_used = True)
                                            └─ still failing / empty ──► empty ParsedDoc, confidence 0.0
```

**Docling (default).** Runs out-of-process in page batches. Its own failure containment —
OOM detection, per-batch fallback, batching tradeoffs — is substantial enough to have its
own page: [The Docling Subprocess Boundary](docling-subprocess.md). From this chain's point
of view it is a single call that either returns a document or raises, and a raise falls
through to legacy.

**Legacy: pdfminer + pdfplumber.** pdfminer extracts per-page text; pdfplumber supplies the
*typing* — table and image blocks, plus image bounding boxes. The two are assembled into
markdown with `[[IMAGE:p=<page>;idx=<n>]]` placeholders inserted in reading position
(images sorted by vertical position within each page), which is what makes
[enrichment](image-enrichment.md) able to substitute descriptions back at the right spot.

**pdfplumber-only.** Used two ways: as the cid re-extraction candidate, and as the last
resort when the primary chain raises or yields nothing.

All extracted text passes through **NFKC normalization**, which flattens ligatures (`ﬁ`,
`ﬂ`) and other compatibility forms into their component characters. This matters for a
downstream text pipeline and has no effect on French accented letters.

### The chain never raises

The terminal `except` returns an empty-markdown `ParsedDoc` at confidence 0.0 rather than
propagating. This is the parsing stage's contribution to
[score-and-flag](../architecture/anti-fabrication-and-flagging.md): a document that cannot
be read is a *result*, not an error. A test asserts directly that a corrupt file produces a
`ParsedDoc` instead of an exception, and the end-to-end test confirms a corrupt PDF is
flagged `unreadable` while its neighbours score normally.

### Bounded memory

Both pdfplumber paths call `page.flush_cache()` after each page. pdfplumber caches the
parsed objects of every page it touches, and on a several-hundred-page PDF that
accumulation is enough to exhaust memory. Flushing per page keeps the footprint bounded and
independent of document length.

## The `(cid:NNN)` failure and its repair

This is the most consequential robustness mechanism in the stage.

When a PDF's font encoding cannot be mapped to Unicode — common in older documents — pdfminer
emits literal `(cid:123)` tokens instead of characters, or Unicode replacement characters
`�`. The document *appears* to extract successfully: the text is present in volume, the
blocks are populated, and every length- or structure-based quality measure reports health.
The text is simply unreadable.

The `cid_failure_fraction` signal measures the share of the text occupied by these
artifacts. It is 0.0 on clean text and rises toward 1.0 as extraction degrades, and it
drives two mechanisms.

**Re-extraction.** Above a threshold cid fraction, the chain attempts a pdfplumber
re-extraction and compares. The decision rule is deliberately conservative: `_better_extraction`
switches to the fallback **only if the fallback's cid fraction is strictly lower** than the
primary's. Equal fractions keep the primary. Tests pin both directions — a cleaner fallback
is adopted and marked as used, and a clean primary is kept even when an alternative exists.
The attempt itself is wrapped so that a failing re-extraction leaves the primary result
intact.

**Confidence penalty.** Whether or not re-extraction helped, the residual cid fraction
penalizes the confidence score directly (below).

## How `parse_confidence` is computed

Confidence is a single number in `[0, 1]` summarizing how much to trust the extraction. It
is consumed by [screening](../scoring/two-speed-screening.md), which uses it as a
degradation signal, and by [document scoring](../reporting/document-scoring-and-reports.md),
which raises `low_parse_confidence` below 0.5.

The computation is a base, two caps, and one multiplicative penalty:

1. **Base.** An equal blend of two components: a length component that saturates at a
   modest character count, and the ratio of blocks carrying text to all blocks. Empty
   markdown short-circuits to 0.0 immediately.
2. **Cap — content loss per page.** If the page count is known and the extracted characters
   per page fall below a floor, confidence is capped low. This catches a parser silently
   failing on *some* pages: overall length looks acceptable, but the per-page density
   betrays the loss.
3. **Cap — fallback used.** If the pdfplumber fallback was adopted, confidence is capped at
   a moderate ceiling. The result is usable but was not the intended path.
4. **Penalty — cid fraction.** Confidence is multiplied by `1 - cid_fraction`. This is the
   only *multiplicative* term, and it is multiplicative on purpose: it scales the whole
   confidence down in proportion to the share of text that is genuinely lost. A
   half-unreadable document can no longer come out with high confidence, which the
   in-code comment records as the concrete failure that motivated the mechanism — a real
   document scoring 0.947 while being unreadable.

A behavioural detail worth knowing: on the **Docling path, `fallback_used` is always
`False`** when confidence is computed, even if per-batch pdfminer fallback fired inside the
Docling extraction. The fallback cap therefore never applies to a Docling-parsed document;
degradation there surfaces through the cid penalty and the per-page cap instead.

## Related

- [The Docling Subprocess Boundary](docling-subprocess.md) — the default parser's isolation and batching
- [Image Enrichment](image-enrichment.md) — the consumer of image placeholders and coordinates
- [Deterministic Signals and Metrics](../scoring/deterministic-signals.md) — where `cid_failure_fraction` sits among the other signals
- [Two-Speed Screening](../scoring/two-speed-screening.md) — the main consumer of `parse_confidence`
- [The run Pipeline](../workflows/run-pipeline.md) — how triage records reach this stage
- [Anti-Fabrication and Score-and-Flag](../architecture/anti-fabrication-and-flagging.md) — why an unreadable document is a result rather than an error
