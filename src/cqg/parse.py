import unicodedata
from pathlib import Path
from .models import ParsedDoc, Block, ImageRef
from .signals import cid_failure_fraction


def _nfkc(s: str) -> str:
    # Normalisation compatibilite : ecrase les ligatures (U+FB01 fi, U+FB02 fl) et
    # autres formes de compatibilite. Sans effet sur les lettres accentuees francaises.
    return unicodedata.normalize("NFKC", s or "")


def _pages_text_pdfminer(path: str) -> list[str]:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer
    pages: list[str] = []
    for layout in extract_pages(path):
        parts = [el.get_text() for el in layout if isinstance(el, LTTextContainer)]
        pages.append(_nfkc("".join(parts)).strip())
    return pages


def _typing_pdfplumber(path: str) -> tuple[list[Block], dict[int, list[dict]]]:
    import pdfplumber
    blocks: list[Block] = []
    images_by_page: dict[int, list[dict]] = {}
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.find_tables() or []
            for _ in tables:
                blocks.append(Block(kind="table", text="", page=i + 1))
            imgs = page.images or []
            page_imgs = []
            for im in imgs:
                blocks.append(Block(kind="image", text="", page=i + 1))
                page_imgs.append({"x0": float(im["x0"]), "top": float(im["top"]),
                                  "x1": float(im["x1"]), "bottom": float(im["bottom"])})
            if page_imgs:
                images_by_page[i] = sorted(page_imgs, key=lambda d: d["top"])
    return blocks, images_by_page


def _assemble(pages_text: list[str],
              images_by_page: dict[int, list[dict]]) -> tuple[str, list[ImageRef]]:
    out_parts: list[str] = []
    refs: list[ImageRef] = []
    for i, text in enumerate(pages_text):
        if text:
            out_parts.append(text)
        for k, im in enumerate(images_by_page.get(i, []), start=1):
            ph = f"[[IMAGE:p={i + 1};idx={k}]]"
            out_parts.append(ph)
            refs.append(ImageRef(page=i + 1, idx=k, x0=im["x0"], top=im["top"],
                                 x1=im["x1"], bottom=im["bottom"], placeholder=ph))
    return "\n\n".join(p for p in out_parts if p), refs


def _confidence(markdown: str, blocks: list[Block], pages: int | None,
                fallback_used: bool) -> float:
    if not markdown.strip():
        return 0.0
    length_ok = min(1.0, len(markdown) / 500.0)
    non_empty = sum(1 for b in blocks if b.text.strip())
    ratio = (non_empty / len(blocks)) if blocks else 1.0
    conf = 0.5 * length_ok + 0.5 * ratio
    # Detection de perte de contenu : une extraction anormalement faible par page
    # (ex. parser qui echoue silencieusement sur des pages) plafonne la confiance.
    if pages and pages > 0 and (len(markdown) / pages) < 200:
        conf = min(conf, 0.4)
    if fallback_used:
        conf = min(conf, 0.6)
    # Echec de mapping police : le texte est present en volume (length_ok haut) mais
    # illisible (jetons (cid:NNN), glyphes non mappes). La confiance longueur/blocs ne
    # le voit pas (cas CG Auto a 0.947). Penalite proportionnelle a la part perdue.
    cid_frac = cid_failure_fraction(markdown)
    conf = conf * (1.0 - cid_frac)
    return round(conf, 3)


def _pdfplumber_only(path: str) -> tuple[str, list[Block], list[ImageRef]]:
    # Fallback 1 : pdfplumber pour le texte ET le typage (0 artefact natif).
    import pdfplumber
    pages_text, blocks, images_by_page = [], [], {}
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            pages_text.append(_nfkc(page.extract_text() or "").strip())
            for _ in (page.find_tables() or []):
                blocks.append(Block(kind="table", text="", page=i + 1))
            page_imgs = []
            for im in (page.images or []):
                blocks.append(Block(kind="image", text="", page=i + 1))
                page_imgs.append({"x0": float(im["x0"]), "top": float(im["top"]),
                                  "x1": float(im["x1"]), "bottom": float(im["bottom"])})
            if page_imgs:
                images_by_page[i] = sorted(page_imgs, key=lambda d: d["top"])
    md, refs = _assemble(pages_text, images_by_page)
    for i, t in enumerate(pages_text):
        if t:
            blocks.append(Block(kind="text", text=t, page=i + 1))
    return md, blocks, refs


def _better_extraction(primary, fallback):
    """Choisit l'extraction la moins degradee (plus faible fraction cid).

    primary/fallback : tuples (markdown, blocks, refs). Retourne (choisi, fallback_used).
    Ne bascule sur le fallback que s'il reduit strictement la fraction cid.
    """
    if cid_failure_fraction(fallback[0]) < cid_failure_fraction(primary[0]):
        return fallback, True
    return primary, False


# Au-dela de ce seuil de fraction cid, on tente une reextraction pdfplumber : pdfminer
# a produit du texte en volume mais illisible (mapping police echoue).
_CID_FALLBACK_THRESHOLD = 0.1


def parse_document(path: str, category: str, pages: int | None = None) -> ParsedDoc:
    doc_id = Path(path).stem
    fallback_used = False
    try:
        pages_text = _pages_text_pdfminer(path)
        type_blocks, images_by_page = _typing_pdfplumber(path)
        md, refs = _assemble(pages_text, images_by_page)
        blocks = list(type_blocks)
        for i, t in enumerate(pages_text):
            if t:
                blocks.append(Block(kind="text", text=t, page=i + 1))
        if not md.strip():
            raise ValueError("texte primaire vide")
        # Fallback cid : pdfminer a extrait du volume mais illisible (jetons cid). On tente
        # pdfplumber et on garde l'extraction la moins degradee. Ne leve jamais (chaine S14).
        if cid_failure_fraction(md) > _CID_FALLBACK_THRESHOLD:
            try:
                alt = _pdfplumber_only(path)
                (md, blocks, refs), fallback_used = _better_extraction(
                    (md, blocks, refs), alt)
            except Exception:
                pass
    except Exception:
        try:
            fallback_used = True
            md, blocks, refs = _pdfplumber_only(path)
            if not md.strip():
                raise ValueError("fallback vide")
        except Exception:
            return ParsedDoc(doc_id=doc_id, markdown="",
                             blocks=[Block(kind="unreadable", text="", page=0)],
                             parse_confidence=0.0, images=[])
    return ParsedDoc(doc_id=doc_id, markdown=md, blocks=blocks,
                     parse_confidence=_confidence(md, blocks, pages, fallback_used),
                     images=refs)
