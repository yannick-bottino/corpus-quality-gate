import argparse
import warnings
from pathlib import Path
from . import parse_store
from .config import load_config, config_hash
from .registry.loader import load_registry, registry_fingerprint
from .triage import triage_corpus
from .parse import parse_document
from .deterministic import compute_metrics
from .llm.base import from_config
from .llm.instrument import CountingLLM
from .judge import score_document
from .screen import screen_document
from .report import compute_doc_score, write_doc_json, write_corpus_report
from .redundancy import corpus_redundancy
from .enrich import enrich_document, count_auto_descriptions
from .golden_qa import generate_golden_qa, generate_corpus_golden_qa, write_golden_qa
from .models import DocScore, ParsedDoc, ParseProvenance
from .triage import TEXT_EXTS, OFFICE_EXTS
import json

_GOLDEN_POLICY_DEFAUT = (
    "Repondre uniquement a partir du document. Citer la source. Si l'information n'est pas "
    "presente, repondre 'Non couvert par le document'."
)


def _parsed_items(corpus_dir: str):
    """Yields a parsed_input/ entry in the shape the raw triage items have.

    Generator rather than a list: a parsed entry carries its blocks, and loading a whole
    corpus of them upfront would undo the bounded memory the per-page parsing buys.
    """
    for md_path in parse_store.parsed_markdown_paths(corpus_dir):
        entry = parse_store.read_parsed_doc(md_path)
        prov = entry.sidecar.provenance if entry.sidecar else None
        yield {"doc_id": entry.doc.doc_id, "path": str(md_path),
               "type": prov.source_type if prov else "md",
               "pages": prov.source_pages if prov else None,
               "category": prov.category if prov else "parsed",
               "doc": entry.doc, "flags": entry.flags}


def _corpus_items(corpus_dir: str, parsed_mode: bool):
    return _parsed_items(corpus_dir) if parsed_mode else triage_corpus(corpus_dir)


def _refuse_colliding_doc_ids(items: list[dict]) -> None:
    """Refuses a corpus where two sources share a stem, before anything is written.

    `doc_id` is the file stem, so `rapport.docx` and `rapport.pdf` -- a Word source next
    to its PDF export, an ordinary shape for a client corpus -- both claim `rapport.md`.
    One of the two would be silently skipped as "already parsed", and `--force` would
    then overwrite rather than recover it. There is no honest way to pick a winner, so
    this fails loudly before any file is written, the way an ambiguous folder does.
    """
    seen: dict[str, str] = {}
    for item in items:
        clash = seen.get(item["doc_id"])
        if clash:
            raise ValueError(
                f"Deux sources portent le meme nom '{item['doc_id']}' et ecriraient le "
                f"meme fichier parse : {clash} et {item['path']}. Renommez l'une des deux.")
        seen[item["doc_id"]] = item["path"]


def parse_corpus(corpus_dir: str, config_path: str, out_dir: str,
                 enrich: bool = False, force: bool = False) -> dict:
    # `cqg parse` subcommand: turns a raw_input/ into a parsed_input/, i.e. the documents
    # AS THEY WILL BE INGESTED into RAG. The image -> text enrichment belongs here (Q9):
    # it needs the source PDF, which scoring must no longer touch.
    cfg = load_config(config_path)
    if parse_store.is_parsed_input(corpus_dir):
        raise ValueError(f"{corpus_dir} est deja un parsed_input/ : rien a parser.")
    if Path(out_dir).resolve() == Path(corpus_dir).resolve():
        raise ValueError(
            "Le dossier de sortie ne peut pas etre le dossier source : parsed_input/ et "
            "raw_input/ doivent etre separes, sinon le dossier devient ambigu.")
    items = triage_corpus(corpus_dir)
    _refuse_colliding_doc_ids(items)
    parser = cfg.get("parsing", {}).get("parser", "docling")
    docling_batch_pages = cfg.get("parsing", {}).get("docling_batch_pages")
    enrich_on = enrich or cfg.get("enrichment", {}).get("enabled", False)
    min_side_pts = cfg.get("enrichment", {}).get("min_side_pts", 24.0)
    vlm = None
    if enrich_on:
        evlm_cfg = cfg.get("enrichment", {}).get("vlm") or cfg.get("llm", {"provider": "mock"})
        vlm = from_config(evlm_cfg)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    written, skipped, source_changed, errors = [], [], [], []
    for item in items:
        doc_id = item["doc_id"]
        try:
            if not force and parse_store.is_parsed_doc_present(str(out), doc_id):
                # Q11: an existing entry is never overwritten. The markdown may have been
                # corrected by hand, and a silent re-parse would throw that work away.
                skipped.append(doc_id)
                side = parse_store.read_sidecar(parse_store.markdown_path(out, doc_id))
                if side and side.provenance.source_sha256 != item["hash"]:
                    # Reported, never acted on: choosing between the human edit and the
                    # new source version is the human's call, made with --force.
                    source_changed.append(doc_id)
                continue
            ext = Path(item["path"]).suffix.lower()
            prov = ParseProvenance(
                parser="direct" if ext in TEXT_EXTS | OFFICE_EXTS else parser,
                source_name=Path(item["path"]).name, source_type=item["type"],
                source_sha256=item["hash"], source_pages=item.get("pages"),
                category=item["category"], enriched=False)
            if item["category"] == "unsupported_format":
                # Kept as an entry with an empty markdown: the split must not lose a
                # document on the way. `run` reads the category back and flags it
                # exactly as it would have on the raw folder.
                doc = ParsedDoc(doc_id=doc_id, markdown="", blocks=[],
                                parse_confidence=0.0, images=[])
                parse_store.write_parsed_doc(doc, str(out), prov)
                written.append(doc_id)
                continue
            doc = parse_document(item["path"], pages=item.get("pages"), parser=parser,
                                 docling_batch_pages=docling_batch_pages)
            if enrich_on and doc.images:
                try:
                    enriched_md = enrich_document(doc, item["path"], vlm,
                                                  str(out / "images" / doc.doc_id),
                                                  min_side_pts=min_side_pts)
                    doc = doc.model_copy(update={"markdown": enriched_md})
                    prov = prov.model_copy(update={"enriched": True})
                except Exception as exc:
                    # A failing enrichment (rate limit, timeout, unreadable image) must
                    # not cost the parsed markdown, which is valid and expensive to
                    # recompute. The entry is written un-enriched and the failure
                    # reported, rather than the document vanishing from parsed_input/.
                    errors.append({"doc_id": doc_id,
                                   "error": f"enrichissement: {type(exc).__name__}: {exc}"})
            parse_store.write_parsed_doc(doc, str(out), prov)
            written.append(doc_id)
        except Exception as exc:
            # Score-and-flag: a failing document never brings down the rest of the corpus.
            errors.append({"doc_id": doc_id, "error": f"{type(exc).__name__}: {exc}"})
    result = {"out": str(out), "n_written": len(written), "n_skipped": len(skipped),
              "n_errors": len(errors), "written": written, "skipped": skipped,
              "source_changed": source_changed, "errors": errors}
    if vlm is not None and hasattr(vlm, "flush"):
        # Manual mode: without the manifest there is no trace of the images left to
        # describe, so the enrichment could never be completed.
        result["image_manifest"] = vlm.flush()
    return result

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
    # Q1: a raw folder is parsed on the fly (unchanged behaviour), a parsed_input/ is
    # read as is. parse_document has two callers, and both had to learn the boundary.
    parsed_mode = parse_store.is_parsed_input(corpus_dir)
    rows, docs = [], []
    for item in _corpus_items(corpus_dir, parsed_mode):
        if item["category"] == "unsupported_format":
            continue
        try:
            doc = item["doc"] if parsed_mode else parse_document(
                item["path"], pages=item.get("pages"), parser=parser,
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
    # Registry fingerprint derived from the grid's content: editing the criteria
    # changes the run fingerprint, which a hardcoded version string could not do.
    chash = config_hash(cfg, registry_version=registry_fingerprint())
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
    # Q1: scoring accepts either a raw folder (parsed on the fly, unchanged behaviour)
    # or a parsed_input/, which it scores without ever touching a source file.
    parsed_mode = parse_store.is_parsed_input(corpus_dir)
    if parsed_mode and enrich_on:
        # Q24: enrichment happens in `parse`, so on an already parsed folder the option
        # has no object. Said out loud rather than silently ignored -- and the VLM client
        # is not built at all, so no API key is demanded to do nothing.
        warnings.warn(
            "--enrich est sans objet sur un parsed_input/ : l'enrichissement a lieu "
            "dans `cqg parse`. Option ignoree.", RuntimeWarning, stacklevel=2)
        enrich_on = False
    if enrich_on:
        # Enrichment VLM decoupled from the judgment LLM: built only if
        # enrichment is active, so as not to require its API key otherwise.
        evlm_cfg = cfg.get("enrichment", {}).get("vlm") or cfg.get("llm", {"provider": "mock"})
        vlm = from_config(evlm_cfg)
    scores, parsed, errors = [], [], []
    for item in _corpus_items(corpus_dir, parsed_mode):
        doc_id = item["doc_id"]
        # Flags raised by reading the parsed entry itself (hand edit, missing sidecar or
        # markdown). Empty on the raw path, so the flag lists stay identical there.
        extra_flags = item.get("flags", [])
        try:
            if item["category"] == "unsupported_format":
                # Score-and-flag: surfaced with its own flag, never dropped. Distinct
                # from "unreadable" (a document cqg tried and failed to extract) and
                # from a processing error (nothing went wrong here).
                ds = DocScore(doc_id=doc_id, global_pct=0.0, level="Inadapté", coverage_pct=0.0,
                              dimensions={}, criteria=[], worst_sections=[],
                              flags=[f"unsupported_format:{item['type']}"] + extra_flags,
                              config_hash=chash)
                write_doc_json(ds, str(out))
                scores.append(ds)
                continue
            doc = item["doc"] if parsed_mode else parse_document(
                item["path"], pages=item.get("pages"), parser=parser,
                docling_batch_pages=docling_batch_pages)
            if not doc.markdown.strip():
                # Score-and-flag: unreadable document (S14 parsing never raises) flagged
                # for human review without going through compute_metrics/score_document (no
                # LLM call on empty content) and without polluting duplicate detection.
                ds = DocScore(doc_id=doc_id, global_pct=0.0, level="Inadapté", coverage_pct=0.0,
                              dimensions={}, criteria=[], worst_sections=[],
                              flags=["unreadable"] + extra_flags, config_hash=chash)
                write_doc_json(ds, str(out))
                scores.append(ds)
                continue
            if enrich_on and doc.images:
                img_dir = str(out / "images" / doc.doc_id)
                enriched_md = enrich_document(doc, item["path"], vlm, img_dir,
                                              min_side_pts=min_side_pts)
                (out / f"{doc.doc_id}.enriched.md").write_text(enriched_md, encoding="utf-8")
                # Enrich-before-eval: quality is scored on the ENRICHED markdown (what will
                # really be ingested into RAG), not on the raw text with placeholders.
                # Anti-fabrication guard: descriptions keep the 'non verifiee' tag and their
                # presence is surfaced as a flag for human review (score-and-flag).
                doc = doc.model_copy(update={"markdown": enriched_md})
            # Counted from the scored markdown itself rather than from the enrichment
            # step, so the flag is identical whether the enrichment happened here or
            # upstream in `cqg parse`.
            n_auto_desc = count_auto_descriptions(doc.markdown)
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
            ds.flags.extend(extra_flags)
        except Exception as exc:
            # Score-and-flag: a failing document is flagged for human review, never
            # dropped silently, and never brings down the rest of the corpus.
            ds = DocScore(doc_id=doc_id, global_pct=0.0, level="Inadapté", coverage_pct=0.0,
                          dimensions={}, criteria=[], worst_sections=[],
                          flags=[f"processing_error: {type(exc).__name__}"] + extra_flags,
                          config_hash=chash)
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
    parser.add_argument("command", choices=["parse", "run", "golden"])
    parser.add_argument("corpus")
    parser.add_argument("--config", default="config/config.example.yaml")
    parser.add_argument("--out", default="./workdir/out")
    parser.add_argument("--enrich", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="re-parse un document deja present dans parsed_input/")
    args = parser.parse_args()
    if args.force and args.command != "parse":
        print(f"--force est sans objet sur `{args.command}` : il ne s'applique qu'a "
              "`parse`. Option ignoree.")
    try:
        return _dispatch(args)
    except ValueError as exc:
        # Ambiguous folder, colliding document names: the message explains what to do,
        # so it is worth more to the operator than a bare traceback.
        print(f"Erreur: {exc}")
        return 2


def _dispatch(args) -> int:
    if args.command == "parse":
        result = parse_corpus(args.corpus, args.config, args.out,
                              enrich=args.enrich, force=args.force)
        print(f"Parse termine: {result['n_written']} documents ecrits, "
              f"{result['n_skipped']} ignores. Sortie: {result['out']}")
        if result["source_changed"]:
            print("Source modifiee depuis le parsing (relancer avec --force pour "
                  f"reparser): {', '.join(result['source_changed'])}")
        if result["errors"]:
            # Reported, and non-zero exit: parsed_input/ feeds the scoring step, so a
            # partial output that looks like a success is how a document silently
            # disappears from a report.
            print(f"{result['n_errors']} erreur(s) pendant le parsing:")
            for err in result["errors"]:
                print(f"  - {err['doc_id']}: {err['error']}")
            return 1
    elif args.command == "run":
        result = run(args.corpus, args.config, args.out, enrich=args.enrich)
        print(f"Termine: {result['n_docs']} documents. Rapport: {result['corpus_report']['xlsx']}")
    elif args.command == "golden":
        result = run_golden(args.corpus, args.config, args.out)
        print(f"Golden Q/R genere: {result['xlsx']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
