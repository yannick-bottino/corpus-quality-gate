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


# Au-dela de ce volume, un document est "gros" : le TTR global y devient un artefact de
# longueur (le vocabulaire sature) et le raccourci "signaux propres" n'a plus de sens.
LARGE_DOC_TOKENS = 10_000


def screen_document(doc: ParsedDoc, metrics: dict) -> dict:
    s = metrics.get("signals", {})
    non_alpha = s.get("non_alpha_fraction", 0.0)
    dup = s.get("duplicate_line_fraction", 0.0)
    ttr = s.get("type_token_ratio", 1.0)
    # TTR normalise par fenetre : robuste a la longueur, contrairement au TTR global.
    # Fallback sur le TTR global s'il est absent (compat. appels/tests historiques).
    mattr = s.get("mattr", ttr)
    n_tokens = s.get("n_tokens", 0)
    pc = doc.parse_confidence
    # NB : block_integrity n'est PAS un signal de degradation ici. Il mesure la part de
    # blocs texte parmi tous les blocs, or les docs riches en images/tableaux ont
    # beaucoup de blocs typees vides (image/table) : block_integrity bas y est normal,
    # pas une degradation. L'utiliser comme crible route a tort tout doc illustre en light.

    # Garde-fou metadonnees. Le TTR global chute mecaniquement avec la longueur : un gros
    # document (ex. "Le Cahier Ma Sante", 222 pages, ttr global=0.0042) au vocabulaire
    # pourtant sain serait ecarte du jugement LLM par ce seul artefact. On exige donc, pour
    # un gros document, la concordance de plusieurs signaux avant tout declassement : tant
    # que l'extraction est saine (confiance de parsing correcte, non_alpha raisonnable, TTR
    # *fenetre* sain), le document est juge sur le fond ("full"). Cela court-circuite aussi
    # le raccourci "signaux propres" (qui saute le jugement) : un gros doc merite un jugement
    # complet. Un gros document REELLEMENT degrade a un TTR fenetre bas et retombe plus bas.
    extraction_saine = pc >= 0.5 and non_alpha <= 0.40 and mattr >= 0.05
    if n_tokens >= LARGE_DOC_TOKENS and extraction_saine:
        return {"route": "full",
                "reasons": [f"gros_document_extraction_saine (n_tokens={n_tokens}, "
                            f"parse_confidence={pc}, non_alpha={non_alpha}, mattr={mattr})"]}

    # Extraction degradee -> flag direct, pas de jugement complet. Signaux fiables :
    # confiance de parsing basse (cf. levier E), fraction non-alpha elevee (jetons cid,
    # symboles), vocabulaire quasi nul (texte repete/illisible). On s'appuie sur le TTR
    # *fenetre* (mattr) et non sur le TTR global, pour ne pas confondre "document long" et
    # "vocabulaire quasi nul".
    if pc < 0.5 or non_alpha > 0.40 or mattr < 0.05:
        return {"route": "light",
                "reasons": [f"extraction_degradee (parse_confidence={pc}, "
                            f"non_alpha={non_alpha}, mattr={mattr})"]}

    # Tous les signaux au vert -> document manifestement propre, jugement reduit.
    if non_alpha < 0.30 and dup < 0.15 and mattr > 0.15:
        return {"route": "light", "reasons": ["signaux_propres"]}

    return {"route": "full", "reasons": ["cas_limite"]}
