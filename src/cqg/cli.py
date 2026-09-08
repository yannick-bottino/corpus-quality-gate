import argparse
from pathlib import Path
from .config import load_config, config_hash
from .registry.loader import load_registry
from .triage import triage_corpus
from .parse import parse_document
from .deterministic import compute_metrics
from .llm.base import from_config
from .llm.instrument import CountingLLM
from .judge import score_document
from .screen import screen_document
from .report import compute_doc_score, write_doc_json, write_corpus_report
from .redundancy import corpus_redundancy
from .enrich import enrich_document
from .golden_qa import generate_golden_qa, generate_corpus_golden_qa, write_golden_qa
from .models import DocScore
import json

_GOLDEN_POLICY_DEFAUT = (
    "Repondre uniquement a partir du document. Citer la source. Si l'information n'est pas "
    "presente, repondre 'Non couvert par le document'."
)

def run_golden(corpus_dir: str, config_path: str, out_dir: str) -> dict:
    # `cqg golden` subcommand: produces a reference question/answer set per
    # document (golden set), to be VERIFIED by the business (statut_validation column).
    # Reference-free and anti-fabrication: an answer is kept only if the document
    # covers it explicitly, otherwise 'Non couvert par le document'. The LLM comes from
    # the config (real endpoint at AXA, or offline in-session judgment).
    cfg = load_config(config_path)
    llm = from_config(cfg.get("llm", {"provider": "mock"}))
    golden_cfg = cfg.get("golden", {})
    profile = golden_cfg.get("profile", "utilisateur metier")
    policy = golden_cfg.get("policy", _GOLDEN_POLICY_DEFAUT)
    # n_questions: "auto" (the LLM decides from the density) or an integer (set by hand).
    n_questions = golden_cfg.get("n_questions", "auto")
    corpus_level = golden_cfg.get("corpus_level", True)
    parser = cfg.get("parsing", {}).get("parser", "docling")
    docling_batch_pages = cfg.get("parsing", {}).get("docling_batch_pages")
    rows, docs = [], []
    for item in triage_corpus(corpus_dir):
        try:
            doc = parse_document(item["path"], item["category"], pages=item.get("pages"), parser=parser,
                                 docling_batch_pages=docling_batch_pages)
            if not doc.markdown.strip():
                continue
            rows.extend(generate_golden_qa(doc, profile, llm, policy, n_questions))
            docs.append(doc)
        except Exception:
            # Score-and-flag: a failing document does not bring down the rest of the corpus.
            continue
    # Corpus-wide Q/A (answer spanning several documents), grounded by retrieval.
    if corpus_level and len(docs) >= 2:
        try:
            rows.extend(generate_corpus_golden_qa(
                docs, profile, llm, policy, n_questions,
                k=int(golden_cfg.get("k", 6)),
                chunk_chars=int(golden_cfg.get("chunk_chars", 1000)),
                overlap=int(golden_cfg.get("chunk_overlap", 100))))
        except Exception:
            pass
    return write_golden_qa(rows, out_dir)

def run(corpus_dir: str, config_path: str, out_dir: str, enrich: bool = False) -> dict:
    cfg = load_config(config_path)
    reg = load_registry()
    # Cost instrumentation (Part 2 of the levers plan): counts the judgment
    # calls and the prompt chars per doc, central criterion of levers A and C.
    llm = CountingLLM(from_config(cfg.get("llm", {"provider": "mock"})))
    cost = {}
    chash = config_hash(cfg, registry_version="v1", policy_version="v1")
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    threshold = cfg.get("thresholds", {}).get("coverage_flag_below", 0.7)
    max_doc_chars = cfg.get("llm", {}).get("max_doc_chars", 24000)
    # Section-based judgment (lever A): configurable size and overlap.
    judge_cfg = cfg.get("judge", {})
    section_chars = int(judge_cfg.get("section_chars", 8000))
    _ov = judge_cfg.get("section_overlap", "auto")
    section_overlap = None if str(_ov).strip().lower() == "auto" else int(_ov)
    enrich_on = enrich or cfg.get("enrichment", {}).get("enabled", False)
    vlm = None
    min_side_pts = cfg.get("enrichment", {}).get("min_side_pts", 24.0)
    parser = cfg.get("parsing", {}).get("parser", "docling")
    docling_batch_pages = cfg.get("parsing", {}).get("docling_batch_pages")
    if enrich_on:
        # Enrichment VLM decoupled from the judgment LLM: built only if
        # enrichment is active, so as not to require its API key otherwise.
        evlm_cfg = cfg.get("enrichment", {}).get("vlm") or cfg.get("llm", {"provider": "mock"})
        vlm = from_config(evlm_cfg)
    scores, parsed, errors = [], [], []
    for item in triage_corpus(corpus_dir):
        doc_id = item["doc_id"]
        try:
            doc = parse_document(item["path"], item["category"], pages=item.get("pages"), parser=parser,
                                 docling_batch_pages=docling_batch_pages)
            if not doc.markdown.strip():
                # Score-and-flag: unreadable document (S14 parsing never raises) flagged
                # for human review without going through compute_metrics/score_document (no
                # LLM call on empty content) and without polluting duplicate detection.
                ds = DocScore(doc_id=doc_id, global_pct=0.0, level="Inadapté", coverage_pct=0.0,
                              dimensions={}, criteria=[], worst_sections=[],
                              flags=["unreadable"], config_hash=chash)
                write_doc_json(ds, str(out))
                scores.append(ds)
                continue
            n_auto_desc = 0
            if enrich_on and doc.images:
                img_dir = str(out / "images" / doc.doc_id)
                enriched_md = enrich_document(doc, item["path"], vlm, img_dir,
                                              min_side_pts=min_side_pts)
                (out / f"{doc.doc_id}.enriched.md").write_text(enriched_md, encoding="utf-8")
                # Enrich-before-eval: quality is scored on the ENRICHED markdown (what will
                # really be ingested into RAG), not on the raw text with placeholders.
                # Anti-fabrication guard: descriptions keep the 'non verifiee' tag and their
                # presence is surfaced as a flag for human review (score-and-flag).
                n_auto_desc = enriched_md.count("description automatique, non verifiee")
                doc = doc.model_copy(update={"markdown": enriched_md})
            if doc.markdown.strip():
                parsed.append((doc.doc_id, doc.markdown))
            metrics = compute_metrics(doc, reg)
            # Lever C: two-speed triage. A degraded or obviously clean doc is
            # routed "light" (LLM judgment skipped, doc flagged); otherwise full judgment.
            screen = screen_document(doc, metrics)
            llm.reset()
            criteria = score_document(doc, reg, metrics, llm, chash, max_doc_chars=max_doc_chars,
                                      section_chars=section_chars, section_overlap=section_overlap,
                                      skip_llm=(screen["route"] == "light"))
            cost[doc.doc_id] = {"n_calls": llm.n_calls, "prompt_chars": llm.total_prompt_chars}
            ds = compute_doc_score(doc.doc_id, criteria, reg, doc.parse_confidence, chash, threshold)
            if screen["route"] == "light":
                ds.flags.append(f"screen:light ({'; '.join(screen['reasons'])})")
            if n_auto_desc:
                ds.flags.append(f"auto_descriptions:{n_auto_desc}")
        except Exception as exc:
            # Score-and-flag: a failing document is flagged for human review, never
            # dropped silently, and never brings down the rest of the corpus.
            ds = DocScore(doc_id=doc_id, global_pct=0.0, level="Inadapté", coverage_pct=0.0,
                          dimensions={}, criteria=[], worst_sections=[],
                          flags=[f"processing_error: {type(exc).__name__}"], config_hash=chash)
            errors.append({"doc_id": doc_id, "error": f"{type(exc).__name__}: {exc}"})
        write_doc_json(ds, str(out))
        scores.append(ds)
    report = write_corpus_report(scores, reg, str(out))
    redundancy = corpus_redundancy(parsed)
    (out / "corpus_redundancy.json").write_text(
        json.dumps(redundancy, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "cost.json").write_text(
        json.dumps(cost, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {"corpus_report": report, "n_docs": len(scores), "n_errors": len(errors),
              "errors": errors, "redundancy": str(out / "corpus_redundancy.json"),
              "cost": str(out / "cost.json")}
    if vlm is not None and hasattr(vlm, "flush"):
        # Manual mode: persists the manifest of images to describe (filled in-session
        # or offline), otherwise no trace exists to complete the enrichment.
        result["image_manifest"] = vlm.flush()
    return result

def main() -> int:
    parser = argparse.ArgumentParser(prog="cqg")
    parser.add_argument("command", choices=["run", "golden"])
    parser.add_argument("corpus")
    parser.add_argument("--config", default="config/config.example.yaml")
    parser.add_argument("--out", default="./workdir/out")
    parser.add_argument("--enrich", action="store_true")
    args = parser.parse_args()
    if args.command == "run":
        result = run(args.corpus, args.config, args.out, enrich=args.enrich)
        print(f"Termine: {result['n_docs']} documents. Rapport: {result['corpus_report']['xlsx']}")
    elif args.command == "golden":
        result = run_golden(args.corpus, args.config, args.out)
        print(f"Golden Q/R genere: {result['xlsx']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
