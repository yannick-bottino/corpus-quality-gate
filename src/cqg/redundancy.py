import hashlib
from collections import defaultdict

def _semhash_available() -> bool:
    try:
        import semhash  # noqa: F401
        return True
    except Exception:
        return False

def _norm(t: str) -> str:
    return " ".join(t.split()).strip().lower()

def corpus_redundancy(docs: list[tuple[str, str]]) -> dict:
    buckets = defaultdict(list)
    for doc_id, text in docs:
        buckets[hashlib.sha256(_norm(text).encode()).hexdigest()].append(doc_id)
    exact = [ids for ids in buckets.values() if len(ids) > 1]
    near = []
    if not _semhash_available():
        near_status = "skipped: semhash indisponible"
    elif not docs:
        near_status = "skipped: aucun document"
    else:
        try:
            from semhash import SemHash
            records = [t for _, t in docs]
            ids = [d for d, _ in docs]
            # SemHash charge/telecharge un modele d'embedding (model2vec) : si le modele
            # n'est pas disponible (hors ligne, telechargement echoue), la detection de
            # quasi-doublons est desactivee proprement plutot que de faire tomber tout le
            # batch (coherent avec l'intention "semhash optionnel, degradation silencieuse").
            result = SemHash.from_records(records=records).self_deduplicate()
            for dr in getattr(result, "duplicates", []):
                try:
                    a = ids[records.index(dr.record)]
                    for dup in dr.duplicates:
                        b = ids[records.index(dup[0])]
                        near.append({"a": a, "b": b, "score": round(float(dup[1]), 3)})
                except (ValueError, AttributeError, IndexError):
                    continue
            near_status = "ok"
        except Exception as exc:
            near = []
            near_status = f"skipped: {type(exc).__name__}"
    return {"exact_duplicates": exact, "near_duplicates": near,
            "near_duplicates_status": near_status}
