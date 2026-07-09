import os, json
from cqg.cli import run

def test_end_to_end(tmp_path):
    from reportlab.pdfgen import canvas
    corpus = tmp_path / "corpus"; corpus.mkdir()
    for name in ("a.pdf", "b.pdf"):
        c = canvas.Canvas(str(corpus / name))
        to = c.beginText(72, 800)
        for _ in range(30):
            to.textLine("Version v1.0 du 2026-01-01.")
        c.drawText(to); c.showPage(); c.save()
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("llm:\n  provider: mock\n  temperature: 0\npaths:\n  workdir: ./wd\n"
                   "thresholds:\n  coverage_flag_below: 0.7\n", encoding="utf-8")
    out = tmp_path / "out"
    paths = run(str(corpus), str(cfg), str(out))
    assert os.path.exists(paths["corpus_report"]["xlsx"])
    assert os.path.exists(out / "a.score.json")
    data = json.loads((out / "a.score.json").read_text(encoding="utf-8"))
    assert data["config_hash"] and "level" in data


def test_run_isolates_and_flags_bad_document(tmp_path):
    from reportlab.pdfgen import canvas
    corpus = tmp_path / "corpus"; corpus.mkdir()
    c = canvas.Canvas(str(corpus / "good.pdf")); to = c.beginText(72, 800)
    for _ in range(30):
        to.textLine("Version v1.0 du 2026-01-01.")
    c.drawText(to); c.showPage(); c.save()
    (corpus / "corrupt.pdf").write_bytes(b"%PDF-1.4 fichier corrompu \x00\x01\x02 pas un vrai pdf")
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("llm:\n  provider: mock\nthresholds:\n  coverage_flag_below: 0.7\n", encoding="utf-8")
    out = tmp_path / "out"
    result = run(str(corpus), str(cfg), str(out))
    assert result["n_docs"] == 2
    # parse_document est resilient (jamais de crash) : le PDF corrompu n'est plus un
    # processing_error, il est court-circuité avec flag unreadable.
    bad = json.loads((out / "corrupt.score.json").read_text(encoding="utf-8"))
    assert "unreadable" in bad["flags"]
    # document valide doit être présent et scorer normalement
    good = json.loads((out / "good.score.json").read_text(encoding="utf-8"))
    assert "level" in good


def test_cli_enrich_writes_enriched_md(tmp_path, monkeypatch):
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    corpus = tmp_path / "corpus"; corpus.mkdir()
    src = tmp_path / "pic.png"; Image.new("RGB", (80, 60), (0, 0, 200)).save(src)
    pdf = corpus / "doc.pdf"; c = canvas.Canvas(str(pdf))
    c.drawString(72, 700, "Texte du document.")
    c.drawImage(ImageReader(str(src)), 72, 500, width=120, height=90); c.showPage(); c.save()
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("llm:\n  provider: mock\nparsing: {}\nenrichment:\n  enabled: true\n",
                   encoding="utf-8")
    from cqg.cli import run
    out = tmp_path / "out"
    run(str(corpus), str(cfg), str(out), enrich=True)
    enriched = out / "doc.enriched.md"
    assert enriched.exists()
    assert "description automatique" in enriched.read_text(encoding="utf-8")


def test_cli_enrich_manual_writes_manifest(tmp_path):
    # Mode manual : run() doit flush() le manifeste des images a decrire, sinon aucune
    # trace n'existe pour completer l'enrichissement in-session. Le placeholder reste
    # intact dans le .enriched.md tant que la description n'est pas remplie.
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    corpus = tmp_path / "corpus"; corpus.mkdir()
    src = tmp_path / "pic.png"; Image.new("RGB", (80, 60), (200, 0, 0)).save(src)
    pdf = corpus / "doc.pdf"; c = canvas.Canvas(str(pdf))
    c.drawString(72, 700, "Texte du document.")
    c.drawImage(ImageReader(str(src)), 72, 500, width=120, height=90); c.showPage(); c.save()
    manifest_path = tmp_path / "manifest.json"
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "llm:\n  provider: mock\nparsing: {}\nenrichment:\n  enabled: true\n"
        f"  vlm:\n    provider: manual\n    manifest_path: {manifest_path.as_posix()}\n",
        encoding="utf-8")
    from cqg.cli import run
    out = tmp_path / "out"
    result = run(str(corpus), str(cfg), str(out))
    from pathlib import Path as _P
    assert _P(result["image_manifest"]) == manifest_path
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest) >= 1
    assert set(("image_path", "placeholder", "description")) <= set(manifest[0].keys())
    enriched = out / "doc.enriched.md"
    assert enriched.exists()
    assert "[[IMAGE" in enriched.read_text(encoding="utf-8")


def test_cli_enrich_feeds_eval_and_flags_auto_descriptions(tmp_path):
    # Enrich-avant-eval : le markdown ENRICHI (descriptions injectees) est ce qui est note,
    # et la presence de descriptions auto-generees est remontee en flag garde-fou pour la
    # revue humaine (anti-fabrication : le score s'appuie en partie sur du non-verifie).
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    corpus = tmp_path / "corpus"; corpus.mkdir()
    src = tmp_path / "pic.png"; Image.new("RGB", (80, 60), (0, 0, 200)).save(src)
    pdf = corpus / "doc.pdf"; c = canvas.Canvas(str(pdf))
    c.drawString(72, 700, "Texte du document.")
    c.drawImage(ImageReader(str(src)), 72, 500, width=120, height=90); c.showPage(); c.save()
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("llm:\n  provider: mock\nparsing: {}\nenrichment:\n  enabled: true\n"
                   "  vlm:\n    provider: mock\n", encoding="utf-8")
    from cqg.cli import run
    out = tmp_path / "out"
    run(str(corpus), str(cfg), str(out), enrich=True)
    data = json.loads((out / "doc.score.json").read_text(encoding="utf-8"))
    assert any(f.startswith("auto_descriptions:") for f in data["flags"])


def test_cli_enrich_config_only_with_separate_vlm(tmp_path):
    # Chemin config-only : enrichment.enabled: true pilote l'enrichissement sans passer
    # enrich=True, avec un client vlm distinct du llm de jugement (enrichment.vlm).
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    corpus = tmp_path / "corpus"; corpus.mkdir()
    src = tmp_path / "pic.png"; Image.new("RGB", (80, 60), (0, 200, 0)).save(src)
    pdf = corpus / "doc.pdf"; c = canvas.Canvas(str(pdf))
    c.drawString(72, 700, "Texte du document.")
    c.drawImage(ImageReader(str(src)), 72, 500, width=120, height=90); c.showPage(); c.save()
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "llm:\n  provider: mock\nparsing: {}\nenrichment:\n  enabled: true\n"
        "  vlm:\n    provider: mock\n",
        encoding="utf-8")
    from cqg.cli import run
    out = tmp_path / "out"
    run(str(corpus), str(cfg), str(out))
    enriched = out / "doc.enriched.md"
    assert enriched.exists()
    assert "description automatique" in enriched.read_text(encoding="utf-8")
