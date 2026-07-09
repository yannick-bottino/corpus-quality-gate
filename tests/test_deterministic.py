# tests/test_deterministic.py
from cqg.models import ParsedDoc, Block
from cqg.registry.loader import load_registry
from cqg.deterministic import compute_metrics

def test_metrics_marks_na_and_scores():
    doc = ParsedDoc(doc_id="d", markdown="Version v1.2 du 2026-01-01. " * 5,
                    blocks=[Block(kind="text", text="para")], parse_confidence=1.0)
    m = compute_metrics(doc, load_registry())
    assert "3.1" in m["na"]            # pas d'image
    assert "signals" in m and "non_alpha_fraction" in m["signals"]
    assert all(1 <= v <= 5 for v in m["d_scores"].values())


def test_french_textual_date_detected():
    doc = ParsedDoc(doc_id="d",
                    markdown="Notice Essen Ciel Juin 2025. Mise a jour au 1er janvier 2026.",
                    blocks=[Block(kind="text", text="x")], parse_confidence=1.0)
    m = compute_metrics(doc, load_registry())
    assert m["d_scores"]["1.4"] >= 3  # date FR textuelle detectee (sans version -> au moins 3)


def test_content_duplicate_ignores_boilerplate():
    from cqg.deterministic import _content_duplicate_fraction
    # en-tete repete 5x (boilerplate) -> ne compte pas comme doublon de contenu
    txt = "\n".join(["Notice Essen Ciel Juin 2025"] * 5 + ["Paragraphe de contenu unique numero un ici."])
    assert _content_duplicate_fraction(txt) == 0.0


def test_faq_detected_via_question_headings():
    doc = ParsedDoc(doc_id="d",
                    markdown="Quelle est la garantie ?\nQui paie ?\nQuand ?\nComment declarer ?\nCombien ?\nTexte.",
                    blocks=[Block(kind="text", text="x")], parse_confidence=1.0)
    m = compute_metrics(doc, load_registry())
    assert m["d_scores"]["8.1"] == 5
