"""Test du branchement CLI des golden Q/R (sous-commande `cqg golden`)."""
import os


def _make_pdf(path, lines, n=6):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path)); to = c.beginText(72, 800)
    for _ in range(n):
        for ln in lines:
            to.textLine(ln)
    c.drawText(to); c.showPage(); c.save()


def test_golden_subcommand_writes_qr_files(tmp_path):
    corpus = tmp_path / "corpus"; corpus.mkdir()
    _make_pdf(corpus / "doc1.pdf", ["Le produit X couvre le risque incendie."])
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        "llm:\n  provider: mock\n  model: mock-model\n"
        "parsing:\n  parser: legacy\n"
        "golden:\n  profile: gestionnaire sinistres\n  policy: repondre brievement\n",
        encoding="utf-8")
    out = tmp_path / "out"

    from cqg.cli import run_golden
    res = run_golden(str(corpus), str(cfg), str(out))

    # Le pipeline golden produit un classeur Excel + un CSV partageables au metier.
    assert os.path.exists(res["xlsx"])
    assert os.path.exists(res["csv"])
    # En-tete attendu (colonnes de validation metier).
    with open(res["csv"], encoding="utf-8-sig") as f:
        header = f.readline()
    for col in ("question", "reponse", "couvert", "statut_validation"):
        assert col in header
