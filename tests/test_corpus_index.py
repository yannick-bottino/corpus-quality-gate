"""Tests de l'index de corpus (chunk + embed + retrieve, offline model2vec)."""
import numpy as np

from cqg.models import ParsedDoc, Block
from cqg.corpus_index import build_index, retrieve, _chunk


def _doc(doc_id, md):
    return ParsedDoc(doc_id=doc_id, markdown=md, blocks=[Block(kind="text", text=md)],
                     parse_confidence=1.0)


def _char_encoder(texts):
    vocab = "abcdefghijklmnopqrstuvwxyz"
    return np.array([[t.lower().count(c) for c in vocab] for t in texts], dtype=float)


def test_chunk_overlap_covers_text():
    md = "".join(chr(97 + (k % 26)) for k in range(300))
    chunks = _chunk(md, 100, 20)
    rebuilt = chunks[0] + "".join(c[20:] for c in chunks[1:])
    assert rebuilt == md
    assert all(len(c) <= 100 for c in chunks)


def test_build_index_tags_each_chunk_with_doc_id():
    docs = [_doc("A", "a" * 250), _doc("B", "b" * 120)]
    idx = build_index(docs, chunk_chars=100, overlap=0, encoder=_char_encoder)
    doc_ids = {e["doc_id"] for e in idx["entries"]}
    assert doc_ids == {"A", "B"}
    assert idx["emb"].shape[0] == len(idx["entries"])


def test_retrieve_returns_most_similar_chunk_across_docs():
    docs = [_doc("incendie", "aaaa"), _doc("degat_eaux", "zzzz")]
    idx = build_index(docs, chunk_chars=100, overlap=0, encoder=_char_encoder)
    hits = retrieve(idx, "aaaa", k=1, encoder=_char_encoder)
    assert hits and hits[0]["doc_id"] == "incendie"


def test_retrieve_empty_index_is_safe():
    idx = build_index([], chunk_chars=100, overlap=0, encoder=_char_encoder)
    assert retrieve(idx, "q", k=3, encoder=_char_encoder) == []
