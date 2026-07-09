# tests/test_judge.py
from cqg.registry.loader import load_registry
from cqg.models import ParsedDoc, Block
from cqg.llm.mock import MockLLM
from cqg.judge import score_document

def test_na_external_and_llm_states():
    reg = load_registry()
    doc = ParsedDoc(doc_id="d", markdown="para", blocks=[Block(kind="text", text="p")],
                    parse_confidence=1.0)
    metrics = {"na": ["3.1"], "signals": {}, "d_scores": {"1.3": 5}, "h_signals": {}}
    llm = MockLLM(default={"status": "not_evaluated", "score": None,
                           "justification": "mock", "evidence": None})
    scores = score_document(doc, reg, metrics, llm, "hash123")
    by_id = {c.id: c for c in scores}
    assert by_id["3.1"].status == "na"
    assert by_id["2.7"].status == "not_evaluated"      # external_dep sans referentiel
    assert by_id["1.3"].status == "scored" and by_id["1.3"].score == 5
    assert by_id["2.5"].status == "not_evaluated"      # L, mock renvoie not_evaluated
    assert len(scores) == len(reg.criteria)            # couverture totale, un score par critere

def _doc_and_metrics():
    doc = ParsedDoc(doc_id="d", markdown="para", blocks=[Block(kind="text", text="p")],
                    parse_confidence=1.0)
    metrics = {"na": [], "signals": {}, "d_scores": {}, "h_signals": {}}
    return doc, metrics

class _CountingMock(MockLLM):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = 0

    def judge(self, prompt, schema):
        self.calls += 1
        return super().judge(prompt, schema)


def test_skip_llm_makes_no_llm_calls_and_never_fabricates():
    # Levier C, route light : jugement LLM saute. Les criteres deterministes (na, d_scores)
    # restent scores/na ; les criteres LLM deviennent not_evaluated (anti-fabrication),
    # jamais une note devinee.
    reg = load_registry()
    doc = ParsedDoc(doc_id="d", markdown="para", blocks=[Block(kind="text", text="p")],
                    parse_confidence=1.0)
    metrics = {"na": ["3.1"], "signals": {}, "d_scores": {"1.3": 5}, "h_signals": {}}
    llm = _CountingMock(default={"status": "scored", "score": 5, "justification": "x",
                                 "evidence": None})
    scores = score_document(doc, reg, metrics, llm, "h", skip_llm=True)
    by_id = {c.id: c for c in scores}
    assert llm.calls == 0
    assert by_id["3.1"].status == "na"
    assert by_id["1.3"].status == "scored" and by_id["1.3"].score == 5
    assert by_id["2.5"].status == "not_evaluated"      # critere L -> non evalue (pas de LLM)
    assert len(scores) == len(reg.criteria)


def _scored(resp_25):
    reg = load_registry()
    doc, metrics = _doc_and_metrics()
    # Levier A : le jugement passe par judge_batch (une reponse multi-criteres par section).
    # On seed la reponse batche du critere 2.5 pour la section unique ("para").
    llm = MockLLM(batch_responses={"para": {"2.5": resp_25}})
    return {c.id: c for c in score_document(doc, reg, metrics, llm, "h")}

def test_llm_scored_valid_is_kept():
    by_id = _scored({"status": "scored", "score": 4, "justification": "ok", "evidence": "s1"})
    assert by_id["2.5"].status == "scored" and by_id["2.5"].score == 4

def test_llm_scored_without_score_demoted():
    by_id = _scored({"status": "scored", "justification": "ok"})
    assert by_id["2.5"].status == "not_evaluated" and by_id["2.5"].score is None

def test_llm_score_out_of_scale_demoted():
    by_id = _scored({"status": "scored", "score": 7, "justification": "ok"})
    assert by_id["2.5"].status == "not_evaluated"

def test_llm_na_from_model_is_ignored():
    by_id = _scored({"status": "na", "score": None, "justification": "x"})
    assert by_id["2.5"].status == "not_evaluated"

def test_representative_excerpt_covers_whole_document():
    from cqg.judge import _representative_excerpt
    md = ("DEBUT " + "a"*10000 + " MILIEU " + "b"*10000 + " FIN_UNIQUE_MARQUEUR")
    ex = _representative_excerpt(md, budget=8000)
    assert len(ex) <= 8000 + 200
    assert "DEBUT" in ex
    assert "FIN_UNIQUE_MARQUEUR" in ex  # la fin du document est echantillonnee, pas seulement le debut

def test_short_document_returned_whole():
    from cqg.judge import _representative_excerpt
    md = "petit document"
    assert _representative_excerpt(md, budget=24000) == md

def test_excerpt_budget_non_positive_is_safe():
    from cqg.judge import _representative_excerpt
    assert _representative_excerpt("X" * 50000, budget=-5) == ""
    assert _representative_excerpt("X" * 50000, budget=0) == ""
