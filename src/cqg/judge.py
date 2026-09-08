# src/cqg/judge.py
import statistics

from .models import CriterionScore, ParsedDoc
from .registry.loader import Registry
from .llm.base import LLMClient

_SCHEMA = {"type": "object", "required": ["status", "justification"]}
_BATCH_SCHEMA = {"type": "object"}


def _representative_excerpt(markdown: str, budget: int = 24000) -> str:
    # Kept for compatibility (baseline) : sampling of a representative excerpt.
    # Lever A no longer uses it (100% coverage through sections), but the function is still
    # used by the baseline test suite.
    budget = max(int(budget), 0)
    if budget == 0:
        return ""
    if len(markdown) <= budget:
        return markdown
    head = int(budget * 0.5)
    rest_budget = budget - head
    parts = [markdown[:head]]
    remaining = markdown[head:]
    n = 4  # number of distributed windows
    win = max(1, rest_budget // n)
    # The windows are distributed so that the last one lands exactly at the end of
    # `remaining` : otherwise the very end of the document is never sampled.
    span = max(1, len(remaining) - win)
    for i in range(n):
        start = (span * i) // max(1, n - 1) if n > 1 else 0
        parts.append("\n[...]\n" + remaining[start:start + win])
    return "".join(parts)


def _split_sections(markdown: str, section_chars: int = 8000,
                    overlap: int | None = None) -> list[str]:
    # Lever A : splits the markdown into windows of `section_chars` characters with an
    # OVERLAP between consecutive windows, like RAG chunking. The overlap
    # avoids losing evidence straddling a boundary : a criterion whose evidence falls
    # at the edge of a section stays fully visible in the neighbouring window.
    # 100% coverage by UNION (every character is in at least one section). Each section
    # is at most `section_chars` characters. Default overlap = 10% of section_chars (usual
    # in RAG) ; overlap=0 gives back adjoining windows. Empty markdown -> no section.
    if not markdown:
        return []
    size = max(1, int(section_chars))
    ov = size // 10 if overlap is None else int(overlap)
    ov = min(max(0, ov), size - 1)  # 0 <= overlap < size (otherwise no progression)
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
    # Anti-fabrication : the ONLY path to "scored" is a valid integer score within the
    # scale WITH a non-empty justification. Predicate shared by sections and aggregated result.
    return (
        status == "scored"
        and isinstance(score, int) and not isinstance(score, bool)
        and 1 <= score <= scale_max
        and bool(justification)
    )


def _aggregate(responses: list[dict], scale_max: int):
    # Cross-section aggregation rule (lever A) :
    #   - A section "scores" a criterion ONLY if its response passes anti-fabrication
    #     (status=scored, integer score within the scale, non-empty justification). The other
    #     sections (not_evaluated, out of scale, empty justification, criterion absent) are ignored.
    #   - The document score = MEDIAN of the scores of the sections that scored (robust to
    #     outlier sections). An even-count median is rounded to the nearest integer.
    #   - Justification and evidence retained = those of the section whose score is the
    #     closest to the median (tie -> earliest section).
    #   - No compliant section -> not_evaluated (never a guessed score).
    # Anti-fabrication validation is re-applied to the aggregated result (belt + braces).
    valides = []  # (score, justification, evidence) of compliant sections, in order
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
        # Should not happen (the median of valid scores is within the scale) : ultimate safety net.
        return "not_evaluated", None, "Non evalue: agregat non conforme.", None
    return "scored", score, justification, proche[2]


def score_document(doc: ParsedDoc, reg: Registry, metrics: dict,
                   llm: LLMClient, config_hash: str, max_doc_chars: int = 24000,
                   section_chars: int = 8000, section_overlap: int | None = None,
                   skip_llm: bool = False) -> list[CriterionScore]:
    # Integration of levers A + C :
    #   - section_chars / section_overlap (lever A) : 100% coverage of the document by batched
    #     sections with overlap in the style of RAG chunking (overlap None -> 10% of section_chars).
    #   - skip_llm (lever C, light route) : keeps na and the deterministic scorers but
    #     calls NO LLM (not even judge_batch). Qualitative criteria become
    #     not_evaluated (anti-fabrication : never a guessed score) and the document is flagged
    #     upstream (cli). A light-route doc therefore pays for no judgment call.
    na = set(metrics.get("na", []))
    d_scores = metrics.get("d_scores", {})
    h_signals = metrics.get("h_signals", {})

    # Criteria to be judged by the LLM : everything that is neither na, nor external_dep, nor a D
    # criterion already resolved by a deterministic signal. (LLM scope identical to the baseline, but judged
    # by batched sections instead of one call per criterion.)
    qualitatifs = [c for c in reg.criteria
                   if c.id not in na and not c.external_dep
                   and not (c.tag == "D" and c.id in d_scores)]

    # Lever A : 100% coverage of the document by sections ; ONE judge_batch call per section
    # covers all the qualitative criteria. LLM cost/doc = number of sections.
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
            # Lever C, light route : no LLM call, qualitative criterion not evaluated (flagged).
            out.append(CriterionScore(**base, status="not_evaluated", score=None,
                                      justification="Route light (crible) : jugement LLM non execute.",
                                      evidence=None))
            continue
        # Lever A : cross-section aggregation of the batched judgment (anti-fabrication re-applied).
        status, score, justification, evidence = _aggregate(par_critere.get(crit.id, []),
                                                            reg.scale_max)
        out.append(CriterionScore(**base, status=status, score=score,
                                  justification=justification, evidence=evidence))
    return out
