---
type: operations-guide
title: Configuration and Secrets
description: The YAML configuration surface that parameterizes every cqg stage, the rule that no API key is ever stored in plaintext, the difference between the two shipped configurations, and the run fingerprint stamped into every scored document — including what that fingerprint does not cover.
tags: [configuration, secrets, operations, provenance, yaml, credentials]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T21:30:42.164Z
sources:
  - id: openwiki-source-3c31ddb57801e0f385098e58
    resource: repo://config/config.claude_cli.yaml
  - id: openwiki-source-bf4bd188e5cad9eab90456b4
    resource: repo://config/config.example.yaml
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-f677215832a3297e22304de0
    resource: repo://src/cqg/config.py
  - id: openwiki-source-f3839253c7c5e3d67e28a4ad
    resource: repo://src/cqg/judge.py
  - id: openwiki-source-12c8799a8cb6e53fa1e21fea
    resource: repo://src/cqg/llm/base.py
  - id: openwiki-source-8d6d550a60308fe69d50bbff
    resource: repo://src/cqg/llm/claude_cli.py
  - id: openwiki-source-bf3b15b22d143311cdbe443a
    resource: repo://src/cqg/llm/providers.py
  - id: openwiki-source-b6095db5ec5025983f3c1227
    resource: repo://src/cqg/parse.py
  - id: openwiki-source-15ffe11df9b60121e2241bb7
    resource: repo://tests/test_cli_e2e.py
  - id: openwiki-source-81af13fa7982f0b3becf1286
    resource: repo://tests/test_config.py
generated: { by: "claude-code", at: "2026-09-08T21:30:42.164Z" }
---

# Configuration and Secrets

A run is parameterized by a single YAML file passed with `--config`. It covers the judge
LLM, section sizing, parsing, enrichment, golden generation, and thresholds.

## No API key in plaintext

This is the project's stated security rule, and the mechanism is a deliberate indirection:

> The configuration stores the **name of an environment variable**, never a key value.

The `api_key_env` field holds a variable name — `CQG_LLM_API_KEY` by default. The provider
reads that variable from the process environment at construction time. A configuration file
can therefore be committed, shared, or attached to a ticket without carrying a credential,
and rotating a key means changing the environment, not the repository.

The failure mode is deliberately loud and late. Construction **succeeds** even when the
variable is unset; the error is raised at **call time**, and the message names the missing
variable so the fix is unambiguous:

```
Cle API absente: definir la variable d'environnement CQG_LLM_API_KEY
```

Every credential-requiring operation performs this check independently. Details of the
resolution and the provider set are on
[LLM Provider Abstraction](../integrations/llm-providers.md).

Two shipped provider options need no credential at all: `mock`, and `claude_cli`, which
borrows an already-authenticated CLI session.

## What each section controls

Rather than transcribing the YAML — `config/config.example.yaml` is itself the documented
template, commented inline — here is what each block actually changes downstream.

| Section | Controls | Stage page |
|---|---|---|
| `llm` | The **judge** LLM: provider, model, endpoint, credential variable, and `max_doc_chars` (a compatibility budget; sectioned judgment covers 100% of the document) | [LLM Provider Abstraction](../integrations/llm-providers.md) |
| `judge` | `section_chars` and `section_overlap` — the window size and overlap that determine how many sections a document is split into, and therefore **how many LLM calls it costs** | [Sectioned LLM Judgment](../scoring/llm-judgment.md) |
| `parsing` | `parser` (`docling` or `legacy`) and `docling_batch_pages`, the RAM/latency tradeoff for the out-of-process parser | [Docling Subprocess](../ingestion/docling-subprocess.md), [Parsing](../ingestion/document-parsing.md) |
| `enrichment` | Whether images are described before evaluation, the decorative size floor, and a **`vlm` sub-block that is a full provider configuration in its own right** | [Image Enrichment](../ingestion/image-enrichment.md) |
| `golden` | Profile, answering policy, question count, whether corpus-wide questions are generated, and the retrieval parameters (`k`, `chunk_chars`, `chunk_overlap`) backing them | [Golden Q&A Generation](../workflows/golden-set-generation.md) |
| `thresholds` | `coverage_flag_below`, the coverage level under which a document is flagged | [Document Scoring](../reporting/document-scoring-and-reports.md) |
| `paths` | `workdir` — present in both shipped files | — |

The `enrichment.vlm` sub-block deserves emphasis: it lets the vision model be a *different
provider, model, and credential* from the judge. Only when it is absent does enrichment
fall back to the main `llm` block.

The `golden.policy` block and `config/golden_qa_policy.md` hold the French answering policy
imposed on generated answers, and are intended to be edited by business owners rather than
engineers.

## Loading, defaults, and validation

`load_config` is a thin wrapper: read the file, `yaml.safe_load`, return a plain `dict`.
There is **no schema validation** — no Pydantic model, no required-key check, no type
coercion. A missing file or malformed YAML raises; an unknown key is silently ignored, and a
key of the wrong type surfaces later as a `TypeError` at its point of use.

Consequently **defaults live at the call sites**, applied through `dict.get` where each
value is consumed:

- In the `run` orchestration: the LLM block defaults to `mock`; coverage threshold `0.7`;
  `max_doc_chars` `24000`; `section_chars` `8000`; `section_overlap` `auto`; enrichment
  disabled; `min_side_pts` `24.0`; parser `docling`; `docling_batch_pages` unset, letting
  the parser apply its own default.
- In the `golden` orchestration: profile `"utilisateur metier"`, the built-in French policy
  constant `_GOLDEN_POLICY_DEFAUT`, `n_questions` `auto`, corpus-level generation enabled,
  `k` `6`, `chunk_chars` `1000`, `chunk_overlap` `100`.

The practical effect is that a nearly empty configuration file still runs end to end on the
mock provider — which the end-to-end tests rely on, several passing configurations of only
a handful of lines. The cost is that a **typo in a key name is not an error**; it silently
selects the default. When a setting appears to have no effect, check its spelling and
nesting first.

Note that the `golden.profile` default in code differs from the value in both shipped
configuration files, so the effective profile depends on whether the key is present.

`section_overlap` accepts the sentinel string `auto`, normalized case-insensitively to
`None`, which the judge then interprets as a proportional default rather than zero overlap.

## The two shipped configurations

**`config/config.example.yaml`** — the documented template, commented inline, intended to
be copied and filled. It selects `mock` by default so it runs unmodified, and shows the
hosted-provider fields (`base_url`, `model`, `api_key_env`) ready to be switched on. It is
the reference for the full schema.

**`config/config.claude_cli.yaml`** — a test configuration for environments with **no API
key at all**. It selects the `claude_cli` provider, adds `cli_timeout`, and drops
`api_key_env` entirely, since none is used. It also **disables image enrichment**, and the
reason is a real capability limit rather than a preference: the Claude CLI client
implements no `describe_image`. Its `enrichment.vlm` block is left on `mock`.

Both files otherwise agree on sectioning, thresholds, parsing and golden settings, so the
difference between them is genuinely just the credential story and the vision capability.

## Run provenance: `config_hash`

Every `DocScore` carries a `config_hash`, a short SHA-256 digest computed once per run and
stamped into every document's score file. Its purpose is provenance: to tell whether two
score files are comparable.

The digest is built from a canonical JSON payload — sorted keys, non-ASCII preserved — so it
is stable across dictionary ordering. Tests confirm it is deterministic for identical input
and changes when the model changes.

### What the fingerprint does not cover — a real limitation

The payload contains exactly four things: the `llm` block, the `thresholds` block, and two
version strings. **`judge`, `parsing`, and `enrichment` are excluded.**

This is verifiable directly: two configurations differing in `judge.section_chars`,
`parsing.parser`, *and* `enrichment.enabled` simultaneously produce an **identical**
`config_hash`.

That is a genuine provenance gap, because all three settings change scoring outcomes:

- `judge.section_chars` and `section_overlap` change how many sections a document is split
  into, and the score is a **median across sections** — different sectioning can produce a
  different score from identical inputs and an identical model.
- `parsing.parser` changes the extracted text itself, and therefore every deterministic
  signal and every judgment built on it.
- `enrichment.enabled` changes whether machine-written image descriptions are part of the
  scored text at all.

So two score files bearing the same `config_hash` are **not** necessarily comparable. When
comparing runs, verify the sectioning, parser, and enrichment settings separately —
`cost.json` is a useful cross-check, since a change in sectioning shows up directly as a
change in calls per document.

Additionally, the `registry_version` and `policy_version` components are passed as the
hardcoded literal `"v1"` at the call site rather than derived from the registry or policy
files. Editing the criteria registry or the answering policy therefore does not change the
hash either.

## Related

- [LLM Provider Abstraction](../integrations/llm-providers.md) — how the credential indirection is resolved
- [The run Pipeline](../workflows/run-pipeline.md) — where configuration values are read and defaults applied
- [Sectioned LLM Judgment](../scoring/llm-judgment.md) — what `judge` sizing costs
- [The Docling Subprocess Boundary](../ingestion/docling-subprocess.md) — the batch-size tradeoff
- [Golden Q&A Set Generation](../workflows/golden-set-generation.md) — the `golden` block
- [Document Scoring and Corpus Outputs](../reporting/document-scoring-and-reports.md) — where the threshold and the hash surface
