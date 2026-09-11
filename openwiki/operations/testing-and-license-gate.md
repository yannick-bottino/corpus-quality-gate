---
type: operations-guide
title: Testing and the License Gate
description: How cqg verifies itself — the invariants each area of the pytest suite pins, the synthetic-PDF and mock-provider fixtures that keep end-to-end runs hermetic, and the permissive-license dependency constraint enforced by a checkable script.
tags: [testing, pytest, quality-gates, licensing, compliance, ci]
sources:
  - id: openwiki-source-05ccef8d4cf1698187f20464
    resource: repo://pyproject.toml
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-a008312c35a1268ab293d5cb
    resource: repo://scripts/check_licenses.py
  - id: openwiki-source-f677215832a3297e22304de0
    resource: repo://src/cqg/config.py
  - id: openwiki-source-32ae41a9ecb698838dd793e6
    resource: repo://src/cqg/llm/mock.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-0d4ac7a15c4a3514756da39e
    resource: repo://src/cqg/report.py
  - id: openwiki-source-c68b4fcfcbfc7045e09425f5
    resource: repo://src/cqg/screen.py
  - id: openwiki-source-15ffe11df9b60121e2241bb7
    resource: repo://tests/test_cli_e2e.py
  - id: openwiki-source-81af13fa7982f0b3becf1286
    resource: repo://tests/test_config.py
  - id: openwiki-source-81792d29bf652c27ca85a4c6
    resource: repo://tests/test_golden_cli.py
  - id: openwiki-source-96f4e8eabb9c2b7186fe059b
    resource: repo://tests/test_golden_qa.py
  - id: openwiki-source-5ae9caedcf7eaa19f9cf0d18
    resource: repo://tests/test_judge_batch.py
  - id: openwiki-source-42c6d60421d221776b69fe39
    resource: repo://tests/test_licenses.py
  - id: openwiki-source-c3bd80e13bca0fabc8af5c04
    resource: repo://tests/test_parse.py
  - id: openwiki-source-1fb869e707757275b0a8994a
    resource: repo://tests/test_report_export.py
  - id: openwiki-source-9fc38c4696400c0068133e6e
    resource: repo://tests/test_report_scoring.py
  - id: openwiki-source-81cf9f57b4380dad067c7e02
    resource: repo://tests/test_screen.py
  - id: openwiki-source-f5f06ff27486b680ea499ebd
    resource: repo://tests/test_triage.py
generated: { by: "claude-code", at: "2026-09-09T22:03:23.095Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-11T06:45:44.636Z
---

# Testing and the License Gate

```bash
python -m pytest -q
```

The suite currently reports **146 passed, 1 skipped in about 4 seconds**. That combination —
a full end-to-end pipeline suite that runs in seconds with no network and no credentials —
is a deliberate design outcome, and this page explains how it is achieved and what it
actually guarantees.

There is no `pytest.ini`, `conftest.py`, or `[tool.pytest]` section: the suite relies on
default discovery. Two tests read repository-root-relative paths, so **run pytest from the
repository root**.

## The suite maps to invariants, not to modules

The most useful way to read the suite is by the property each area protects. When changing
code, the table below points at the test that will notice.

| Invariant | Representative tests |
|---|---|
| **[Anti-fabrication](../architecture/anti-fabrication-and-flagging.md)** — a score survives only if whole, in scale, and justified | `tests/test_judge.py` demotes a `scored` verdict lacking a score, one out of scale, and a model-asserted `na`; `tests/test_judge_batch.py` repeats it for batched responses including empty justifications |
| **The light route never fabricates** | `tests/test_judge.py::test_skip_llm_makes_no_llm_calls_and_never_fabricates` asserts zero LLM calls *and* `not_evaluated` criteria, with a mock primed to return a valid score |
| **Section coverage and overlap** | `tests/test_judge_batch.py` proves zero-overlap sections reconstruct the text exactly, that overlapping sections cover the whole document and genuinely overlap, and that the default overlap is proportional |
| **Cross-section aggregation** | `tests/test_judge_batch.py` pins the median rule and that a single aberrant section is outvoted; `test_batch_calls_equal_n_sections` pins the cost model |
| **[Screening](../scoring/two-speed-screening.md) routes** | `tests/test_screen.py` covers all four outcomes, plus the two regression guards: an image-rich low-block-integrity document must **not** be called degraded, and a large healthy document must route `full` despite a low global TTR while a genuinely degraded large one still routes `light` |
| **[Parser fallback chain](../ingestion/document-parsing.md)** | `tests/test_parse.py` asserts the legacy parser never invokes Docling, that the Docling route dispatches and falls back on failure, that per-page batching spawns one subprocess per page, that an OOM return code degrades to pdfminer, and that a corrupt file **never raises** |
| **cid detection and repair** | `tests/test_signals.py` for the fraction itself; `tests/test_parse.py` for the confidence penalty and the strictly-better fallback rule in both directions |
| **Length-robust vocabulary measurement** | `tests/test_signals.py::test_mattr_stays_high_on_long_repetitive_document` |
| **Export safety** | `tests/test_report_export.py` and `tests/test_golden_qa.py` each pin delimiter/quote/newline escaping **and** spreadsheet formula-injection neutralization, for both output families |
| **Scoring and coverage arithmetic** | `tests/test_report_scoring.py` covers levels, the `low_coverage` flag, and that a `scored` row with a null score is excluded from coverage |
| **Error isolation** | `tests/test_cli_e2e.py::test_run_isolates_and_flags_bad_document` runs a good and a corrupt PDF together and asserts both produce score files |
| **Enrich-before-eval** | `tests/test_cli_e2e.py` asserts the enriched markdown is what gets scored and that `auto_descriptions:` is flagged; `tests/test_enrich.py` pins the empty-description invariant and the manual round trip |
| **[Registry](../scoring/criteria-registry.md) shape** | `tests/test_registry.py` pins the criteria count, the dimension-weight total, and the presence of external-dependency criteria |
| **Run-fingerprint coverage** | `tests/test_config.py` asserts the hash changes for every scoring section, ignores `paths`, and covers a section `config_hash` has never heard of — the last one guards against the allowlist failure that caused the original provenance gap |
| **Parser signature cannot drift** | `tests/test_parse.py::test_parse_document_takes_no_positional_beyond_path` pins that only `path` is positional, so a stray argument can never bind to `pages` |
| **Plain-text extraction avoids PDF machinery** | `tests/test_parse.py` asserts a text document reaches neither Docling, pdfminer nor pdfplumber, and that decoding damage lowers `parse_confidence` |
| **Formats are distinguished, not conflated** | `tests/test_triage.py` pins the `text`, `office` and `unsupported_format` categories and the `pages` semantics per format; `tests/test_parse.py` pins the office extractors, that they never reach a PDF parser, that they emit no `ImageRef`, and that a corrupt office file returns rather than raises; `tests/test_cli_e2e.py` scores a `.md`, a `.docx` and a `.pptx` in one corpus, and drives the `unsupported_format` exit separately |
| **Level labels stay canonical** | `tests/test_report_scoring.py` asserts the orchestration cannot introduce a second spelling of a level |
| **[Provider layer](../integrations/llm-providers.md)** | `tests/test_llm.py` covers the factory, the missing-key error, tolerant JSON extraction, and the manual manifest round trip; `tests/test_llm_instrument.py` covers the metering policy |

## What makes the suite hermetic

Three choices remove every external dependency from the end-to-end tests.

**PDFs are generated at test time.** Tests build their fixtures with `reportlab`, a
**dev-only dependency** declared in the `dev` extra alongside `pytest` and `pip-licenses` —
it is not a runtime dependency. Nothing is checked into the repository as a binary fixture,
so tests are readable (the expected text is right there in the test) and each one shapes its
input precisely: a table drawn with explicit `GRID` and `BOX` borders because pdfplumber
detects *vector lines* rather than text layout, a PDF with real text so a fallback path has
something to fall back to, or literal corrupt bytes.

**The LLM is the mock provider.** End-to-end tests configure `provider: mock`, so no network
call and no credential is involved, and responses are deterministic. Because the mock keys
its scripted responses on a prompt substring, a test can assert the pipeline's behaviour for
a *specific* criterion under a *specific* model response.

**The parser is `legacy`.** Every configuration written by an end-to-end or CLI test sets
`parsing.parser: legacy`, deliberately bypassing Docling. Docling loads machine-learning
models and runs a subprocess per page batch — orders of magnitude slower than the suite's
total runtime, and it would pull `torch` into the test environment. The legacy pdfminer +
pdfplumber chain exercises the same interfaces and produces the same `ParsedDoc`, so the
pipeline is covered without the cost. Docling's own behaviour is tested instead by
**mocking `subprocess.run`**, which is how batching and OOM fallback can be asserted
deterministically without the real converter.

### The one opt-in test

`tests/test_parse.py::test_docling_real_extraction` is the single skipped test. It is gated
behind the `CQG_TEST_DOCLING=1` environment variable, marked as heavy because of `torch`,
and is the only test that requires the real parser installed. It verifies that Docling
genuinely produces *structured* markdown by asserting pipe characters appear for a drawn
table — the table fidelity that justifies preferring Docling in the first place.

Run it deliberately when changing the parsing boundary:

```bash
CQG_TEST_DOCLING=1 python -m pytest tests/test_parse.py -q
```

## The license gate

The project constrains itself to **MIT / Apache-2.0 / BSD dependencies only, for commercial
use**. This is a real project constraint, not an aspiration, and it is checkable:

```bash
python scripts/check_licenses.py
```

The script is a **denylist**, not a license resolver. It holds a set of packages known to
carry incompatible licensing — notably the PyMuPDF family and several PDF/ML tools that
would otherwise be natural choices for this problem domain — enumerates the *installed*
distributions via `importlib.metadata`, and reports the intersection.

The exit behaviour is what makes it usable as a CI gate: on a violation it prints
`Licences interdites detectees: [...]` and **exits 1**; otherwise it prints `Licences OK`
and exits 0.

Support for plain-text documents was added **without any new runtime dependency** — it is
`read_text()` plus the existing normalization — so it left this constraint untouched.

Office support did add two: `python-docx` and `python-pptx` are declared runtime
dependencies. Both clear the gate, and the addition was cheaper than it looks — both were
already installed as transitive dependencies of `docling-slim`, which pulls them in for its
own office backends. Declaring them makes an existing presence explicit rather than
enlarging the dependency surface. Both are MIT-licensed, their shared `lxml` dependency is
BSD-3-Clause, and none of the three appears in the denylist.

Checking what is *installed* rather than what is *declared* is the important design choice.
A forbidden package pulled in transitively by a dependency is caught, which a manifest scan
would miss.

`tests/test_licenses.py` guards the gate itself from both sides:

- **The denylist works** — a mixed list yields exactly the forbidden members, and a clean
  list yields nothing.
- **Legitimate dependencies are not falsely flagged** — the parsing stack is asserted clean,
  a guard against an over-broad future denylist.
- **The declared dependency set is correct** — one test parses `pyproject.toml` with
  `tomllib` and asserts Docling is declared as a core dependency, pinning the fact that the
  default parser is a real dependency rather than an optional extra.

That last test is why pytest must run from the repository root: it opens `pyproject.toml` by
a relative path.

## Related

- [System Overview](../architecture/system-overview.md) — the dependency posture in context
- [Anti-Fabrication and Score-and-Flag](../architecture/anti-fabrication-and-flagging.md) — the invariants most of the suite defends
- [Corpus Triage and Document Parsing](../ingestion/document-parsing.md) — the chain the parser tests exercise
- [The Docling Subprocess Boundary](../ingestion/docling-subprocess.md) — why the real parser is opt-in
- [The run Pipeline](../workflows/run-pipeline.md) — what the end-to-end tests drive
