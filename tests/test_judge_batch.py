# tests/test_judge_batch.py
# Levier A : jugement par sections + appel batche. Tests du decoupage, de judge_batch,
# de l'agregation inter-sections et de la preservation de l'anti-fabrication.
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


# --- _split_sections : couverture 100% + recouvrement (overlap facon chunking RAG) ---

def test_split_sections_no_overlap_reconstructs_exactly():
    md = "z" * 20000
    secs = _split_sections(md, 8000, overlap=0)
    assert "".join(secs) == md            # overlap=0 : reconstruction exacte
    assert all(len(s) <= 8000 for s in secs)
    assert len(secs) == 3                 # 8000 + 8000 + 4000


def test_split_sections_overlap_covers_whole_and_overlaps():
    # Contenu varie pour que le controle de recouvrement porte sur de vrais octets.
    md = "".join(chr(33 + (k % 90)) for k in range(20000))
    ov = 800
    secs = _split_sections(md, 8000, overlap=ov)
    assert all(len(s) <= 8000 for s in secs)
    # Couverture 100% par UNION : premiere section + les queues au-dela de l'overlap == md.
    rebuilt = secs[0] + "".join(s[ov:] for s in secs[1:])
    assert rebuilt == md
    # Recouvrement effectif : la fin d'une section == le debut de la suivante (ov caracteres).
    for a, b in zip(secs, secs[1:]):
        assert a[-ov:] == b[:ov]
    assert len(secs) >= 3                 # stride 7200 -> au moins 3 fenetres sur 20000


def test_split_sections_default_overlap_is_proportional():
    # Overlap par defaut = 10% de section_chars (comme un chunking RAG usuel).
    secs = _split_sections("w" * 20000, 8000)
    assert len(secs) == 3                 # stride 7200 : debuts a 0, 7200, 14400
    assert secs[0][-800:] == secs[1][:800]  # recouvrement de 800 par defaut


def test_split_sections_empty_returns_empty():
    assert _split_sections("", 8000) == []


def test_split_sections_short_single():
    assert _split_sections("para", 8000) == ["para"]


# --- judge_batch : dict multi-criteres ---

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


# --- score_document batche : contrat de sortie + anti-fabrication ---

def test_batched_one_score_per_criterion():
    reg = load_registry()
    scores = score_document(_doc("para"), reg, _metrics(), MockLLM(), "h")
    assert len(scores) == len(reg.criteria)


def test_criterion_omitted_in_all_sections_is_not_evaluated():
    # Un critere absent de la reponse LLM de toutes les sections -> not_evaluated (jamais devine).
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


# --- agregation inter-sections : mediane ---

def test_multi_section_aggregation_uses_median():
    reg = load_registry()
    md = "AAAAMARK1A" + "BBBBMARK2B"     # 2 fenetres de 10 caracteres
    llm = MockLLM(batch_responses={
        "MARK1": {"2.5": {"status": "scored", "score": 2, "justification": "sec1", "evidence": "e1"}},
        "MARK2": {"2.5": {"status": "scored", "score": 4, "justification": "sec2", "evidence": "e2"}},
    })
    by_id = {c.id: c for c in score_document(_doc(md), reg, _metrics(), llm, "h",
                                             section_chars=10, section_overlap=0)}
    assert by_id["2.5"].status == "scored"
    assert by_id["2.5"].score == 3        # mediane de [2, 4]


def test_multi_section_one_aberrant_section_ignored():
    # Une section note hors bareme, l'autre note valide -> seule la valide compte.
    reg = load_registry()
    md = "AAAAMARK1A" + "BBBBMARK2B"
    llm = MockLLM(batch_responses={
        "MARK1": {"2.5": {"status": "scored", "score": 99, "justification": "x", "evidence": None}},
        "MARK2": {"2.5": {"status": "scored", "score": 5, "justification": "ok", "evidence": "e2"}},
    })
    by_id = {c.id: c for c in score_document(_doc(md), reg, _metrics(), llm, "h",
                                             section_chars=10, section_overlap=0)}
    assert by_id["2.5"].status == "scored" and by_id["2.5"].score == 5


# --- instrumentation : nb d'appels judge_batch == nb de sections ---

def test_batch_calls_equal_n_sections():
    reg = load_registry()
    md = "q" * 20000                       # 3 sections a 8000
    llm = CountingLLM(MockLLM())
    score_document(_doc(md), reg, _metrics(), llm, "h", section_chars=8000)
    assert llm.n_calls == 3
