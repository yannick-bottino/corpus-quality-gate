---
type: integration-layer
title: LLM Provider Abstraction
description: The pluggable LLM layer of cqg — the capability contract every client implements, the factory that selects one from configuration, the hosted-API, Claude CLI, manual and mock implementations, the tolerant JSON extraction they share, and the wrapper that meters judgment cost.
tags: [llm, providers, integration, anthropic, openai, azure, instrumentation, testing]
sources:
  - id: openwiki-source-3c31ddb57801e0f385098e58
    resource: repo://config/config.claude_cli.yaml
  - id: openwiki-source-bf4bd188e5cad9eab90456b4
    resource: repo://config/config.example.yaml
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-b324806e0b781575cf038d77
    resource: repo://src/cqg/cli.py
  - id: openwiki-source-12c8799a8cb6e53fa1e21fea
    resource: repo://src/cqg/llm/base.py
  - id: openwiki-source-8d6d550a60308fe69d50bbff
    resource: repo://src/cqg/llm/claude_cli.py
  - id: openwiki-source-ada6bc0d2c90f334a8174d7f
    resource: repo://src/cqg/llm/instrument.py
  - id: openwiki-source-c19eabdc855679b7af548ca1
    resource: repo://src/cqg/llm/manual.py
  - id: openwiki-source-32ae41a9ecb698838dd793e6
    resource: repo://src/cqg/llm/mock.py
  - id: openwiki-source-bf3b15b22d143311cdbe443a
    resource: repo://src/cqg/llm/providers.py
  - id: openwiki-source-5ae9caedcf7eaa19f9cf0d18
    resource: repo://tests/test_judge_batch.py
  - id: openwiki-source-106a52b0ffa333d51c722aca
    resource: repo://tests/test_llm_instrument.py
  - id: openwiki-source-30660c9911c84372885f3d7f
    resource: repo://tests/test_llm.py
generated: { by: "claude-code", at: "2026-09-11T06:45:44.636Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-11T06:45:44.636Z
---

# LLM Provider Abstraction

Every LLM call in `cqg` goes through a small abstraction in `src/cqg/llm/`. The layer
exists so the pipeline can run against a hosted API, an authenticated CLI, a human, or
nothing at all, without any stage knowing which.

## The capability contract

`LLMClient` is an abstract base declaring three operations, and the split between them is
deliberate — it is a **capability contract**, not a uniform interface:

| Operation | Status | Used by |
|---|---|---|
| `judge(prompt, schema)` | **abstract** — every client must implement it | [Golden Q&A generation](../workflows/golden-set-generation.md), both stages |
| `judge_batch(prompt, schema)` | optional, raises by default | [Sectioned judgment](../scoring/llm-judgment.md), one call per section |
| `describe_image(path, context)` | optional, raises by default | [Image enrichment](../ingestion/image-enrichment.md) |

The two optional operations have concrete default implementations that raise
`NotImplementedError` with an explicit French message — `"Ce provider LLM ne supporte pas
le jugement batche"` and `"Ce provider LLM ne supporte pas la description d'image"`.

**An unsupported capability fails loudly rather than degrading silently.** A client that
cannot batch does not quietly fall back to per-criterion calls, and one that cannot see
images does not return an empty description that would be mistaken for "nothing to
describe" — an outcome the enrichment stage treats as meaningful. Making the gap an
exception keeps it visible, and because the caller runs inside the run's per-document
`try`/`except`, it surfaces as a `processing_error` flag rather than a crash.

The practical consequence is that a client only needs the capabilities its intended callers
use. `ManualVLM` implements only image description and raises on `judge`; the Claude CLI
client implements both judgment forms but no vision.

## The factory

`from_config` maps the configuration's `provider` field to a client, importing each
implementation lazily so an optional dependency is required only if actually selected:

| `provider` | Client | Notes |
|---|---|---|
| `mock` (default) | `MockLLM` | Test seam; also the fallback when no `llm` block is configured |
| `openai`, `azure_openai`, `anthropic` | `ProviderLLM` | Hosted APIs, key from environment |
| `claude_cli` | `ClaudeCLILLM` | No API key; delegates to the `claude` CLI |
| `manual` | `ManualVLM` | Human-in-the-loop image description |

An unrecognized value raises `ValueError` naming the provider rather than silently
defaulting.

Two of these are easy to overlook because they take no API key at all. `claude_cli`
delegates judgment to the locally installed `claude` binary and is selected by the shipped
`config/config.claude_cli.yaml`; `manual` is the provider behind the enrichment manifest
workflow, where a human fills the descriptions in offline. Both are real, shipped paths
rather than placeholders, and the README's configuration section lists all six.

## Hosted providers

`ProviderLLM` covers OpenAI, Azure OpenAI, and Anthropic behind one class, branching on
transport where the SDKs differ and sharing everything else.

**Credentials.** The constructor reads `api_key_env` — the *name* of an environment
variable, defaulting to `CQG_LLM_API_KEY` — and resolves it from the environment. The key
value never appears in configuration. Construction succeeds even when the variable is
unset; the failure is raised at **call time**, with a message naming the missing variable:
`"Cle API absente: definir la variable d'environnement <NAME>"`. All three operations
perform this check independently, and tests assert it for both `judge` and
`describe_image`. See
[Configuration and Secrets](../operations/configuration-and-secrets.md).

**Transport differences.** OpenAI-family calls request a JSON object response format;
Anthropic calls specify an explicit token ceiling. Both pin `temperature` to 0 for
reproducibility. `judge_batch` uses the same transport as `judge` — only the prompt and the
expected response shape differ — but raises the Anthropic token ceiling substantially,
since a batched response covers many criteria at once.

**Vision.** `describe_image` base64-encodes the PNG and sends it in each SDK's image
message format. Its prompt asks for visible text, chart and table data, and meaning, in the
document's own language, and instructs the model not to fabricate uncertain values —
consistent with the [anti-fabrication](../architecture/anti-fabrication-and-flagging.md)
posture applied to the description tag downstream.

## Tolerant JSON extraction

Every provider parses model output through the shared `_extract_json`, which recovers a
JSON object through three tiers:

1. Strip a fenced code block (` ```json ` or bare ` ``` `) if one wraps the object.
2. Parse the text directly.
3. On a decode error, take the substring between the first `{` and the last `}` and parse
   that.

This exists because models routinely wrap structured output in prose or fences even when
asked not to, and because both judgment and golden generation depend on parsing a JSON
object out of every response. Without it, an otherwise perfect response prefixed by "Here
is the JSON:" would be lost — and lost responses become
`not_evaluated` criteria, so tolerance here directly protects coverage. A test exercises
both the fenced and the prose-wrapped forms.

## The Claude CLI provider: judgment without an API key

`ClaudeCLILLM` exists for a specific, real constraint: a Claude Code *subscription* is not
exposed as an API key, so an environment with an authenticated `claude` CLI has usable
model access but nothing to put in `api_key_env`.

The client delegates each call to a subprocess:

- **The prompt goes through stdin, not argv.** Judgment prompts contain whole document
  sections and would exceed argument-length limits; stdin has no such bound.
- **Structured output is requested** via the CLI's JSON output format, and the model's text
  is read from the envelope's `result` field, then parsed with the same `_extract_json` as
  the API path.
- **Two independent failure channels are both checked.** A non-zero return code raises with
  the truncated stderr; a zero exit with the envelope's `is_error` set also raises, with the
  truncated result. Checking only the exit code would silently accept an error payload as a
  judgment.
- **The binary is resolved** from configuration, then `PATH`, then a bare name; a timeout
  bounds each call.
- **A session-nesting guard variable is removed from the child environment**, so calling out
  to the CLI from inside a Claude Code session is not blocked.

Note that this client implements no `describe_image`; the shipped `config.claude_cli.yaml`
correspondingly disables enrichment.

## Test and human seams

**`MockLLM`** is the test seam and the default provider. It returns scripted responses keyed
by **substring match against the prompt** — the caller seeds a marker it knows will appear
in the prompt (typically a fragment of the section text) and maps it to a response, with a
configurable default when nothing matches. It maintains two independent script tables, one
for `judge` and one for `judge_batch`, since the two return different shapes. Its batched
default is an empty dict, meaning "no criterion answered", which lets a test assert that
unanswered criteria become `not_evaluated`.

This design is what makes the entire suite hermetic and fast: end-to-end tests exercise the
real pipeline with no network, no credentials, and deterministic responses. See
[Testing and the License Gate](../operations/testing-and-license-gate.md).

**`ManualVLM`** is the human seam, described in full on
[Image Enrichment](../ingestion/image-enrichment.md). It records the images it is asked
about into a manifest and returns descriptions a human filled in on a previous pass. It
raises on `judge` — `"ManualVLM ne juge pas de texte"` — because it is a vision seam only.

## Cost instrumentation

`CountingLLM` is a decorator, not a provider: it wraps another client and counts judgment
calls and total prompt characters, delegating everything through. The run wraps the judge
LLM in it and records the two counters per document into `cost.json`.

Two policy decisions matter:

- **Both judgment forms count**, so with sectioned judgment `n_calls` per document equals
  the number of sections — making `cost.json` a direct readout of the cost model described
  on [Sectioned LLM Judgment](../scoring/llm-judgment.md).
- **`describe_image` is deliberately not counted.** It passes through untouched. The
  counters measure *judgment* spend, so enabling enrichment does not inflate the number
  that is used to reason about judgment cost. A test pins this asymmetry explicitly.

`reset()` zeroes both counters, and the run calls it immediately before judging each
document. Without it the counters would accumulate across the corpus and `cost.json` would
report cumulative rather than per-document figures.

## Related

- [Sectioned LLM Judgment](../scoring/llm-judgment.md) — the main consumer of `judge_batch`
- [Golden Q&A Set Generation](../workflows/golden-set-generation.md) — the main consumer of `judge`
- [Image Enrichment](../ingestion/image-enrichment.md) — the consumer of `describe_image`
- [Configuration and Secrets](../operations/configuration-and-secrets.md) — provider selection and the environment-variable indirection
- [Document Scoring and Corpus Outputs](../reporting/document-scoring-and-reports.md) — where `cost.json` is written
- [Testing and the License Gate](../operations/testing-and-license-gate.md) — how the mock keeps the suite hermetic
