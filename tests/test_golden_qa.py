# tests/test_golden_qa.py
import os
from cqg.models import ParsedDoc, Block
from cqg.llm.mock import MockLLM
from cqg.golden_qa import generate_golden_qa, write_golden_qa, _prompt


def test_prompt_exige_des_questions_naturelles_utilisateur():
    doc = ParsedDoc(doc_id="d", markdown="texte", blocks=[Block(kind="text", text="t")],
                    parse_confidence=1.0)
    p = _prompt(doc, "gestionnaire sinistres", "POLICY").lower()
    # Questions must be natural user sentences (chatbot style), not keywords.
    assert "phrase" in p
    assert "chatbot" in p or "utilisateur" in p
    assert "mot-cle" in p or "mots-cles" in p


def test_prompt_auto_count_pilote_par_densite():
    doc = ParsedDoc(doc_id="d", markdown="texte", blocks=[Block(kind="text", text="t")],
                    parse_confidence=1.0)
    p = _prompt(doc, "p", "POL", n_questions="auto").lower()
    assert "densite" in p            # auto: the LLM chooses based on information density
    assert "fixe" in p               # instruction not to impose a fixed number


def test_prompt_nombre_fixe_reglable():
    doc = ParsedDoc(doc_id="d", markdown="texte", blocks=[Block(kind="text", text="t")],
                    parse_confidence=1.0)
    p = _prompt(doc, "p", "POL", n_questions=7).lower()
    assert "7 question" in p          # number adjustable by hand


def _char_encoder(texts):
    import numpy as np
    vocab = "abcdefghijklmnopqrstuvwxyz"
    return np.array([[t.lower().count(c) for c in vocab] for t in texts], dtype=float)


def test_generate_corpus_golden_qa_v2_ancre_par_retrieval():
    # V2: cross-cutting questions grounded by retrieval over the full text of the corpus.
    # Two LLM stages: proposing the questions, then answering grounded on the retrieved chunks.
    from cqg.golden_qa import generate_corpus_golden_qa
    d1 = ParsedDoc(doc_id="contratA", markdown="aaaa le contrat couvre l'incendie",
                   blocks=[Block(kind="text", text="x")], parse_confidence=1.0)
    d2 = ParsedDoc(doc_id="contratB", markdown="zzzz le contrat couvre le degat des eaux",
                   blocks=[Block(kind="text", text="x")], parse_confidence=1.0)
    llm = MockLLM(responses={
        "PROPOSE": {"questions": [
            {"question": "Entre les deux contrats, lequel couvre l'incendie ?"}]},
        "UNIQUEMENT sur les extraits": {
            "reponse": "Le contrat A couvre l'incendie, pas le B.", "couvert": "oui"},
    })
    rows = generate_corpus_golden_qa([d1, d2], profile="client", llm=llm, policy="POL",
                                     k=2, chunk_chars=100, encoder=_char_encoder)
    assert rows and rows[0]["origine"] == "corpus"
    assert rows[0]["id"].startswith("corpus-")
    assert rows[0]["couvert"] == "oui"
    assert ";" in rows[0]["sources"]          # sources = retrieved doc_ids (>= 2 documents)
    assert "contratA" in rows[0]["sources"] and "contratB" in rows[0]["sources"]
    assert rows[0]["statut_validation"] == "a_valider"


def test_corpus_golden_qa_needs_two_docs():
    from cqg.golden_qa import generate_corpus_golden_qa
    d1 = ParsedDoc(doc_id="seul", markdown="texte", blocks=[Block(kind="text", text="x")],
                   parse_confidence=1.0)
    assert generate_corpus_golden_qa([d1], "p", MockLLM(), "POL", encoder=_char_encoder) == []

def test_generate_and_write(tmp_path):
    doc = ParsedDoc(doc_id="d", markdown="Le produit X couvre le risque incendie.",
                    blocks=[Block(kind="text", text="...")], parse_confidence=1.0)
    llm = MockLLM(default={"questions": [
        {"question": "Le produit X couvre-t-il l'incendie ?",
         "reponse": "Oui, le produit X couvre l'incendie.",
         "sources": "section 1", "couvert": "oui", "origine": "document"}]})
    rows = generate_golden_qa(doc, profile="gestionnaire sinistres", llm=llm, policy="POLICY")
    assert rows and rows[0]["statut_validation"] == "a_valider"
    paths = write_golden_qa(rows, str(tmp_path))
    assert os.path.exists(paths["xlsx"]) and os.path.exists(paths["csv"])

def test_uncovered_question_defaults_to_marker():
    doc = ParsedDoc(doc_id="d", markdown="x", blocks=[Block(kind="text", text="x")],
                    parse_confidence=1.0)
    llm = MockLLM(default={"questions": [{"question": "Q?", "sources": "", "origine": "profil"}]})
    rows = generate_golden_qa(doc, profile="p", llm=llm, policy="POLICY")
    assert rows[0]["couvert"] == "non"
    assert rows[0]["reponse"] == "Non couvert par le document"

def test_golden_csv_escapes_special_chars(tmp_path):
    import csv as _csvmod
    rows = [{"id": "d-1", "origine": "document", "question": "Q?",
             "reponse": "Oui; couvre incendie.\nVoir 2.1", "sources": "s1", "couvert": "oui",
             "statut_validation": "a_valider", "commentaire_beta": ""}]
    paths = write_golden_qa(rows, str(tmp_path))
    with open(paths["csv"], encoding="utf-8-sig", newline="") as f:
        parsed = list(_csvmod.reader(f, delimiter=";"))
    assert len(parsed[1]) == len(parsed[0])
    assert any("Oui; couvre incendie." in cell for cell in parsed[1])

def test_golden_csv_neutralizes_formula_injection(tmp_path):
    import csv as _csvmod
    rows = [{"id": "d-1", "origine": "document", "question": "=cmd()", "reponse": "ok",
             "sources": "s", "couvert": "oui", "statut_validation": "a_valider", "commentaire_beta": ""}]
    paths = write_golden_qa(rows, str(tmp_path))
    with open(paths["csv"], encoding="utf-8-sig", newline="") as f:
        parsed = list(_csvmod.reader(f, delimiter=";"))
    assert any(cell.startswith("'=cmd") for cell in parsed[1])
