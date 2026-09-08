# Guide — running the full Docling parsing + LLM coverage

Everything is integrated and tested (123 tests). What follows runs the **full** run
(222 pages) + the substantive LLM judgment (criterion 3b of the handoff) — ideally on a machine
with **≥ 8 GB of RAM** (the original sandbox, ~1.2 GB, can only run Docling at
batch=1 and kills runs > ~2 min).

## Prerequisites (already done in this repo, to redo elsewhere)
```bash
cd corpus-quality-gate
export VIRTUAL_ENV="$PWD/.venv"
uv pip install --python .venv/bin/python "torch==2.13.0" "torchvision==0.28.0" \
    --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/bin/python opencv-python-headless   # headless server: avoids libGL.so.1
uv pip install --python .venv/bin/python -e ".[dev]"              # docling is now a core dependency
```

## 1. Set the batch size according to RAM
`config/config.claude_cli.yaml` → `parsing.docling_batch_pages`:
- **1** (default): ~1.1 GB peak, safe under ~1.2 GB, but slow (~37 min / 222 p, models reloaded per page).
- **10–20** on a machine ≥ 8 GB: much faster (a single model load per batch).
Measured reference: 1 p = 1092 MB, 5 p = 1708 MB, 10 p = 1625 MB (fresh). Leave a margin.

## 2. Run the full pipeline (Docling parsing + LLM judgment without an API key)
```bash
cd corpus-quality-gate && . .venv/bin/activate
python main.py run ../test_data --config config/config.claude_cli.yaml --out ../outputs/run_docling
```
- `parser: docling` is already the default in this config → parsing uses Docling
  (subprocess per batch, per-page pdfminer fallback if a batch OOMs).
- The substantive judgment is delegated to the `claude` CLI (provider `claude_cli`, ~$0.30/call,
  ~45 calls). The corrected triage routes « Le Cahier Ma Santé » to **full** → it is indeed judged.

## 3. Check the result
```bash
# The target doc must be judged (n_calls > 0, coverage > 0), not "screen:light"
cat "../outputs/run_docling/Le Cahier Ma Santé (AGA - AEP).score.json"
cat ../outputs/run_docling/cost.json          # n_calls per doc
```
Criterion 3b is satisfied if `coverage_pct > 0` and `n_calls > 0` on the target doc.

## 4. Measure extraction quality (autoresearch harness)
```bash
python outputs/autoresearch/verify_parse_quality.py docling   # label->value association (expected ~83%)
python outputs/autoresearch/verify_parse_quality.py legacy    # baseline (~37%)
```

## Recommended next iteration (autoresearch #2)
Wire up the winning strategy **Docling + pdfminer completeness** (100% value recall;
recovers `145/200/220/400 %`) as a parser mode, then re-run `verify_parse_quality.py`.
See `outputs/autoresearch/README.md` (Goal/Metric/Verify) and `benchmark-docling-cahier-ma-sante.md`.

## Recap of the measured facts
- Docling: label→value association **37% → 83%**; output as structured Markdown tables.
- Weakness of Docling alone: loses a few values (`55/145/200/220/400 %`) → corrected by the merge.
- The legacy parser (pdfminer) remains available (`parsing.parser: legacy`) as a lightweight fallback.
