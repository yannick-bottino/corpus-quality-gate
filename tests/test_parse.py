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
    doc = parse_document(str(p), "born_digital")
    assert "Contenu complet" in doc.markdown
    assert 0.0 <= doc.parse_confidence <= 1.0


def test_parse_document_unreadable_never_raises(tmp_path):
    from cqg.parse import parse_document
    bad = tmp_path / "bad.pdf"; bad.write_bytes(b"%PDF-1.4 broken")
    doc = parse_document(str(bad), "born_digital")
    assert doc.parse_confidence == 0.0
    assert any(b.kind == "unreadable" for b in doc.blocks)


def test_parse_document_no_docling_symbols():
    import cqg.parse as parse
    assert not hasattr(parse, "_parse_docling")
    assert not hasattr(parse, "_docling_available")


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
