# src/cqg/signals.py
import re
from .models import ParsedDoc

_CID_RE = re.compile(r"\(cid:\d+\)")


def cid_failure_fraction(text: str) -> float:
    """Proportion of content lost during extraction : (cid:NNN) tokens and unmapped glyphs.

    A font mapping failure (frequent on old PDFs) makes pdfminer emit
    '(cid:NNN)' tokens instead of the characters, or U+FFFD replacement
    characters. This signal measures the share of the text taken up by these artefacts, relative to the
    total length. 0.0 on clean text ; high on a degraded extraction.
    """
    if not text:
        return 0.0
    n = len(text)
    cid_chars = sum(len(m.group(0)) for m in _CID_RE.finditer(text))
    replacement_chars = text.count("�")
    return round(min(1.0, (cid_chars + replacement_chars) / n), 4)

def non_alpha_fraction(text: str) -> float:
    if not text:
        return 1.0
    alpha = sum(c.isalpha() for c in text)
    return round(1 - alpha / len(text), 4)

def mean_words_per_sentence(text: str) -> float:
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if not sentences:
        return 0.0
    return round(sum(len(s.split()) for s in sentences) / len(sentences), 2)

def duplicate_line_fraction(text: str) -> float:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    seen, dup = set(), 0
    for l in lines:
        if l in seen:
            dup += 1
        seen.add(l)
    return round(dup / len(lines), 4)

def type_token_ratio(text: str) -> float:
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return 0.0
    return round(len(set(tokens)) / len(tokens), 4)

def mattr(text: str, window: int = 1000) -> float:
    """TTR normalised by window (Mean Segmental TTR) : robust to length.

    The global TTR (type_token_ratio) mechanically decreases with length : on a
    long document, the vocabulary saturates and the denominator (total number of tokens)
    crushes the ratio, whatever the real state of the extraction. Example measured on "Le
    Cahier Ma Sante" (222 pages) : global ttr=0.0042 although the vocabulary is healthy.

    We therefore split the text into segments of `window` tokens, compute the TTR of each
    segment and return the mean. A text with a healthy vocabulary keeps a high segment TTR
    even over hundreds of pages ; a genuinely degraded extraction (repeated/unreadable
    text) stays low on every window. For a text shorter than
    `window`, reduces to the global TTR.
    """
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return 0.0
    if len(tokens) < window:
        return round(len(set(tokens)) / len(tokens), 4)
    ratios = []
    for i in range(0, len(tokens) - window + 1, window):
        seg = tokens[i:i + window]
        ratios.append(len(set(seg)) / window)
    return round(sum(ratios) / len(ratios), 4)

def token_count(text: str) -> int:
    """Number of word tokens (same tokenisation as the TTR). Serves as a size proxy
    for the metadata safeguard of the triage (cf. screen.py)."""
    return len(re.findall(r"\w+", text.lower()))

def block_integrity(doc: ParsedDoc) -> float:
    if not doc.blocks:
        return 0.0
    good = sum(1 for b in doc.blocks if b.text.strip())
    return round(good / len(doc.blocks), 4)
