# src/cqg/judge.py
import statistics

from .models import CriterionScore, ParsedDoc
from .registry.loader import Registry
from .llm.base import LLMClient

_SCHEMA = {"type": "object", "required": ["status", "justification"]}
_BATCH_SCHEMA = {"type": "object"}


def _representative_excerpt(markdown: str, budget: int = 24000) -> str:
    # Conserve pour compatibilite (baseline) : echantillonnage d'un extrait representatif.
    # Le levier A ne s'en sert plus (couverture 100% par sections), mais la fonction reste
    # utilisee par la suite de tests baseline.
    budget = max(int(budget), 0)
    if budget == 0:
        return ""
    if len(markdown) <= budget:
        return markdown
    head = int(budget * 0.5)
    rest_budget = budget - head
    parts = [markdown[:head]]
    remaining = markdown[head:]
    n = 4  # nombre de fenetres reparties
    win = max(1, rest_budget // n)
    # Les fenetres sont reparties de facon a ce que la derniere colle exactement a la fin de
    # `remaining` : sinon la toute fin du document n'est jamais echantillonnee.
    span = max(1, len(remaining) - win)
    for i in range(n):
        start = (span * i) // max(1, n - 1) if n > 1 else 0
        parts.append("\n[...]\n" + remaining[start:start + win])
    return "".join(parts)


def _split_sections(markdown: str, section_chars: int = 8000,
                    overlap: int | None = None) -> list[str]:
    # Levier A : decoupe le markdown en fenetres de `section_chars` caracteres avec un
    # RECOUVREMENT (overlap) entre fenetres consecutives, comme un chunking RAG. Le recouvrement
    # evite de perdre une evidence a cheval sur une frontiere : un critere dont la preuve tombe
    # au bord d'une section reste visible en entier dans la fenetre voisine.
    # Couverture 100% par UNION (chaque caractere est dans au moins une section). Chaque section
    # fait au plus `section_chars` caracteres. Overlap par defaut = 10% de section_chars (usuel
    # en RAG) ; overlap=0 redonne des fenetres jointives. Markdown vide -> aucune section.
    if not markdown:
        return []
    size = max(1, int(section_chars))
    ov = size // 10 if overlap is None else int(overlap)
    ov = min(max(0, ov), size - 1)  # 0 <= overlap < size (sinon aucune progression)
    stride = size - ov
    sections, i, n = [], 0, len(markdown)
    while i < n:
        sections.append(markdown[i:i + size])
        if i + size >= n:
            break
        i += stride
    return sections


def _batch_prompt(section_text: str, crits, h_signals: dict, scale_max: int) -> str:
    lignes = []
    for c in crits:
        hint = h_signals.get(c.id)
        suffixe = f" (signal deterministe: {hint})" if hint is not None else ""
        lignes.append(f"- {c.id} : {c.label}{suffixe}")
    liste = "\n".join(lignes)
    return (
        "Tu evalues la qualite d'une SECTION d'un document pour un systeme RAG.\n"
        f"Echelle 1 a {scale_max} (au milieu = partiellement satisfaisant).\n"
        "Evalue CHACUN des criteres suivants pour CETTE section:\n"
        f"{liste}\n\n"
        "Si tu ne peux pas evaluer un critere de facon fiable sur cette section, mets son "
        "status a not_evaluated. Ne devine jamais une note.\n"
        "Reponds en JSON: un objet dont chaque cle est un id de critere et chaque valeur "
        "{status: scored|not_evaluated, score: 1-" + str(scale_max) + " ou null, "
        "justification: une phrase, evidence: citation/section ou null}.\n\n"
        f"Contenu de la section:\n{section_text}"
    )


def _valid_scored(status, score, justification, scale_max) -> bool:
    # Anti-fabrication : la SEULE voie vers "scored" est une note entiere valide dans le
    # bareme AVEC justification non vide. Predicat partage entre sections et resultat agrege.
    return (
        status == "scored"
        and isinstance(score, int) and not isinstance(score, bool)
        and 1 <= score <= scale_max
        and bool(justification)
    )


def _aggregate(responses: list[dict], scale_max: int):
    # Regle d'agregation inter-sections (levier A) :
    #   - Une section "note" un critere UNIQUEMENT si sa reponse passe l'anti-fabrication
    #     (status=scored, note entiere dans le bareme, justification non vide). Les autres
    #     sections (not_evaluated, hors bareme, justification vide, critere absent) sont ignorees.
    #   - Le score du document = MEDIANE des notes des sections qui ont note (robuste aux
    #     sections aberrantes). La mediane a nombre pair est arrondie a l'entier le plus proche.
    #   - Justification et evidence retenues = celles de la section dont la note est la plus
    #     proche de la mediane (ex aequo -> section la plus en amont).
    #   - Aucune section conforme -> not_evaluated (jamais de note devinee).
    # La validation anti-fabrication est re-appliquee au resultat agrege (ceinture + bretelles).
    valides = []  # (score, justification, evidence) des sections conformes, dans l'ordre
    for r in responses:
        if not isinstance(r, dict):
            continue
        status = r.get("status")
        score = r.get("score") if status == "scored" else None
        justification = (r.get("justification") or "").strip()
        if _valid_scored(status, score, justification, scale_max):
            valides.append((score, justification, r.get("evidence")))
    if not valides:
        return "not_evaluated", None, "Non evalue: aucune section n'a produit de note conforme.", None
    med = statistics.median([v[0] for v in valides])
    proche = min(valides, key=lambda v: abs(v[0] - med))
    score = int(round(med))
    justification = proche[1]
    if not _valid_scored("scored", score, justification, scale_max):
        # Ne devrait pas arriver (la mediane de notes valides est dans le bareme) : filet ultime.
        return "not_evaluated", None, "Non evalue: agregat non conforme.", None
    return "scored", score, justification, proche[2]


def score_document(doc: ParsedDoc, reg: Registry, metrics: dict,
                   llm: LLMClient, config_hash: str, max_doc_chars: int = 24000,
                   section_chars: int = 8000, section_overlap: int | None = None,
                   skip_llm: bool = False) -> list[CriterionScore]:
    # Integration leviers A + C :
    #   - section_chars / section_overlap (levier A) : couverture 100% du document par sections
    #     batchees avec recouvrement facon chunking RAG (overlap None -> 10% de section_chars).
    #   - skip_llm (levier C, route light) : conserve na et les scoreurs deterministes mais
    #     n'appelle AUCUN LLM (ni judge_batch). Les criteres qualitatifs deviennent
    #     not_evaluated (anti-fabrication : jamais de note devinee) et le document est flague
    #     en amont (cli). Un doc route light ne paie donc aucun appel de jugement.
    na = set(metrics.get("na", []))
    d_scores = metrics.get("d_scores", {})
    h_signals = metrics.get("h_signals", {})

    # Criteres a juger par le LLM : tout ce qui n'est ni na, ni external_dep, ni un critere D
    # deja resolu par un signal deterministe. (Perimetre LLM identique a la baseline, mais juge
    # par sections batchees au lieu d'un appel par critere.)
    qualitatifs = [c for c in reg.criteria
                   if c.id not in na and not c.external_dep
                   and not (c.tag == "D" and c.id in d_scores)]

    # Levier A : couverture 100% du document par sections ; UN appel judge_batch par section
    # couvre tous les criteres qualitatifs. Cout LLM/doc = nombre de sections.
    par_critere: dict[str, list[dict]] = {c.id: [] for c in qualitatifs}
    if qualitatifs and not skip_llm:
        for sec in _split_sections(doc.markdown, section_chars, section_overlap):
            resp = llm.judge_batch(_batch_prompt(sec, qualitatifs, h_signals, reg.scale_max),
                                   _BATCH_SCHEMA) or {}
            for c in qualitatifs:
                r = resp.get(c.id)
                if isinstance(r, dict):
                    par_critere[c.id].append(r)

    out: list[CriterionScore] = []
    for crit in reg.criteria:
        base = dict(id=crit.id, tag=crit.tag, weight=crit.weight)
        if crit.id in na:
            out.append(CriterionScore(**base, status="na", score=None,
                                      justification="Objet absent du document (inventaire).",
                                      evidence=None))
            continue
        if crit.external_dep:
            out.append(CriterionScore(**base, status="not_evaluated", score=None,
                                      justification="Referentiel de questions/cas d'usage absent.",
                                      evidence=None))
            continue
        if crit.tag == "D" and crit.id in d_scores:
            out.append(CriterionScore(**base, status="scored", score=int(d_scores[crit.id]),
                                      justification="Signal deterministe.", evidence=None))
            continue
        if skip_llm:
            # Levier C, route light : aucun appel LLM, critere qualitatif non evalue (flague).
            out.append(CriterionScore(**base, status="not_evaluated", score=None,
                                      justification="Route light (crible) : jugement LLM non execute.",
                                      evidence=None))
            continue
        # Levier A : agregation inter-sections du jugement batche (anti-fabrication re-appliquee).
        status, score, justification, evidence = _aggregate(par_critere.get(crit.id, []),
                                                            reg.scale_max)
        out.append(CriterionScore(**base, status=status, score=score,
                                  justification=justification, evidence=evidence))
    return out
