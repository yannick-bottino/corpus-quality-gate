# src/cqg/golden_qa.py
import csv
from pathlib import Path
from openpyxl import Workbook
from .models import ParsedDoc
from .llm.base import LLMClient
from .report import _sanitize_cell

_COLS = ["id", "origine", "question", "reponse", "sources", "couvert",
         "statut_validation", "commentaire_beta"]

# Style impose a TOUTES les questions (par document et corpus) : phrase naturelle d'usager.
_STYLE = (
    "STYLE DES QUESTIONS (imperatif) : chaque question doit etre une PHRASE COMPLETE et "
    "NATURELLE, telle qu'un utilisateur reel la taperait a un chatbot d'assistance. Langage "
    "courant, ponctuation, point d'interrogation. INTERDIT : les mots-cles, les listes de "
    "termes, le style telegraphique (ex. n'ecris PAS 'Delai prescription ?' ni "
    "'Commanditaire, date ?' ; ecris 'Quel est le delai de prescription pour agir ?' ou "
    "'Au bout de combien de temps mon contrat ne me couvre-t-il plus ?')."
)


def _count_instruction(n_questions) -> str:
    # Nombre de questions : soit fixe (regle a la main via la config), soit "auto" (le LLM
    # choisit selon la DENSITE d'information du document ou du corpus).
    if n_questions is None or str(n_questions).strip().lower() == "auto":
        return ("Choisis TOI-MEME le nombre de questions selon la DENSITE d'information : un "
                "document pauvre en informations -> peu de questions (3 a 4) ; un document dense "
                "-> davantage (jusqu'a 12 a 15). N'impose aucun nombre fixe.")
    return f"Genere exactement {int(n_questions)} questions variees."


def _json_instruction(origine_valeurs: str) -> str:
    return ("Reponds en JSON: {questions: [{question, reponse, sources, couvert (oui|non), "
            f"origine ({origine_valeurs})}}]}}")


def _prompt(doc: ParsedDoc, profile: str, policy: str, n_questions="auto") -> str:
    return (
        "Genere un jeu de questions/reponses de reference (golden set) pour ce profil utilisateur.\n"
        f"Profil: {profile}\n"
        f"{_count_instruction(n_questions)} Elles couvrent les points importants du document.\n"
        f"{_STYLE} Formule les questions du point de vue de ce profil, dans ses mots.\n"
        "Regle absolue: ne fabrique aucune reponse absente du document. Si non couvert, "
        "reponse='Non couvert par le document', couvert='non'.\n"
        f"Politique de reponse a respecter:\n{policy}\n"
        f"{_json_instruction('profil|document')}\n\n"
        f"Document:\n{doc.markdown[:6000]}"
    )


def _corpus_questions_prompt(docs: list[ParsedDoc], profile: str, policy: str,
                             n_questions="auto", synopsis_chars: int = 1200) -> str:
    # Etage 1 (proposition) : a partir d'une carte du corpus (id + synopsis), PROPOSE des
    # questions transverses dont la reponse exige d'au moins DEUX documents.
    carte = "\n\n".join(f"[{d.doc_id}]\n{d.markdown[:synopsis_chars]}" for d in docs)
    return (
        "PROPOSE des questions transverses au corpus : chacune doit exiger d'au moins DEUX "
        "documents pour y repondre (comparaison, mise en relation, renvoi, coherence ou "
        "contradiction entre documents). Ne reponds PAS encore, propose seulement les questions.\n"
        f"Profil: {profile}\n"
        f"{_count_instruction(n_questions)}\n"
        f"{_STYLE}\n"
        f"Politique visee (contexte):\n{policy}\n"
        "Reponds en JSON: {questions: [{question}]}\n\n"
        f"Corpus (identifiant puis extrait de chaque document):\n{carte}"
    )


def _corpus_answer_prompt(question: str, contexte: str, policy: str) -> str:
    # Etage 2 (reponse ancree) : reponds a la question transverse en t'appuyant UNIQUEMENT sur
    # les extraits recuperes (retrieval sur le texte integral), qui portent leur doc_id.
    return (
        "Reponds a la question suivante en t'appuyant UNIQUEMENT sur les extraits fournis "
        "(chacun prefixe par son identifiant de document entre crochets).\n"
        "Regle absolue: ne fabrique rien. Si les extraits ne contiennent pas la reponse, "
        "reponse='Non couvert par le document', couvert='non'.\n"
        f"Politique de reponse a respecter:\n{policy}\n"
        "Reponds en JSON: {reponse, couvert (oui|non)}\n\n"
        f"Question:\n{question}\n\nExtraits recuperes:\n{contexte}"
    )


def _rows_from_response(resp: dict, id_prefix: str, origine_defaut: str) -> list[dict]:
    rows = []
    for i, q in enumerate(resp.get("questions", []), start=1):
        # Anti-fabrication : seule une reponse explicitement couverte ("oui") ET non vide est
        # conservee ; tout le reste bascule sur le marqueur "Non couvert par le document".
        couvert = (q.get("couvert") or "non").strip().lower()
        reponse = (q.get("reponse") or "").strip()
        if couvert != "oui" or not reponse:
            couvert, reponse = "non", "Non couvert par le document"
        rows.append({
            "id": f"{id_prefix}-{i}",
            "origine": q.get("origine", origine_defaut),
            "question": q.get("question", ""),
            "reponse": reponse,
            "sources": q.get("sources", ""),
            "couvert": couvert,
            "statut_validation": "a_valider",
            "commentaire_beta": "",
        })
    return rows


def generate_golden_qa(doc: ParsedDoc, profile: str, llm: LLMClient, policy: str,
                       n_questions="auto") -> list[dict]:
    resp = llm.judge(_prompt(doc, profile, policy, n_questions), {"type": "object"})
    return _rows_from_response(resp, doc.doc_id, "document")


def generate_corpus_golden_qa(docs: list[ParsedDoc], profile: str, llm: LLMClient,
                              policy: str, n_questions="auto", k: int = 6,
                              chunk_chars: int = 1000, overlap: int = 100,
                              encoder=None) -> list[dict]:
    # V2 : questions transverses ANCREES PAR RETRIEVAL sur le texte integral du corpus.
    #  Etage 1 : proposer les questions transverses (carte du corpus).
    #  Etage 2 : pour chaque question, recuperer les chunks les plus proches DANS TOUT LE CORPUS,
    #            puis repondre en s'appuyant uniquement sur eux. Les sources sont les doc_ids
    #            reellement recuperes (donc multi-documents par construction), pas un synopsis.
    # Anti-fabrication : reponse gardee seulement si couverte par les extraits, sinon marqueur.
    if len(docs) < 2:
        return []
    from .corpus_index import build_index, retrieve
    index = build_index(docs, chunk_chars=chunk_chars, overlap=overlap, encoder=encoder)
    prop = llm.judge(_corpus_questions_prompt(docs, profile, policy, n_questions),
                     {"type": "object"})
    questions = [(q.get("question") or "").strip()
                 for q in prop.get("questions", []) if (q.get("question") or "").strip()]
    rows = []
    for i, question in enumerate(questions, start=1):
        hits = retrieve(index, question, k=k, encoder=encoder)
        contexte = "\n\n".join(f"[{h['doc_id']}] {h['text']}" for h in hits)
        # sources = doc_ids effectivement mobilises par le retrieval, ordre stable.
        src_docs, seen = [], set()
        for h in hits:
            if h["doc_id"] not in seen:
                seen.add(h["doc_id"]); src_docs.append(h["doc_id"])
        ans = llm.judge(_corpus_answer_prompt(question, contexte, policy), {"type": "object"})
        couvert = (ans.get("couvert") or "non").strip().lower()
        reponse = (ans.get("reponse") or "").strip()
        if couvert != "oui" or not reponse:
            couvert, reponse = "non", "Non couvert par le document"
        rows.append({
            "id": f"corpus-{i}",
            "origine": "corpus",
            "question": question,
            "reponse": reponse,
            "sources": "; ".join(src_docs),
            "couvert": couvert,
            "statut_validation": "a_valider",
            "commentaire_beta": "",
        })
    return rows

def write_golden_qa(rows: list[dict], out_dir: str) -> dict:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    wb = Workbook(); ws = wb.active; ws.title = "golden_qa"
    ws.append(_COLS)
    for r in rows:
        ws.append([_sanitize_cell(r[c]) for c in _COLS])
    xlsx = out / "golden_qa.xlsx"; wb.save(xlsx)
    csv_path = out / "golden_qa.csv"
    # csv.writer echappe ; guillemets et retours ligne ; utf-8-sig pour les accents dans Excel.
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(_COLS)
        for r in rows:
            writer.writerow([_sanitize_cell(r[c]) for c in _COLS])
    return {"xlsx": str(xlsx), "csv": str(csv_path)}
