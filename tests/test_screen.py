"""Tests of lever C: two-speed triage (deterministic screen -> full | light)."""
from cqg.screen import screen_document
from cqg.models import ParsedDoc, Block


def _doc(pc=0.9):
    return ParsedDoc(doc_id="d", markdown="x", blocks=[Block(kind="text", text="x")],
                     parse_confidence=pc)


def _metrics(non_alpha=0.25, dup=0.1, ttr=0.2, bi=0.95):
    return {"signals": {"non_alpha_fraction": non_alpha, "duplicate_line_fraction": dup,
                        "type_token_ratio": ttr, "block_integrity": bi}}


def test_degraded_extraction_routes_light_without_full_judge():
    # Degraded extraction (CG Auto case: high non_alpha) -> direct flag, no full judgment.
    res = screen_document(_doc(), _metrics(non_alpha=0.47, ttr=0.04))
    assert res["route"] == "light"
    assert any("degrad" in r for r in res["reasons"])


def test_low_parse_confidence_routes_light():
    res = screen_document(_doc(pc=0.35), _metrics())
    assert res["route"] == "light"


def test_clean_document_routes_light():
    res = screen_document(_doc(), _metrics(non_alpha=0.22, dup=0.05, ttr=0.30, bi=0.95))
    assert res["route"] == "light"
    assert any("propre" in r for r in res["reasons"])


def test_borderline_document_routes_full():
    # Neither degraded nor obviously clean (high duplicates) -> full judgment.
    res = screen_document(_doc(), _metrics(non_alpha=0.26, dup=0.26, ttr=0.17, bi=0.9))
    assert res["route"] == "full"


def test_image_rich_low_block_integrity_not_flagged_degraded():
    # Regression: a document rich in images (low block_integrity) but with correct text
    # must NOT be routed light-degraded. block_integrity does not drive the screen.
    res = screen_document(_doc(pc=0.7), _metrics(non_alpha=0.27, dup=0.2, ttr=0.16, bi=0.13))
    assert res["route"] == "full"


def test_large_healthy_doc_routes_full_despite_low_global_ttr():
    # "Le Cahier Ma Sante" case: 222 pages, global TTR crushed by the length (0.0042)
    # but HEALTHY extraction (parse_confidence, non_alpha, windowed TTR all green).
    # Metadata safeguard: a large healthy document must be judged on substance (route
    # "full"), never excluded from LLM judgment on the sole artifact of the global TTR.
    metrics = {"signals": {"non_alpha_fraction": 0.2298, "duplicate_line_fraction": 0.30,
                           "type_token_ratio": 0.0042, "mattr": 0.1725, "n_tokens": 227792,
                           "block_integrity": 0.5}}
    res = screen_document(_doc(pc=0.747), metrics)
    assert res["route"] == "full"
    assert any("gros_document" in r for r in res["reasons"])


def test_large_but_genuinely_degraded_doc_still_routes_light():
    # Safeguard: the metadata safeguard must NOT over-trigger. A large document
    # REALLY degraded (windowed TTR collapsed too) stays flagged as light.
    metrics = {"signals": {"non_alpha_fraction": 0.20, "duplicate_line_fraction": 0.30,
                           "type_token_ratio": 0.001, "mattr": 0.02, "n_tokens": 227792,
                           "block_integrity": 0.5}}
    res = screen_document(_doc(pc=0.7), metrics)
    assert res["route"] == "light"
    assert any("degrad" in r for r in res["reasons"])
