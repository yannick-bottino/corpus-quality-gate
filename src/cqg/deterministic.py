# src/cqg/deterministic.py
import re
from .models import ParsedDoc
from .registry.loader import Registry
from .inventory import na_decisions
from . import signals

def _has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE))

def _content_duplicate_fraction(text: str) -> float:
    # Doublons de contenu, en excluant le boilerplate (en-tetes/pieds repetes sur toutes
    # les pages) et les lignes tres courtes. Corrige le faux positif du critere 4.5.
    from collections import Counter
    lines = [l.strip() for l in text.splitlines() if len(l.strip()) >= 15]
    counts = Counter(lines)
    kept = [l for l in lines if counts[l] <= 3]  # >3 occurrences = boilerplate, exclu
    if not kept:
        return 0.0
    seen, dup = set(), 0
    for l in kept:
        if l in seen:
            dup += 1
        seen.add(l)
    return round(dup / len(kept), 4)

def compute_metrics(doc: ParsedDoc, reg: Registry) -> dict:
    text = doc.markdown
    sig = {
        "non_alpha_fraction": signals.non_alpha_fraction(text),
        "mean_words_per_sentence": signals.mean_words_per_sentence(text),
        "duplicate_line_fraction": signals.duplicate_line_fraction(text),
        "type_token_ratio": signals.type_token_ratio(text),
        "block_integrity": signals.block_integrity(doc),
    }
    _MONTHS_FR = (r"(?:janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t"
                  r"|septembre|octobre|novembre|d[eé]cembre)")
    has_version = _has(text, r"\bv\d+(\.\d+)?\b|version\s+\d+|r[eé]vision\s+\d+|[eé]dition\s+\d{4}")
    has_date = _has(
        text,
        r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}"
        r"|\d{1,2}\s?(?:er)?\s+" + _MONTHS_FR + r"\s+\d{4}"
        r"|" + _MONTHS_FR + r"\s+\d{4}",
    )
    d_scores = {
        "1.3": 5 if _has(text, r"auteur|r[eé]dig[eé]|contributeur") else 1,
        "1.4": 5 if (has_version and has_date) else (3 if (has_version or has_date) else 1),
        "1.6": 5 if _has(text, r"mise\s+a\s+jour|revu\s+chaque") else 1,
        "1.7": 5 if _has(text, r"valid[eé]|en cours|brouillon|archiv|obsol") else 1,
        "1.8": 5 if _has(text, r"changelog|historique des (modif|changements)|table des r[eé]visions") else 1,
        "1.9": 5 if (has_version and has_date) else (3 if (has_version or has_date) else 1),
        "8.1": 5 if (_has(text, r"\bFAQ\b|questions fr[eé]quentes|questions/r[eé]ponses")
                     or len([l for l in text.splitlines() if l.strip().endswith("?")]) >= 5) else 1,
    }
    dup = _content_duplicate_fraction(text)
    d_scores["4.5"] = 5 if dup == 0 else (3 if dup <= 0.05 else 1)
    return {
        "na": sorted(na_decisions(doc, reg)),
        "signals": sig,
        "d_scores": {k: v for k, v in d_scores.items()},
        "h_signals": {},  # rempli en enrichissant plus tard ; le LLM ajuste les H
    }
