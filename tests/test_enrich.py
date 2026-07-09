def test_render_image_produces_png(tmp_path):
    from cqg.enrich import render_image
    from cqg.models import ImageRef
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    src = tmp_path / "pic.png"; Image.new("RGB", (60, 40), (0, 120, 200)).save(src)
    pdf = tmp_path / "d.pdf"; c = canvas.Canvas(str(pdf))
    c.drawImage(ImageReader(str(src)), 72, 600, width=120, height=80); c.showPage(); c.save()
    ref = ImageRef(page=1, idx=1, x0=72, top=112, x1=192, bottom=192,
                   placeholder="[[IMAGE:p=1;idx=1]]")
    out = render_image(str(pdf), ref, str(tmp_path / "out"))
    assert out.endswith("p1_idx1.png")
    assert Image.open(out).size[0] > 0

def test_enrich_document_injects_tagged_descriptions(tmp_path):
    from cqg.enrich import enrich_document
    from cqg.models import ParsedDoc, ImageRef
    from cqg.llm.mock import MockLLM
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    src = tmp_path / "pic.png"; Image.new("RGB", (60, 40), (10, 10, 10)).save(src)
    pdf = tmp_path / "d.pdf"; c = canvas.Canvas(str(pdf))
    c.drawImage(ImageReader(str(src)), 72, 600, width=120, height=80); c.showPage(); c.save()
    ref = ImageRef(page=1, idx=1, x0=72, top=112, x1=192, bottom=192,
                   placeholder="[[IMAGE:p=1;idx=1]]")
    doc = ParsedDoc(doc_id="d", markdown="Avant\n\n[[IMAGE:p=1;idx=1]]\n\nApres",
                    blocks=[], parse_confidence=1.0, images=[ref])
    md = enrich_document(doc, str(pdf), MockLLM(image_desc="un graphique bleu"),
                         str(tmp_path / "img"))
    assert "[[IMAGE:p=1;idx=1]]" not in md
    assert "description automatique, non verifiee" in md and "un graphique bleu" in md

def test_enrich_skips_decorative(tmp_path):
    from cqg.enrich import enrich_document
    from cqg.models import ParsedDoc, ImageRef
    from cqg.llm.mock import MockLLM
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "d.pdf"; canvas.Canvas(str(pdf)).save()
    ref = ImageRef(page=1, idx=1, x0=10, top=10, x1=18, bottom=18,
                   placeholder="[[IMAGE:p=1;idx=1]]")
    doc = ParsedDoc(doc_id="d", markdown="[[IMAGE:p=1;idx=1]]", blocks=[],
                    parse_confidence=1.0, images=[ref])
    md = enrich_document(doc, str(pdf), MockLLM(), str(tmp_path / "img"))
    assert "decorative ignoree" in md

def test_empty_description_leaves_placeholder(tmp_path):
    # Une image NON decorative dont la description revient vide ne doit jamais
    # etre mislabel "decorative" : le placeholder reste intact pour un remplissage
    # ulterieur (apply_descriptions ou re-run).
    from cqg.enrich import enrich_document
    from cqg.models import ParsedDoc, ImageRef
    from cqg.llm.mock import MockLLM
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    src = tmp_path / "pic.png"; Image.new("RGB", (60, 40), (1, 2, 3)).save(src)
    pdf = tmp_path / "d.pdf"; c = canvas.Canvas(str(pdf))
    c.drawImage(ImageReader(str(src)), 72, 600, width=120, height=80); c.showPage(); c.save()
    ref = ImageRef(page=1, idx=1, x0=72, top=112, x1=192, bottom=192,
                   placeholder="[[IMAGE:p=1;idx=1]]")
    doc = ParsedDoc(doc_id="d", markdown="[[IMAGE:p=1;idx=1]]", blocks=[],
                    parse_confidence=1.0, images=[ref])
    md = enrich_document(doc, str(pdf), MockLLM(image_desc=""), str(tmp_path / "img"))
    assert md == "[[IMAGE:p=1;idx=1]]"
    assert "decorative ignoree" not in md

def test_apply_descriptions_empty_leaves_placeholder():
    # Un item de manifeste avec description vide (image non decrite par l'humain, mais
    # deja passee le filtre de taille donc PAS decorative) ne doit jamais devenir
    # "decorative ignoree" : le placeholder reste intact pour remplissage ulterieur.
    from cqg.enrich import apply_descriptions
    markdown = "Avant\n\n[[IMAGE:p=1;idx=1]]\n\n[[IMAGE:p=1;idx=2]]\n\nApres"
    manifest = [
        {"placeholder": "[[IMAGE:p=1;idx=1]]", "description": ""},
        {"placeholder": "[[IMAGE:p=1;idx=2]]", "description": "un schema explicatif"},
    ]
    result = apply_descriptions(markdown, manifest)
    assert "[[IMAGE:p=1;idx=1]]" in result
    assert "decorative ignoree" not in result
    assert "description automatique, non verifiee" in result and "un schema explicatif" in result
    assert "[[IMAGE:p=1;idx=2]]" not in result

def test_manual_roundtrip(tmp_path):
    # Mode manual : enrich_document laisse le placeholder intact (sentinelle "" de
    # ManualVLM.describe_image), flush() ecrit le manifeste, puis apply_descriptions
    # injecte la description remplie hors ligne sans laisser de placeholder residuel.
    import json
    from cqg.enrich import enrich_document, apply_descriptions
    from cqg.models import ParsedDoc, ImageRef
    from cqg.llm.manual import ManualVLM
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from PIL import Image
    src = tmp_path / "pic.png"; Image.new("RGB", (60, 40), (5, 5, 5)).save(src)
    pdf = tmp_path / "d.pdf"; c = canvas.Canvas(str(pdf))
    c.drawImage(ImageReader(str(src)), 72, 600, width=120, height=80); c.showPage(); c.save()
    ref = ImageRef(page=1, idx=1, x0=72, top=112, x1=192, bottom=192,
                   placeholder="[[IMAGE:p=1;idx=1]]")
    doc = ParsedDoc(doc_id="d", markdown="Avant\n\n[[IMAGE:p=1;idx=1]]\n\nApres",
                    blocks=[], parse_confidence=1.0, images=[ref])
    manifest_path = tmp_path / "manifest.json"
    vlm = ManualVLM(str(manifest_path))
    md = enrich_document(doc, str(pdf), vlm, str(tmp_path / "img"))
    assert "[[IMAGE:p=1;idx=1]]" in md
    vlm.flush()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest[0]["placeholder"] == "[[IMAGE:p=1;idx=1]]"
    manifest[0]["description"] = "un schema explicatif"
    final_md = apply_descriptions(md, manifest)
    assert "[[IMAGE" not in final_md
    assert "un schema explicatif" in final_md
