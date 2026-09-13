import json

import pytest

from cqg import parse_store
from cqg.cli import main, parse_corpus, run, run_golden


def _text_pdf(path, line="Version v1.0 du 2026-01-01.", n=30):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    to = c.beginText(72, 800)
    for _ in range(n):
        to.textLine(line)
    c.drawText(to)
    c.showPage()
    c.save()


def _image_pdf(path, tmp_path):
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from PIL import Image
    src = tmp_path / "pic.png"
    Image.new("RGB", (80, 60), (0, 0, 200)).save(src)
    c = canvas.Canvas(str(path))
    c.drawString(72, 700, "Texte du document.")
    c.drawImage(ImageReader(str(src)), 72, 500, width=120, height=90)
    c.showPage()
    c.save()


def _cfg(tmp_path, extra=""):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("llm:\n  provider: mock\nparsing:\n  parser: legacy\n" + extra,
                   encoding="utf-8")
    return str(cfg)


def test_parse_writes_markdown_and_sidecar_per_document(tmp_path):
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "a.pdf")
    out = tmp_path / "parsed"
    result = parse_corpus(str(corpus), _cfg(tmp_path), str(out))
    assert result["n_written"] == 1
    assert (out / "a.md").exists() and (out / "a.parse.json").exists()
    side = json.loads((out / "a.parse.json").read_text(encoding="utf-8"))
    assert side["blocks"], "the sidecar carries the blocks na_decisions counts"
    assert side["provenance"]["source_name"] == "a.pdf"
    assert side["provenance"]["parser"] == "legacy"
    assert side["provenance"]["source_sha256"]
    assert side["markdown_hash"] == parse_store.markdown_hash(
        (out / "a.md").read_bytes().decode("utf-8"))


def test_parse_refuses_a_folder_already_parsed(tmp_path):
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "a.pdf")
    out = tmp_path / "parsed"
    parse_corpus(str(corpus), _cfg(tmp_path), str(out))
    with pytest.raises(ValueError):
        parse_corpus(str(out), _cfg(tmp_path), str(tmp_path / "again"))


def test_parse_skips_an_already_parsed_document_and_force_reparses(tmp_path):
    # A hand edit of the markdown is a first-class case: re-running parse must not
    # silently overwrite it. --force is the explicit way to ask for that.
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "a.pdf")
    out = tmp_path / "parsed"
    cfg = _cfg(tmp_path)
    parse_corpus(str(corpus), cfg, str(out))
    (out / "a.md").write_bytes("Texte corrige a la main.".encode("utf-8"))

    again = parse_corpus(str(corpus), cfg, str(out))
    assert again["n_skipped"] == 1 and again["n_written"] == 0
    assert (out / "a.md").read_bytes().decode("utf-8") == "Texte corrige a la main."

    forced = parse_corpus(str(corpus), cfg, str(out), force=True)
    assert forced["n_written"] == 1
    assert "Version v1.0" in (out / "a.md").read_bytes().decode("utf-8")


def test_parse_reports_a_source_changed_since_the_last_parse(tmp_path):
    # Never re-parses on its own (that would discard a human edit); says so instead.
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "a.pdf")
    out = tmp_path / "parsed"
    cfg = _cfg(tmp_path)
    parse_corpus(str(corpus), cfg, str(out))
    _text_pdf(corpus / "a.pdf", line="Version v2.0 du 2026-06-01.", n=40)
    again = parse_corpus(str(corpus), cfg, str(out))
    assert again["source_changed"] == ["a"]
    assert "Version v1.0" in (out / "a.md").read_bytes().decode("utf-8")


def test_parse_enriches_the_markdown_it_writes(tmp_path):
    # parsed_input/ must hold the document AS IT WILL BE INGESTED into RAG, so the
    # image -> text enrichment belongs to parse, not to scoring.
    corpus = tmp_path / "raw"; corpus.mkdir()
    _image_pdf(corpus / "doc.pdf", tmp_path)
    out = tmp_path / "parsed"
    cfg = _cfg(tmp_path, "enrichment:\n  enabled: true\n  vlm:\n    provider: mock\n")
    parse_corpus(str(corpus), cfg, str(out), enrich=True)
    md = (out / "doc.md").read_bytes().decode("utf-8")
    assert "description automatique" in md
    side = json.loads((out / "doc.parse.json").read_text(encoding="utf-8"))
    assert side["provenance"]["enriched"] is True
    # The sidecar stays the parse-time truth: the image blocks and their geometry
    # describe the SOURCE, which enrichment does not change.
    assert side["images"], "image geometry survives enrichment"


def test_parse_keeps_an_unsupported_format_as_an_entry(tmp_path, monkeypatch):
    # Splitting parse from run must not lose a document on the way: an unsupported
    # format is flagged by run today, so it has to survive the boundary.
    import cqg.cli as cli
    corpus = tmp_path / "raw"; corpus.mkdir()
    (corpus / "classeur.xlsx").write_bytes(b"PK\x03\x04 pas ouvert par cqg")
    monkeypatch.setattr(cli, "triage_corpus", lambda folder: [
        {"doc_id": "classeur", "type": "xlsx", "hash": "0" * 64,
         "path": str(corpus / "classeur.xlsx"), "pages": None,
         "category": "unsupported_format"}])
    out = tmp_path / "parsed"
    parse_corpus(str(corpus), _cfg(tmp_path), str(out))
    side = json.loads((out / "classeur.parse.json").read_text(encoding="utf-8"))
    assert side["provenance"]["category"] == "unsupported_format"
    assert side["provenance"]["source_type"] == "xlsx"

    scores = tmp_path / "out"
    run(str(out), _cfg(tmp_path), str(scores))
    ds = json.loads((scores / "classeur.score.json").read_text(encoding="utf-8"))
    assert "unsupported_format:xlsx" in ds["flags"]


def test_parse_keeps_an_unreadable_document_as_an_empty_entry(tmp_path):
    corpus = tmp_path / "raw"; corpus.mkdir()
    (corpus / "corrupt.pdf").write_bytes(b"%PDF-1.4 fichier corrompu \x00\x01 pas un vrai pdf")
    out = tmp_path / "parsed"
    parse_corpus(str(corpus), _cfg(tmp_path), str(out))
    assert (out / "corrupt.md").read_bytes() == b""
    scores = tmp_path / "out"
    run(str(out), _cfg(tmp_path), str(scores))
    ds = json.loads((scores / "corrupt.score.json").read_text(encoding="utf-8"))
    assert "unreadable" in ds["flags"]


def test_run_scores_a_parsed_input_without_touching_the_source(tmp_path):
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "a.pdf")
    parsed = tmp_path / "parsed"
    cfg = _cfg(tmp_path)
    parse_corpus(str(corpus), cfg, str(parsed))
    scores = tmp_path / "out"
    result = run(str(parsed), cfg, str(scores))
    assert result["n_docs"] == 1 and result["n_errors"] == 0
    ds = json.loads((scores / "a.score.json").read_text(encoding="utf-8"))
    assert ds["criteria"]
    assert "unreadable" not in ds["flags"]


def test_run_flags_a_hand_edited_document(tmp_path):
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "a.pdf")
    parsed = tmp_path / "parsed"
    cfg = _cfg(tmp_path)
    parse_corpus(str(corpus), cfg, str(parsed))
    (parsed / "a.md").write_bytes(
        ("Version v2.0 du 2026-06-01.\n\n" + "Le contrat couvre l'incendie. " * 40)
        .encode("utf-8"))
    scores = tmp_path / "out"
    run(str(parsed), cfg, str(scores))
    ds = json.loads((scores / "a.score.json").read_text(encoding="utf-8"))
    assert "manually_edited" in ds["flags"]


def test_run_warns_when_enrich_is_asked_on_a_parsed_input(tmp_path):
    # Q24: --enrich stays meaningful on a raw folder (run parses, so it can enrich)
    # and is without object on an already parsed folder. Say so, never pretend.
    corpus = tmp_path / "raw"; corpus.mkdir()
    _image_pdf(corpus / "doc.pdf", tmp_path)
    parsed = tmp_path / "parsed"
    cfg = _cfg(tmp_path)
    parse_corpus(str(corpus), cfg, str(parsed))
    scores = tmp_path / "out"
    with pytest.warns(RuntimeWarning, match="enrich"):
        run(str(parsed), cfg, str(scores), enrich=True)
    assert not (scores / "doc.enriched.md").exists()


def test_golden_accepts_a_parsed_input(tmp_path):
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "a.pdf")
    parsed = tmp_path / "parsed"
    cfg = _cfg(tmp_path)
    parse_corpus(str(corpus), cfg, str(parsed))
    out = tmp_path / "golden"
    result = run_golden(str(parsed), cfg, str(out))
    assert result["xlsx"]


def test_main_exposes_the_parse_subcommand(tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "a.pdf")
    out = tmp_path / "parsed"
    monkeypatch.setattr("sys.argv", ["cqg", "parse", str(corpus),
                                     "--config", _cfg(tmp_path), "--out", str(out)])
    assert main() == 0
    assert (out / "a.md").exists()
    assert "1 documents ecrits" in capsys.readouterr().out


def test_parse_refuses_two_sources_sharing_a_name(tmp_path):
    # rapport.docx next to its PDF export: both claim rapport.md. One would be skipped
    # as "already parsed" and lost from the report, and --force would overwrite rather
    # than recover it. No honest winner exists, so nothing is written at all.
    from docx import Document
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "rapport.pdf")
    d = Document(); d.add_paragraph("Le contrat couvre l'incendie.")
    d.save(str(corpus / "rapport.docx"))
    out = tmp_path / "parsed"
    with pytest.raises(ValueError, match="rapport"):
        parse_corpus(str(corpus), _cfg(tmp_path), str(out))
    assert not (out / "rapport.md").exists()


def test_parse_refuses_to_write_into_the_source_folder(tmp_path):
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "a.pdf")
    with pytest.raises(ValueError):
        parse_corpus(str(corpus), _cfg(tmp_path), str(corpus))


def test_a_failing_enrichment_never_costs_the_parsed_document(tmp_path, monkeypatch):
    # Score-and-flag at the parsing boundary: a rate limit on the VLM must not make a
    # perfectly parsed document disappear from parsed_input/ -- and therefore from the
    # report -- while the command reports success.
    import cqg.cli as cli
    corpus = tmp_path / "raw"; corpus.mkdir()
    _image_pdf(corpus / "doc.pdf", tmp_path)
    def _boom(*a, **kw):
        raise RuntimeError("VLM 429 rate limit")
    monkeypatch.setattr(cli, "enrich_document", _boom)
    out = tmp_path / "parsed"
    result = parse_corpus(str(corpus), _cfg(tmp_path), str(out), enrich=True)
    assert result["n_written"] == 1 and result["n_errors"] == 1
    assert (out / "doc.md").exists() and (out / "doc.parse.json").exists()
    assert "Texte du document" in (out / "doc.md").read_bytes().decode("utf-8")
    scores = tmp_path / "out"
    run(str(out), _cfg(tmp_path), str(scores))
    assert (scores / "doc.score.json").exists()


def test_parse_reports_errors_and_exits_non_zero(tmp_path, monkeypatch, capsys):
    import cqg.cli as cli
    corpus = tmp_path / "raw"; corpus.mkdir()
    _image_pdf(corpus / "doc.pdf", tmp_path)
    def _boom(*a, **kw):
        raise RuntimeError("VLM 429 rate limit")
    monkeypatch.setattr(cli, "enrich_document", _boom)
    out = tmp_path / "parsed"
    monkeypatch.setattr("sys.argv", ["cqg", "parse", str(corpus), "--enrich",
                                     "--config", _cfg(tmp_path), "--out", str(out)])
    assert main() == 1
    assert "429" in capsys.readouterr().out


def test_a_renamed_parsed_pair_reports_under_its_file_name(tmp_path):
    # Duplicating a parsed pair to edit a variant is a natural human move. If the
    # sidecar doc_id won, both variants would write the same score file and one would
    # silently overwrite the other.
    corpus = tmp_path / "raw"; corpus.mkdir()
    _text_pdf(corpus / "note.pdf")
    parsed = tmp_path / "parsed"
    cfg = _cfg(tmp_path)
    parse_corpus(str(corpus), cfg, str(parsed))
    for suffix in (".md", ".parse.json"):
        (parsed / f"variante{suffix}").write_bytes((parsed / f"note{suffix}").read_bytes())
    scores = tmp_path / "out"
    result = run(str(parsed), cfg, str(scores))
    assert result["n_docs"] == 2
    assert (scores / "note.score.json").exists() and (scores / "variante.score.json").exists()
    ds = json.loads((scores / "variante.score.json").read_text(encoding="utf-8"))
    assert "renamed:note" in ds["flags"]
