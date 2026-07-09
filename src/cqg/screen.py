"""Levier C : triage a deux vitesses.

Crible deterministe qui route chaque document AVANT le jugement LLM couteux :
- extraction degradee (non_alpha eleve, confiance de parsing basse, vocabulaire quasi nul)
  -> route "light" : on flague pour revue humaine sans depenser ~45 appels LLM sur du
  texte illisible.
- document manifestement propre (tous les signaux au vert) -> route "light" : jugement
  LLM reduit, on fait confiance aux signaux deterministes.
- cas limite -> route "full" : jugement LLM complet.

Score-and-flag, human-in-the-loop : "light" ne supprime jamais, il oriente et flague.
"""
from .models import ParsedDoc


def screen_document(doc: ParsedDoc, metrics: dict) -> dict:
    s = metrics.get("signals", {})
    non_alpha = s.get("non_alpha_fraction", 0.0)
    dup = s.get("duplicate_line_fraction", 0.0)
    ttr = s.get("type_token_ratio", 1.0)
    pc = doc.parse_confidence
    # NB : block_integrity n'est PAS un signal de degradation ici. Il mesure la part de
    # blocs texte parmi tous les blocs, or les docs riches en images/tableaux ont
    # beaucoup de blocs typees vides (image/table) : block_integrity bas y est normal,
    # pas une degradation. L'utiliser comme crible route a tort tout doc illustre en light.

    # Extraction degradee -> flag direct, pas de jugement complet. Signaux fiables :
    # confiance de parsing basse (cf. levier E), fraction non-alpha elevee (jetons cid,
    # symboles), vocabulaire quasi nul (texte repete/illisible).
    if pc < 0.5 or non_alpha > 0.40 or ttr < 0.05:
        return {"route": "light",
                "reasons": [f"extraction_degradee (parse_confidence={pc}, "
                            f"non_alpha={non_alpha}, ttr={ttr})"]}

    # Tous les signaux au vert -> document manifestement propre, jugement reduit.
    if non_alpha < 0.30 and dup < 0.15 and ttr > 0.15:
        return {"route": "light", "reasons": ["signaux_propres"]}

    return {"route": "full", "reasons": ["cas_limite"]}
