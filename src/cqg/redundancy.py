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
            # SemHash loads/downloads an embedding model (model2vec) : if the model
            # is not available (offline, download failed), near-duplicate detection
            # is disabled cleanly rather than bringing down the whole
            # batch (consistent with the intent "semhash optional, silent degradation").
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
