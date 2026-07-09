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
