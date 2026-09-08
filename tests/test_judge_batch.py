# tests/test_judge_batch.py
# Lever A: judgment by sections + batched call. Tests of the splitting, of judge_batch,
# of the inter-section aggregation and of the preservation of anti-fabrication.
from cqg.registry.loader import load_registry
from cqg.models import ParsedDoc, Block
from cqg.llm.mock import MockLLM
from cqg.llm.instrument import CountingLLM
from cqg.judge import score_document, _split_sections


def _doc(md):
    return ParsedDoc(doc_id="d", markdown=md, blocks=[Block(kind="text", text=md)],
                     parse_confidence=1.0)


def _metrics():
    return {"na": [], "signals": {}, "d_scores": {}, "h_signals": {}}


# --- _split_sections: 100% coverage + overlap (RAG-chunking-style overlap) ---

def test_split_sections_no_overlap_reconstructs_exactly():
    md = "z" * 20000
    secs = _split_sections(md, 8000, overlap=0)
    assert "".join(secs) == md            # overlap=0: exact reconstruction
    assert all(len(s) <= 8000 for s in secs)
    assert len(secs) == 3                 # 8000 + 8000 + 4000


def test_split_sections_overlap_covers_whole_and_overlaps():
    # Varied content so that the overlap check operates on real bytes.
    md = "".join(chr(33 + (k % 90)) for k in range(20000))
    ov = 800
    secs = _split_sections(md, 8000, overlap=ov)
    assert all(len(s) <= 8000 for s in secs)
    # 100% coverage by UNION: first section + the tails beyond the overlap == md.
    rebuilt = secs[0] + "".join(s[ov:] for s in secs[1:])
    assert rebuilt == md
    # Effective overlap: the end of a section == the start of the next one (ov characters).
    for a, b in zip(secs, secs[1:]):
        assert a[-ov:] == b[:ov]
    assert len(secs) >= 3                 # stride 7200 -> at least 3 windows over 20000


def test_split_sections_default_overlap_is_proportional():
    # Default overlap = 10% of section_chars (like a usual RAG chunking).
    secs = _split_sections("w" * 20000, 8000)
    assert len(secs) == 3                 # stride 7200: starts at 0, 7200, 14400
    assert secs[0][-800:] == secs[1][:800]  # overlap of 800 by default


def test_split_sections_empty_returns_empty():
    assert _split_sections("", 8000) == []


def test_split_sections_short_single():
    assert _split_sections("para", 8000) == ["para"]


# --- judge_batch: multi-criteria dict ---

def test_judge_batch_returns_multi_criteria_dict():
    llm = MockLLM(batch_responses={"": {
        "2.5": {"status": "scored", "score": 3, "justification": "j5", "evidence": None},
        "2.6": {"status": "not_evaluated", "score": None, "justification": "j6", "evidence": None},
    }})
    out = llm.judge_batch("un prompt quelconque", {})
    assert set(out) >= {"2.5", "2.6"}
    assert out["2.5"]["score"] == 3


def test_judge_batch_default_is_empty():
    assert MockLLM().judge_batch("x", {}) == {}


# --- batched score_document: output contract + anti-fabrication ---

def test_batched_one_score_per_criterion():
    reg = load_registry()
    scores = score_document(_doc("para"), reg, _metrics(), MockLLM(), "h")
    assert len(scores) == len(reg.criteria)


def test_criterion_omitted_in_all_sections_is_not_evaluated():
    # A criterion absent from the LLM response of every section -> not_evaluated (never guessed).
    reg = load_registry()
    by_id = {c.id: c for c in score_document(_doc("para"), reg, _metrics(), MockLLM(), "h")}
    assert by_id["2.5"].status == "not_evaluated" and by_id["2.5"].score is None


def test_batched_valid_score_kept():
    reg = load_registry()
    llm = MockLLM(batch_responses={"para": {
        "2.5": {"status": "scored", "score": 4, "justification": "ok", "evidence": "s1"}}})
    by_id = {c.id: c for c in score_document(_doc("para"), reg, _metrics(), llm, "h")}
    assert by_id["2.5"].status == "scored" and by_id["2.5"].score == 4


def test_batched_out_of_scale_not_fabricated():
    reg = load_registry()
    llm = MockLLM(batch_responses={"para": {
        "2.5": {"status": "scored", "score": 9, "justification": "ok", "evidence": None}}})
    by_id = {c.id: c for c in score_document(_doc("para"), reg, _metrics(), llm, "h")}
    assert by_id["2.5"].status == "not_evaluated" and by_id["2.5"].score is None


def test_batched_empty_justification_not_fabricated():
    reg = load_registry()
    llm = MockLLM(batch_responses={"para": {
        "2.5": {"status": "scored", "score": 4, "justification": "  ", "evidence": None}}})
    by_id = {c.id: c for c in score_document(_doc("para"), reg, _metrics(), llm, "h")}
    assert by_id["2.5"].status == "not_evaluated"


# --- inter-section aggregation: median ---

def test_multi_section_aggregation_uses_median():
    reg = load_registry()
    md = "AAAAMARK1A" + "BBBBMARK2B"     # 2 windows of 10 characters
    llm = MockLLM(batch_responses={
        "MARK1": {"2.5": {"status": "scored", "score": 2, "justification": "sec1", "evidence": "e1"}},
        "MARK2": {"2.5": {"status": "scored", "score": 4, "justification": "sec2", "evidence": "e2"}},
    })
    by_id = {c.id: c for c in score_document(_doc(md), reg, _metrics(), llm, "h",
                                             section_chars=10, section_overlap=0)}
    assert by_id["2.5"].status == "scored"
    assert by_id["2.5"].score == 3        # median of [2, 4]


def test_multi_section_one_aberrant_section_ignored():
    # One section scores out of scale, the other scores valid -> only the valid one counts.
    reg = load_registry()
    md = "AAAAMARK1A" + "BBBBMARK2B"
    llm = MockLLM(batch_responses={
        "MARK1": {"2.5": {"status": "scored", "score": 99, "justification": "x", "evidence": None}},
        "MARK2": {"2.5": {"status": "scored", "score": 5, "justification": "ok", "evidence": "e2"}},
    })
    by_id = {c.id: c for c in score_document(_doc(md), reg, _metrics(), llm, "h",
                                             section_chars=10, section_overlap=0)}
    assert by_id["2.5"].status == "scored" and by_id["2.5"].score == 5


# --- instrumentation: number of judge_batch calls == number of sections ---

def test_batch_calls_equal_n_sections():
    reg = load_registry()
    md = "q" * 20000                       # 3 sections of 8000
    llm = CountingLLM(MockLLM())
    score_document(_doc(md), reg, _metrics(), llm, "h", section_chars=8000)
    assert llm.n_calls == 3
