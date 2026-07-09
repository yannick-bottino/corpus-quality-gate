from cqg.redundancy import corpus_redundancy

def test_exact_duplicates_detected(monkeypatch):
    monkeypatch.setattr("cqg.redundancy._semhash_available", lambda: False)
    docs = [("a", "meme texte identique"), ("b", "meme texte identique"), ("c", "autre")]
    r = corpus_redundancy(docs)
    assert ["a", "b"] in [sorted(p) for p in r["exact_duplicates"]]
    assert r["near_duplicates"] == []
