"""Tests du levier C : triage a deux vitesses (crible deterministe -> full | light)."""
from cqg.screen import screen_document
from cqg.models import ParsedDoc, Block


def _doc(pc=0.9):
    return ParsedDoc(doc_id="d", markdown="x", blocks=[Block(kind="text", text="x")],
                     parse_confidence=pc)


def _metrics(non_alpha=0.25, dup=0.1, ttr=0.2, bi=0.95):
    return {"signals": {"non_alpha_fraction": non_alpha, "duplicate_line_fraction": dup,
                        "type_token_ratio": ttr, "block_integrity": bi}}


def test_degraded_extraction_routes_light_without_full_judge():
    # Extraction degradee (cas CG Auto : non_alpha eleve) -> flag direct, pas de jugement complet.
    res = screen_document(_doc(), _metrics(non_alpha=0.47, ttr=0.04))
    assert res["route"] == "light"
    assert any("degrad" in r for r in res["reasons"])


def test_low_parse_confidence_routes_light():
    res = screen_document(_doc(pc=0.35), _metrics())
    assert res["route"] == "light"


def test_clean_document_routes_light():
    res = screen_document(_doc(), _metrics(non_alpha=0.22, dup=0.05, ttr=0.30, bi=0.95))
    assert res["route"] == "light"
    assert any("propre" in r for r in res["reasons"])


def test_borderline_document_routes_full():
    # Ni degrade ni manifestement propre (doublons eleves) -> jugement complet.
    res = screen_document(_doc(), _metrics(non_alpha=0.26, dup=0.26, ttr=0.17, bi=0.9))
    assert res["route"] == "full"


def test_image_rich_low_block_integrity_not_flagged_degraded():
    # Regression : un doc riche en images (block_integrity bas) mais au texte correct
    # NE doit PAS etre route light-degrade. block_integrity ne pilote pas le crible.
    res = screen_document(_doc(pc=0.7), _metrics(non_alpha=0.27, dup=0.2, ttr=0.16, bi=0.13))
    assert res["route"] == "full"


def test_large_healthy_doc_routes_full_despite_low_global_ttr():
    # Cas "Le Cahier Ma Sante" : 222 pages, TTR global ecrase par la longueur (0.0042)
    # mais extraction SAINE (parse_confidence, non_alpha, TTR fenetre tous au vert).
    # Garde-fou metadonnees : un gros document sain doit etre juge sur le fond (route
    # "full"), jamais ecarte du jugement LLM sur le seul artefact du TTR global.
    metrics = {"signals": {"non_alpha_fraction": 0.2298, "duplicate_line_fraction": 0.30,
                           "type_token_ratio": 0.0042, "mattr": 0.1725, "n_tokens": 227792,
                           "block_integrity": 0.5}}
    res = screen_document(_doc(pc=0.747), metrics)
    assert res["route"] == "full"
    assert any("gros_document" in r for r in res["reasons"])


def test_large_but_genuinely_degraded_doc_still_routes_light():
    # Garde-fou : le garde-fou metadonnees ne doit PAS sur-declencher. Un gros document
    # REELLEMENT degrade (TTR fenetre effondre lui aussi) reste flague en light.
    metrics = {"signals": {"non_alpha_fraction": 0.20, "duplicate_line_fraction": 0.30,
                           "type_token_ratio": 0.001, "mattr": 0.02, "n_tokens": 227792,
                           "block_integrity": 0.5}}
    res = screen_document(_doc(pc=0.7), metrics)
    assert res["route"] == "light"
    assert any("degrad" in r for r in res["reasons"])
