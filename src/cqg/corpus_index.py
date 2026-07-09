"""Index de corpus pour la generation de golden Q/R transverses (V2, retrieval texte integral).

Chunke tous les documents, embarque chaque chunk (model2vec, hors ligne) en gardant son
doc_id d'origine, et permet de recuperer les chunks les plus proches d'une question A TRAVERS
tout le corpus. C'est ce qui permet d'ancrer une reponse transverse sur le contenu reel de
plusieurs documents (et pas sur un simple synopsis tronque).
"""
import numpy as np

from .models import ParsedDoc

_MODEL = None
_MODEL_NAME = "minishlab/potion-base-8M"


def _default_encoder(texts):
    global _MODEL
    if _MODEL is None:
        from model2vec import StaticModel
        _MODEL = StaticModel.from_pretrained(_MODEL_NAME)
    return np.asarray(_MODEL.encode(list(texts)), dtype=float)


def _chunk(text: str, chunk_chars: int, overlap: int) -> list[str]:
    # Fenetres de chunk_chars avec recouvrement (meme logique que le decoupage du levier A).
    if not text:
        return []
    size = max(1, int(chunk_chars))
    ov = min(max(0, int(overlap)), size - 1)
    stride = size - ov
    out, i, n = [], 0, len(text)
    while i < n:
        out.append(text[i:i + size])
        if i + size >= n:
            break
        i += stride
    return out


def build_index(docs: list[ParsedDoc], chunk_chars: int = 1000, overlap: int = 100,
                encoder=None) -> dict:
    encoder = encoder or _default_encoder
    entries, texts = [], []
    for d in docs:
        for ch in _chunk(d.markdown, chunk_chars, overlap):
            entries.append({"doc_id": d.doc_id, "text": ch})
            texts.append(ch)
    if not texts:
        return {"entries": [], "emb": None}
    emb = np.asarray(encoder(texts), dtype=float)
    return {"entries": entries, "emb": emb}


def retrieve(index: dict, query: str, k: int = 5, encoder=None) -> list[dict]:
    entries = index.get("entries", [])
    emb = index.get("emb")
    if not entries or emb is None:
        return []
    encoder = encoder or _default_encoder
    q = np.asarray(encoder([query]), dtype=float)[0]
    en = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    qn = q / (np.linalg.norm(q) + 1e-9)
    sims = en @ qn
    order = np.argsort(-sims)[:max(1, int(k))]
    return [{"doc_id": entries[i]["doc_id"], "text": entries[i]["text"],
             "score": float(sims[i])} for i in order]
