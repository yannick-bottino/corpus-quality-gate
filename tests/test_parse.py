import os
import pytest


def _make_pdf(path, lines, n=20):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path)); to = c.beginText(72, 800)
    for _ in range(n):
        for ln in lines:
            to.textLine(ln)
    c.drawText(to); c.showPage(); c.save()


def test_pages_text_pdfminer_nfkc(tmp_path):
    from cqg.parse import _pages_text_pdfminer, _nfkc
    assert _nfkc("ﬁn") == "fin"  # ligature fi -> fi
    p = tmp_path / "d.pdf"; _make_pdf(p, ["Bonjour le monde."])
    pages = _pages_text_pdfminer(str(p))
    assert isinstance(pages, list) and "Bonjour" in "\n".join(pages)


def test_typing_pdfplumber_detects_image(tmp_path):
    from cqg.parse import _typing_pdfplumber
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    img = tmp_path / "pic.png"; Image.new("RGB", (60, 40), (200, 0, 0)).save(img)
    p = tmp_path / "d.pdf"; c = canvas.Canvas(str(p))
    c.drawImage(ImageReader(str(img)), 72, 600, width=120, height=80)
    c.drawString(72, 500, "Texte."); c.showPage(); c.save()
    blocks, images_by_page = _typing_pdfplumber(str(p))
    assert any(b.kind == "image" for b in blocks)
    assert 0 in images_by_page and len(images_by_page[0]) >= 1


def test_assemble_inserts_placeholders_in_order():
    from cqg.parse import _assemble
    pages = ["Texte page 1", "Texte page 2"]
    imgs = {0: [{"x0": 0, "top": 10, "x1": 5, "bottom": 20},
                {"x0": 0, "top": 50, "x1": 5, "bottom": 60}]}
    md, refs = _assemble(pages, imgs)
    assert "[[IMAGE:p=1;idx=1]]" in md and "[[IMAGE:p=1;idx=2]]" in md
    assert md.index("[[IMAGE:p=1;idx=1]]") < md.index("[[IMAGE:p=1;idx=2]]")
    assert "Texte page 2" in md
    assert [r.placeholder for r in refs] == ["[[IMAGE:p=1;idx=1]]", "[[IMAGE:p=1;idx=2]]"]
    assert refs[0].page == 1 and refs[0].idx == 1


def test_confidence_signals():
    from cqg.parse import _confidence
    from cqg.models import Block
    full = "phrase complete. " * 200
    good = _confidence(full, [Block(kind="text", text=full, page=1)], pages=1, fallback_used=False)
    assert good >= 0.8
    # fallback secondaire -> plafond a 0.6
    fb = _confidence(full, [Block(kind="text", text=full, page=1)], pages=1, fallback_used=True)
    assert fb <= 0.6
    # texte tres court sur beaucoup de pages -> faible
    assert _confidence("ok", [Block(kind="text", text="ok", page=1)], pages=50, fallback_used=False) <= 0.4


def test_confidence_penalized_by_cid_failure():
    from cqg.parse import _confidence
    from cqg.models import Block
    # Texte a moitie compose de jetons (cid:NNN) non mappes : la confiance ne doit
    # PAS rester elevee (cas CG Auto qui sortait a 0.947 malgre l'echec d'extraction).
    clean = "phrase lisible et complete. " * 100
    cid = "(cid:114)(cid:97)(cid:103)(cid:101) " * 100
    mixed = clean + cid
    blocks = [Block(kind="text", text=mixed, page=1)]
    conf_clean = _confidence(clean, blocks, pages=1, fallback_used=False)
    conf_mixed = _confidence(mixed, blocks, pages=1, fallback_used=False)
    assert conf_clean >= 0.8
    assert conf_mixed < 0.7
    assert conf_mixed < conf_clean


def test_better_extraction_prefers_lower_cid():
    from cqg.parse import _better_extraction
    from cqg.models import Block
    cid_md = "(cid:1)(cid:2)(cid:3) " * 50
    clean_md = "texte parfaitement lisible et complet. " * 20
    primary = (cid_md, [Block(kind="text", text=cid_md, page=1)], [])
    fallback = (clean_md, [Block(kind="text", text=clean_md, page=1)], [])
    chosen, used = _better_extraction(primary, fallback)
    assert chosen[0] == clean_md
    assert used is True


def test_better_extraction_keeps_primary_when_clean():
    from cqg.parse import _better_extraction
    from cqg.models import Block
    clean_md = "texte lisible. " * 20
    worse_md = "(cid:9) " * 40
    primary = (clean_md, [Block(kind="text", text=clean_md, page=1)], [])
    fallback = (worse_md, [Block(kind="text", text=worse_md, page=1)], [])
    chosen, used = _better_extraction(primary, fallback)
    assert chosen[0] == clean_md
    assert used is False


def test_parse_document_full_chain(tmp_path):
    from cqg.parse import parse_document
    p = tmp_path / "d.pdf"; _make_pdf(p, ["Contenu complet de la page."])
    doc = parse_document(str(p), "born_digital", parser="legacy")
    assert "Contenu complet" in doc.markdown
    assert 0.0 <= doc.parse_confidence <= 1.0


def test_parse_document_unreadable_never_raises(tmp_path):
    from cqg.parse import parse_document
    bad = tmp_path / "bad.pdf"; bad.write_bytes(b"%PDF-1.4 broken")
    doc = parse_document(str(bad), "born_digital", parser="legacy")
    assert doc.parse_confidence == 0.0
    assert any(b.kind == "unreadable" for b in doc.blocks)


def test_legacy_parser_does_not_use_docling(tmp_path, monkeypatch):
    # Invariant : parser="legacy" n'appelle jamais Docling et parse via pdfminer/pdfplumber.
    # (Docling est desormais le parser PAR DEFAUT ; le mode legacy reste le repli leger.)
    import cqg.parse as parse

    def _boom(*a, **k):
        raise AssertionError("Docling ne doit pas etre utilise par le parser legacy")

    monkeypatch.setattr(parse, "_docling_extraction", _boom)
    p = tmp_path / "d.pdf"; _make_pdf(p, ["Contenu complet de la page."])
    doc = parse.parse_document(str(p), "born_digital", parser="legacy")
    assert "Contenu complet" in doc.markdown


def test_parser_docling_dispatches_to_docling_extraction(tmp_path, monkeypatch):
    # parser="docling" -> l'extraction Docling est bien appelee et son resultat utilise.
    import cqg.parse as parse
    from cqg.models import Block
    called = {}

    def _fake(path, pages=None, batch_pages=None):
        called["yes"] = True
        return ("MD docling structure", [Block(kind="text", text="MD docling structure", page=1)], [])

    monkeypatch.setattr(parse, "_docling_extraction", _fake)
    p = tmp_path / "d.pdf"; _make_pdf(p, ["x"])
    doc = parse.parse_document(str(p), "born_digital", parser="docling")
    assert called.get("yes") is True
    assert doc.markdown == "MD docling structure"


def test_parser_docling_falls_back_to_default_on_failure(tmp_path, monkeypatch):
    # Robustesse (score-and-flag) : si Docling echoue (import/OOM/erreur), on retombe sur
    # la chaine par defaut plutot que d'abandonner le document.
    import cqg.parse as parse

    def _boom(path, pages=None, batch_pages=None):
        raise RuntimeError("docling indisponible")

    monkeypatch.setattr(parse, "_docling_extraction", _boom)
    p = tmp_path / "d.pdf"; _make_pdf(p, ["Contenu de repli."])
    doc = parse.parse_document(str(p), "born_digital", parser="docling")
    assert "Contenu de repli" in doc.markdown  # chaine par defaut a pris le relais


def _make_pdf_pages(path, page_lines):
    # PDF multi-pages : une entree de page_lines = les lignes d'une page (showPage par page).
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    for lines in page_lines:
        to = c.beginText(72, 800)
        for ln in lines:
            to.textLine(ln)
        c.drawText(to); c.showPage()
    c.save()


def test_docling_extraction_batches_one_subprocess_per_page(tmp_path, monkeypatch):
    # Batching : batch_pages=1 -> un sous-processus FRAIS par page. subprocess.run est
    # mocke (aucun vrai docling) et ecrit un markdown fixe dans le fichier de sortie.
    import cqg.parse as parse
    from pathlib import Path
    calls = {"n": 0}

    class _Proc:
        returncode = 0

    def _fake_run(args, **kwargs):
        calls["n"] += 1
        out = next(a for a in args if str(a).endswith(".md"))
        Path(out).write_text("TEXTE_LOT", encoding="utf-8")
        return _Proc()

    monkeypatch.setattr(parse.subprocess, "run", _fake_run)
    p = tmp_path / "d.pdf"
    _make_pdf_pages(p, [["Page une."], ["Page deux."], ["Page trois."]])
    md, blocks, refs = parse._docling_extraction(str(p), batch_pages=1)
    assert calls["n"] == 3
    assert md.count("TEXTE_LOT") == 3


def test_docling_extraction_per_page_pdfminer_fallback_on_oom(tmp_path, monkeypatch):
    # Repli par lot : returncode 137 (OOM) -> chaque page bascule sur pdfminer sans faire
    # tomber le document. Le PDF a du vrai texte, donc pdfminer produit du contenu.
    import cqg.parse as parse

    class _Proc:
        returncode = 137

    def _fake_run(args, **kwargs):
        return _Proc()

    monkeypatch.setattr(parse.subprocess, "run", _fake_run)
    p = tmp_path / "d.pdf"; _make_pdf(p, ["Contenu reel de la page."])
    md, blocks, refs = parse._docling_extraction(str(p), batch_pages=1)
    assert md.strip()
    assert "Contenu reel" in md


def test_typing_pdfplumber_detects_table(tmp_path):
    from cqg.parse import _typing_pdfplumber
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    p = tmp_path / "d.pdf"
    c = canvas.Canvas(str(p))
    data = [["A", "B", "C"], ["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]]
    table = Table(data, colWidths=80, rowHeights=24)
    # GRID (toutes les bordures internes et externes) + BOX (contour epais) sont
    # necessaires : pdfplumber.find_tables() detecte des lignes vectorielles, pas
    # une simple mise en page de texte. Sans bordures dessinees, aucune table
    # n'est identifiee.
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1.5, colors.black),
        ("BOX", (0, 0), (-1, -1), 2, colors.black),
    ]))
    w, h = table.wrapOn(c, 400, 400)
    table.drawOn(c, 72, 700 - h)
    c.showPage(); c.save()
    blocks, _ = _typing_pdfplumber(str(p))
    assert any(b.kind == "table" for b in blocks)


@pytest.mark.skipif(os.getenv("CQG_TEST_DOCLING") != "1",
                    reason="test docling reel opt-in (CQG_TEST_DOCLING=1), lourd (torch)")
def test_docling_real_extraction(tmp_path):
    # Opt-in : verifie que le vrai worker Docling extrait bien un markdown structure
    # (table rendue en pipes). Ignore par defaut pour garder la suite rapide.
    from cqg.parse import parse_document
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    p = tmp_path / "d.pdf"
    c = canvas.Canvas(str(p))
    data = [["A", "B", "C"], ["1", "2", "3"], ["4", "5", "6"]]
    table = Table(data, colWidths=80, rowHeights=24)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1.5, colors.black),
        ("BOX", (0, 0), (-1, -1), 2, colors.black),
    ]))
    _, h = table.wrapOn(c, 400, 400)
    table.drawOn(c, 72, 700 - h)
    c.showPage(); c.save()
    doc = parse_document(str(p), "born_digital", parser="docling")
    assert doc.markdown.strip()
    assert "|" in doc.markdown
