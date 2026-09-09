from cqg.triage import triage_file

def test_born_digital_pdf(tmp_path):
    from reportlab.pdfgen import canvas
    p = tmp_path / "doc.pdf"
    c = canvas.Canvas(str(p))
    to = c.beginText(72, 800)
    for _ in range(40):
        to.textLine("Lorem ipsum dolor sit amet")
    c.drawText(to); c.showPage(); c.save()
    r = triage_file(str(p))
    assert r["category"] == "born_digital"
    assert r["pages"] == 1
    assert len(r["hash"]) == 64


def test_text_formats_are_classified_parseable(tmp_path):
    # .txt/.md carry extractable text: they are a parseable category, not
    # lumped with formats cqg cannot open.
    from cqg.triage import triage_file
    for name in ("note.md", "note.txt"):
        p = tmp_path / name
        p.write_text("Du contenu.", encoding="utf-8")
        assert triage_file(str(p))["category"] == "text"


def test_office_formats_are_classified_unsupported(tmp_path):
    # Score-and-flag: a format cqg cannot parse must be distinguishable from a
    # PDF that failed to extract, so it gets its own category (and its own flag).
    from cqg.triage import triage_file
    for name in ("doc.docx", "deck.pptx"):
        p = tmp_path / name
        p.write_bytes(b"PK\x03\x04 pas ouvert par cqg")
        assert triage_file(str(p))["category"] == "unsupported_format"
