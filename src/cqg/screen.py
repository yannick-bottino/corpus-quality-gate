"""Lever C: two-speed triage.

Deterministic screen that routes each document BEFORE the expensive LLM judgment:
- degraded extraction (high non_alpha, low parse confidence, near-zero vocabulary)
  -> "light" route: we flag for human review without spending ~45 LLM calls on
  unreadable text.
- manifestly clean document (all signals green) -> "light" route: reduced LLM
  judgment, we trust the deterministic signals.
- borderline case -> "full" route: complete LLM judgment.

Score-and-flag, human-in-the-loop: "light" never deletes, it routes and flags.
"""
from .models import ParsedDoc


# Above this volume, a document is "large": the global TTR becomes a length artefact
# there (vocabulary saturates) and the "clean signals" shortcut no longer makes sense.
LARGE_DOC_TOKENS = 10_000


def screen_document(doc: ParsedDoc, metrics: dict) -> dict:
    s = metrics.get("signals", {})
    non_alpha = s.get("non_alpha_fraction", 0.0)
    dup = s.get("duplicate_line_fraction", 0.0)
    ttr = s.get("type_token_ratio", 1.0)
    # Window-normalised TTR: robust to length, unlike the global TTR.
    # Falls back to the global TTR if absent (compat. with legacy calls/tests).
    mattr = s.get("mattr", ttr)
    n_tokens = s.get("n_tokens", 0)
    pc = doc.parse_confidence
    # NB: block_integrity is NOT a degradation signal here. It measures the share of
    # text blocks among all blocks, yet docs rich in images/tables have
    # many empty typed blocks (image/table): a low block_integrity is normal there,
    # not a degradation. Using it as a screen wrongly routes every illustrated doc to light.

    # Metadata guardrail. The global TTR drops mechanically with length: a large
    # document (e.g. "Le Cahier Ma Sante", 222 pages, global ttr=0.0042) with a nonetheless
    # healthy vocabulary would be excluded from LLM judgment by this artefact alone. So for
    # a large document we require several concordant signals before any downgrade: as long
    # as the extraction is healthy (correct parse confidence, reasonable non_alpha, healthy
    # *window* TTR), the document is judged on substance ("full"). This also short-circuits
    # the "clean signals" shortcut (which skips the judgment): a large doc deserves a
    # complete judgment. A REALLY degraded large doc has a low window TTR and falls below.
    extraction_saine = pc >= 0.5 and non_alpha <= 0.40 and mattr >= 0.05
    if n_tokens >= LARGE_DOC_TOKENS and extraction_saine:
        return {"route": "full",
                "reasons": [f"gros_document_extraction_saine (n_tokens={n_tokens}, "
                            f"parse_confidence={pc}, non_alpha={non_alpha}, mattr={mattr})"]}

    # Degraded extraction -> direct flag, no complete judgment. Reliable signals:
    # low parse confidence (cf. lever E), high non-alpha fraction (cid tokens,
    # symbols), near-zero vocabulary (repeated/unreadable text). We rely on the
    # *window* TTR (mattr) and not on the global TTR, so as not to confuse "long document"
    # with "near-zero vocabulary".
    if pc < 0.5 or non_alpha > 0.40 or mattr < 0.05:
        return {"route": "light",
                "reasons": [f"extraction_degradee (parse_confidence={pc}, "
                            f"non_alpha={non_alpha}, mattr={mattr})"]}

    # All signals green -> manifestly clean document, reduced judgment.
    if non_alpha < 0.30 and dup < 0.15 and mattr > 0.15:
        return {"route": "light", "reasons": ["signaux_propres"]}

    return {"route": "full", "reasons": ["cas_limite"]}
