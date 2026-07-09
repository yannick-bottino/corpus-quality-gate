import pytest
from pydantic import ValidationError
from cqg.models import CriterionScore

def test_criterion_status_validated():
    c = CriterionScore(id="1.1", tag="D", weight=3, status="scored",
                       score=5, justification="titre clair", evidence="p.1")
    assert c.score == 5

def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        CriterionScore(id="1.1", tag="D", weight=3, status="wat",
                       score=5, justification="x", evidence=None)

def test_not_evaluated_allows_null_score():
    c = CriterionScore(id="2.5", tag="L", weight=5, status="not_evaluated",
                       score=None, justification="info insuffisante", evidence=None)
    assert c.score is None

def test_imageref_and_parseddoc_images():
    from cqg.models import ImageRef, ParsedDoc
    ref = ImageRef(page=12, idx=1, x0=10.0, top=20.0, x1=110.0, bottom=140.0,
                   placeholder="[[IMAGE:p=12;idx=1]]")
    doc = ParsedDoc(doc_id="d", markdown="x", blocks=[], parse_confidence=1.0, images=[ref])
    assert doc.images[0].placeholder == "[[IMAGE:p=12;idx=1]]"
    assert ParsedDoc(doc_id="d", markdown="x", blocks=[], parse_confidence=1.0).images == []
