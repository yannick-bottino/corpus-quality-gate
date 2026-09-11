---
type: process-boundary
title: The Docling Subprocess Boundary
description: Why cqg's default parser runs out-of-process in page batches — process isolation converts an out-of-memory kill into a detectable return code, per-batch fallback preserves content, and batch size is a tuned RAM/latency tradeoff.
tags: [parsing, docling, subprocess, memory, failure-containment, operations]
sources:
  - id: openwiki-source-bf4bd188e5cad9eab90456b4
    resource: repo://config/config.example.yaml
  - id: openwiki-source-8fc8d14f7ab12ca5833bc793
    resource: repo://docs/benchmark-docling-cahier-ma-sante.md
  - id: openwiki-source-152a88b414832cd1539f749f
    resource: repo://docs/GUIDE-run-docling-complet.md
  - id: openwiki-source-453c0952dd215ca017137f07
    resource: repo://src/cqg/docling_worker.py
  - id: openwiki-source-f3702b5dc23472a869a57236
    resource: repo://src/cqg/enrich.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-978bdc187683aafb96b74a0e
    resource: repo://src/cqg/signals.py
  - id: openwiki-source-c3bd80e13bca0fabc8af5c04
    resource: repo://tests/test_parse.py
generated: { by: "claude-code", at: "2026-09-09T22:03:23.095Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-11T06:45:44.636Z
---

# The Docling Subprocess Boundary

Docling is the default parser. Unlike every other component in `cqg`, it is **not called
in-process**. Each page batch is converted by a freshly spawned `python -m
cqg.docling_worker` subprocess, and the parent communicates with it only through argv, a
temporary file, and an exit code.

Only PDFs reach this boundary. `parse_document` dispatches every directly readable format
— `.txt`, `.md`, `.docx`, `.pptx` — to a separate path *before* the parser choice is
consulted, so none of them ever spawns a worker.

The boundary is PDF-only by construction, not by policy: `_docling_extraction` opens with
`PdfReader(path)` to count the pages it must batch. There is nothing to gain by routing
office formats through it either — the subprocess exists to survive machine-learning
out-of-memory kills, and reading a Word or PowerPoint package is pure XML tree-walking
that cannot cause one.

That indirection is not incidental. It exists because Docling loads machine-learning
models that dominate the process's memory footprint, and because an out-of-memory kill is
not a catchable Python exception.

## The failure-containment argument

When the Linux OOM killer terminates a process, it sends `SIGKILL`. A `SIGKILL` cannot be
caught, handled, or cleaned up after — the process simply ceases. If Docling ran in-process
and exhausted memory, the entire `cqg` run would vanish mid-corpus, taking every
already-computed score with it.

Running it in a child process converts that unrecoverable event into an ordinary,
observable value. The parent sees a **non-zero return code** (`-9` / `137` for a `SIGKILL`)
and continues. This is the central design claim of the boundary: *isolation turns a crash
into a data point*. A test exercises exactly this path by forcing a return code of `137`
and asserting that the document still comes back with content.

The isolation is layered. Three independent failure conditions are handled:

1. **A batch fails** — non-zero return code, or a zero return code with empty output. The
   batch falls back to pdfminer text for those pages (below).
2. **The worker hangs** — a generous timeout bounds the wait; an overrun raises out of
   `_docling_extraction`.
3. **Docling is entirely unusable** — an import failure, a total conversion failure, or an
   empty document raises `RuntimeError`, and the *whole* parse falls back to the legacy
   pdfminer + pdfplumber chain described on
   [Corpus Triage and Document Parsing](document-parsing.md).

At no level does a Docling problem propagate to the caller as an exception. The parsing
chain never raises — that is the [score-and-flag](../architecture/anti-fabrication-and-flagging.md)
guarantee, and this boundary is where most of the work of honouring it happens.

## The worker's CLI contract

The worker is a self-contained module with a deliberately minimal interface, so the parent
depends on as little as possible:

```
python -m cqg.docling_worker <pdf_path> <out_markdown_path> [start] [end]
```

- **Argument count is validated as exactly 3 or 5** (including the program name); anything
  else exits `2` without attempting a conversion.
- **`start` and `end` are 1-based and inclusive**, and are passed straight through as
  Docling's page range. Omitting them converts the whole document.
- **Output goes to a file, not stdout.** The parent creates a temporary `.md` path, passes
  it in, reads it back, and deletes it in a `finally` block regardless of outcome. Keeping
  the payload off stdout means the worker's own diagnostics can never corrupt the result.
- **Exit codes are the whole protocol**: `0` on success, `1` from a catch-all around
  `main`, `2` on a malformed invocation. Every exception inside the worker is converted to
  a non-zero exit rather than a traceback the parent would have to parse.

The worker's pipeline options are fixed rather than configurable, and the choices matter:
OCR is **disabled** (the target corpus is digital, not scanned PDFs — scanned documents are
identified upstream by [triage](document-parsing.md) instead), table-structure recognition
is **enabled** (table fidelity is the reason to prefer Docling at all), and page and
picture image generation are both **disabled**, since images are handled separately through
the pdfplumber coordinate path.

### Why table structure justifies the cost

Docling is markedly more expensive than the legacy chain, so the table-structure option is
what earns it its place. The evidence is recorded in
[`docs/benchmark-docling-cahier-ma-sante.md`](../../docs/benchmark-docling-cahier-ma-sante.md),
a parsing benchmark run against a 222-page insurance guarantee document.

Its decisive finding concerns not text *cleanliness* but **label-to-value association**. The
legacy pdfminer path extracts clean text — negligible `(cid:NNN)` corruption — yet
*flattens* guarantee tables: columns are serialized separately, so every label is emitted
first and every value long afterwards. The benchmark measures one guarantee label separated
from its own rate by roughly **17,000 characters**. For a RAG pipeline that is fatal in a way
no text-quality metric detects: a chunk containing the label does not contain the value, so
the guarantee is not retrievable in context. Docling preserves the association by emitting
the table as Markdown rows.

This is why the [confidence and signal machinery](document-parsing.md) cannot substitute for
the parser choice — the flattened output scores as healthy on every measure `cqg` computes.
Consult the benchmark for the per-candidate measurements and the ground-truth methodology;
they are not reproduced here.

## Batching and the memory/latency tradeoff

The parent reads the page count, then walks the document in batches, spawning a **fresh
subprocess for each one**. A test pins this behaviour directly: a three-page PDF at
`batch_pages=1` produces exactly three subprocess invocations and three concatenated
outputs.

The reason for a fresh process per batch is stated in the code: the models reload on every
batch, but **RAM is genuinely returned to the OS when the process exits**. Reusing one
process would amortize model loading but let the footprint grow until the whole-document
conversion is killed.

This makes batch size a direct tradeoff:

- **Small batches** — lower peak memory, but the model load cost is paid once per batch, so
  throughput suffers.
- **Large batches** — one model load amortized over many pages, much faster, but a
  proportionally higher peak.

The default is the most conservative possible value, one page per batch, chosen to fit a
constrained environment. The setting is exposed in configuration as
`parsing.docling_batch_pages` and is intended to be raised on machines with comfortable
RAM. Measured peak-RSS and runtime figures for each batch size, the RAM thresholds behind
the default, and the full installation and run procedure are recorded in
[`docs/GUIDE-run-docling-complet.md`](../../docs/GUIDE-run-docling-complet.md) — consult it
before changing the value rather than guessing.

The timeout is deliberately generous, sized for large documents; an overrun is treated as
a failure of the whole Docling attempt and hands over to the legacy chain.

## Per-batch fallback: degrade, don't lose

A failing batch does not fail the document. When a batch returns a non-zero code **or**
returns successfully with empty content, the parent substitutes the pdfminer text for
exactly those pages and keeps going.

Two details make this work well:

- **Lazy computation.** The pdfminer page-text extraction for the whole document is
  computed only on the *first* batch failure and then reused for any subsequent one. A run
  where every batch succeeds never pays for it; a run where Docling is entirely unavailable
  pays for it once.
- **Index translation.** Batch bounds are 1-based and inclusive, so the fallback converts
  them to 0-based list indices and guards against a short pdfminer result.

The consequence is graceful, partial degradation. A document where Docling handles 200
pages and dies on 3 comes back with 200 structured pages and 3 plainly-extracted ones,
rather than either crashing or silently losing 3 pages. The document is only abandoned to
the legacy chain if *nothing at all* was produced, which raises `RuntimeError`.

## Division of labour after extraction

Docling produces markdown, but it does not produce everything the pipeline needs. After a
successful extraction the parent deliberately re-opens the PDF with pdfplumber:

- **Docling supplies the text structure.** The markdown is split on blank lines into text
  blocks. These blocks carry page `0` — the batch markdown does not preserve a per-paragraph
  page number, so page attribution is simply not asserted rather than guessed.
- **pdfplumber supplies typing and coordinates.** Table and image blocks, and critically the
  image *bounding boxes*, come from pdfplumber.

That second half is what keeps the [image enrichment](image-enrichment.md) path functional
on the Docling route. Enrichment must crop a specific rectangle out of a specific page to
send to a vision model; Docling's markdown export, with picture generation disabled,
provides no such geometry. Image placeholders are therefore generated from the pdfplumber
coordinates and appended at the end of the markdown, in the same
`[[IMAGE:p=<page>;idx=<n>]]` format the legacy chain uses inline — so downstream stages
cannot tell which parser produced the document.

## Related

- [Corpus Triage and Document Parsing](document-parsing.md) — the surrounding extraction chain and the legacy fallback
- [`docs/benchmark-docling-cahier-ma-sante.md`](../../docs/benchmark-docling-cahier-ma-sante.md) — the parsing benchmark behind the table-fidelity argument
- [`docs/GUIDE-run-docling-complet.md`](../../docs/GUIDE-run-docling-complet.md) — setup and measured batch-size figures
- [Image Enrichment](image-enrichment.md) — the consumer of the pdfplumber coordinates
- [Configuration and Secrets](../operations/configuration-and-secrets.md) — where `parsing.parser` and `parsing.docling_batch_pages` are set
- [The run Pipeline](../workflows/run-pipeline.md) — how parser settings reach this stage
- [Anti-Fabrication and Score-and-Flag](../architecture/anti-fabrication-and-flagging.md) — why the chain never raises
