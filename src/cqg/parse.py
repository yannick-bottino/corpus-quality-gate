import subprocess
import sys
import tempfile
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
            # pdfplumber conserve le cache d'objets de chaque page : sur un gros PDF
            # (des centaines de pages) l'accumulation sature la memoire (OOM). On libere
            # le cache par page, l'empreinte reste bornee.
            page.flush_cache()
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
            # Idem _typing_pdfplumber : cache par page libere pour borner la memoire.
            page.flush_cache()
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

# Timeout genereux du worker Docling (gros documents). Un depassement leve et bascule legacy.
_DOCLING_TIMEOUT = 1800

# Traitement Docling par lots de pages, chaque lot dans un sous-processus FRAIS : les modeles
# rechargent a chaque lot mais la RAM est liberee a la sortie du process (un convert whole-doc
# OOM sous ~1,2 Go de baseline). 1 page = pic RSS ~1,1 Go, seul lot sur ~1,2 Go de baseline.
_DOCLING_BATCH_PAGES = 1


def _docling_extraction(path: str, pages: int | None = None,
                        batch_pages: int | None = None) -> tuple[str, list[Block], list[ImageRef]]:
    # Docling isole en sous-processus : un OOM (SIGKILL -9/137) est vu via returncode et
    # bascule sur legacy au lieu de crasher le pipeline. Leve RuntimeError sur tout echec.
    # Traitement par lots de pages (process frais par lot) pour borner la RAM. Repli par lot
    # sur pdfminer si un lot echoue (OOM/rc!=0/vide) : on garde du contenu sans perdre le doc.
    if batch_pages is None:
        batch_pages = _DOCLING_BATCH_PAGES
    from pypdf import PdfReader
    n = len(PdfReader(path).pages)
    pm_pages: list[str] | None = None  # texte pdfminer calcule paresseusement au 1er echec
    md_parts: list[str] = []
    for start in range(1, n + 1, batch_pages):
        end = min(start + batch_pages - 1, n)
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
            tmp_out = tmp.name
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "cqg.docling_worker", path, tmp_out, str(start), str(end)],
                timeout=_DOCLING_TIMEOUT, capture_output=True)
            batch_md = ""
            if proc.returncode == 0:
                batch_md = _nfkc(Path(tmp_out).read_text(encoding="utf-8")).strip()
        finally:
            try:
                Path(tmp_out).unlink()
            except OSError:
                pass
        if proc.returncode != 0 or not batch_md:
            # Repli du lot en echec : texte pdfminer des pages concernees (1-based -> index 0-based).
            if pm_pages is None:
                pm_pages = _pages_text_pdfminer(path)
            fb = [_nfkc(pm_pages[i]).strip() for i in range(start - 1, end) if i < len(pm_pages)]
            batch_md = "\n\n".join(p for p in fb if p)
        if batch_md:
            md_parts.append(batch_md)
    md = "\n\n".join(md_parts)
    if not md:
        raise RuntimeError("markdown docling vide")
    # Typage (tables/images) + coords images : reutilise pdfplumber, ce qui garde le
    # chemin image -> enrichissement VLM fonctionnel. Les blocs texte viennent du markdown
    # docling (structure), decoupes sur les lignes vides.
    type_blocks, images_by_page = _typing_pdfplumber(path)
    blocks = list(type_blocks)
    for para in md.split("\n\n"):
        if para.strip():
            blocks.append(Block(kind="text", text=para.strip(), page=0))
    # Placeholders images groupes par page, meme format que _assemble, appendus en fin de md.
    refs: list[ImageRef] = []
    ph_parts: list[str] = []
    for i in sorted(images_by_page):
        for k, im in enumerate(images_by_page[i], start=1):
            ph = f"[[IMAGE:p={i + 1};idx={k}]]"
            ph_parts.append(ph)
            refs.append(ImageRef(page=i + 1, idx=k, x0=im["x0"], top=im["top"],
                                 x1=im["x1"], bottom=im["bottom"], placeholder=ph))
    if ph_parts:
        md = md + "\n\n" + "\n\n".join(ph_parts)
    return md, blocks, refs


def parse_document(path: str, category: str, pages: int | None = None,
                   parser: str = "docling",
                   docling_batch_pages: int | None = None) -> ParsedDoc:
    doc_id = Path(path).stem
    fallback_used = False
    # Docling est le parser par defaut. Sur toute exception (import/OOM/erreur), on retombe
    # sur la chaine legacy (pdfminer + pdfplumber) : robustesse score-and-flag, jamais de crash.
    if parser == "docling":
        try:
            md, blocks, refs = _docling_extraction(path, pages=pages, batch_pages=docling_batch_pages)
            return ParsedDoc(doc_id=doc_id, markdown=md, blocks=blocks,
                             parse_confidence=_confidence(md, blocks, pages, fallback_used),
                             images=refs)
        except Exception:
            pass
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
