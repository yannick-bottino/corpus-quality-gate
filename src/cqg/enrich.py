from pathlib import Path
from .models import ParsedDoc, ImageRef
from .llm.base import LLMClient

def render_image(pdf_path: str, ref: ImageRef, out_dir: str, scale: float = 2.0) -> str:
    import pypdfium2 as pdfium
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        page = pdf[ref.page - 1]
        pil = page.render(scale=scale).to_pil()
        page.close()
    finally:
        pdf.close()
    # pdfplumber bbox in points (top-left origin) -> pixels at the scale factor.
    box = (int(ref.x0 * scale), int(ref.top * scale),
           int(ref.x1 * scale), int(ref.bottom * scale))
    crop = pil.crop(box)
    out = str(Path(out_dir) / f"p{ref.page}_idx{ref.idx}.png")
    crop.save(out)
    return out

_TAG = "[Image (description automatique, non verifiee): {desc}]"
_DECO = "[Image decorative ignoree]"

def enrich_document(doc: ParsedDoc, pdf_path: str, llm: LLMClient, out_dir: str,
                    min_side_pts: float = 24.0) -> str:
    md = doc.markdown
    for ref in doc.images:
        if (ref.x1 - ref.x0) < min_side_pts or (ref.bottom - ref.top) < min_side_pts:
            md = md.replace(ref.placeholder, _DECO)
            continue
        try:
            png = render_image(pdf_path, ref, out_dir)
            desc = llm.describe_image(png, context=f"page {ref.page}|{ref.placeholder}").strip()
        except Exception as exc:
            md = md.replace(ref.placeholder,
                            f"[Image non decrite: {type(exc).__name__}]")
            continue
        if desc:
            md = md.replace(ref.placeholder, _TAG.format(desc=desc))
        # empty desc (manual-mode sentinel, or provider with no response): the placeholder
        # is left intact for apply_descriptions / later in-session filling.
        # An empty description never means "decorative" (decided solely by size).
    return md

def apply_descriptions(markdown: str, manifest: list[dict]) -> str:
    # Manual mode: the manifest carries {placeholder, description} filled in-session.
    for item in manifest:
        ph = item.get("placeholder")
        desc = (item.get("description") or "").strip()
        if ph and desc:
            markdown = markdown.replace(ph, _TAG.format(desc=desc))
        # empty desc: the placeholder is left intact (not yet filled). An
        # empty description never means "decorative" (decided solely by size).
    return markdown
