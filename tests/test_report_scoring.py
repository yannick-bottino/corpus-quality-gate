# tests/test_report_scoring.py
from cqg.registry.loader import load_registry
from cqg.models import CriterionScore
from cqg.report import compute_doc_score

def _cs(id, tag, w, status, score):
    return CriterionScore(id=id, tag=tag, weight=w, status=status, score=score,
                          justification="x", evidence=None)

def test_level_and_coverage():
    reg = load_registry()
    crits = []
    for c in reg.criteria:
        if c.id == "2.5":
            crits.append(_cs(c.id, c.tag, c.weight, "not_evaluated", None))
        elif c.na_possible:
            crits.append(_cs(c.id, c.tag, c.weight, "na", None))
        else:
            crits.append(_cs(c.id, c.tag, c.weight, "scored", 5))
    ds = compute_doc_score("d", crits, reg, 0.9, "h")
    assert ds.level == "Excellent"           # quasi tout à 5
    assert 0.0 < ds.coverage_pct < 100.0     # un not_evaluated présent
    assert "low_coverage" in ds.flags or ds.coverage_pct >= 70

def test_low_coverage_flag_raised():
    reg = load_registry()
    crits = []
    for i, c in enumerate(reg.criteria):
        status, score = ("scored", 4) if i % 5 == 0 else ("not_evaluated", None)
        crits.append(_cs(c.id, c.tag, c.weight, status, score))
    ds = compute_doc_score("d", crits, reg, 0.9, "h")
    assert ds.coverage_pct < 70
    assert "low_coverage" in ds.flags

def test_scored_none_excluded_from_coverage():
    reg = load_registry()
    a, b, c = reg.criteria[0], reg.criteria[1], reg.criteria[2]
    crits = [_cs(a.id, a.tag, a.weight, "scored", 4),
             _cs(b.id, b.tag, b.weight, "scored", None),        # malforme : exclu du calcul
             _cs(c.id, c.tag, c.weight, "not_evaluated", None)]
    ds = compute_doc_score("d", crits, reg, 0.9, "h")
    assert ds.coverage_pct == 50.0  # 1 scored valide / (1 scored + 1 not_evaluated)
