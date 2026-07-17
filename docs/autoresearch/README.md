# Autoresearch — optimisation du parsing des tableaux de garanties

Boucle d'itération autonome (style Karpathy : Goal + métrique mécanique + Verify + boucle
qui garde ce qui améliore) appliquée au parsing de `Le Cahier Ma Santé (AGA - AEP).pdf`.

> `/autoresearch` (repo `uditgoenka/autoresearch`) est un **harnais d'itération**, pas un
> outil PDF. Il n'est pas installé dans cet environnement et sa commande `/autoresearch` ne
> peut pas être invoquée en direct dans une session (les commandes se chargent au démarrage).
> On suit donc son protocole manuellement : Goal / Metric / Verify / boucle.

## Goal
Maximiser l'**exploitabilité RAG** des tableaux de garanties : préserver l'association
libellé→valeur (taux %, montants €), sans perdre de valeurs.

## Métrique (Verify → nombre)
Le vrai défaut du parser historique n'est pas la corruption (texte propre, cid≈0) mais
l'**aplatissement** : les colonnes sont sérialisées séparément, un libellé est séparé de sa
valeur de ~17 000 caractères. La métrique mesure donc l'**adjacence libellé→valeur** :

- `assoc_rate` = % de lignes portant une valeur qui portent AUSSI un libellé (≥2 mots).
  `higher_is_better`. Aplati → ~37 % ; tables structurées → ~83 %.
- Contrainte : `value_recall` ne doit pas régresser (Docling seul perd des valeurs).

Verify : `python outputs/autoresearch/verify_parse_quality.py <parser>`
Fixture rapide : `sample_tables.pdf` (5 pages denses : pages 2/42/90/108/217) — évite de
reparser les 222 pages à chaque itération.

## Invocation type
```
/autoresearch Goal: "maximiser assoc libellé→valeur des tableaux sans perdre de valeurs" \
              Scope: src/cqg/parse.py \
              Metric: "assoc_rate" Direction: higher_is_better \
              Verify: "python outputs/autoresearch/verify_parse_quality.py docling" \
              Guard: ".venv/bin/python -m pytest -q"
```

## Résultats

### Itération #0 — baseline vs Docling (via `parse_document`)
| Parser | assoc | value_recall | distinct |
|---|---|---|---|
| legacy (pdfminer, ancien défaut) | 37,3 % | — | 25 |
| docling (nouveau défaut) | 82,6 % | 85,2 % | 23 |

Docling **double** l'association. Faiblesse : perd `145% 200% 220% 400%` (taux
d'hospitalisation) et duplique des libellés de lignes adjacentes.

### Itération #1 — combinaison orchestrée
| Stratégie | assoc | value_recall | distinct |
|---|---|---|---|
| docling + merge complétude pdfminer | 78,7 % | **100 %** | 27 |

Docling en primaire (structure) + passe de récupération des valeurs manquantes depuis le
texte pdfminer natif → recall 100 % en gardant assoc >> baseline. **C'est la stratégie
cible.** Prochaines itérations : rattacher les valeurs récupérées à leur libellé (plutôt
qu'en annexe) pour remonter l'assoc vers celui de Docling seul ; dédupliquer les libellés.

## État d'intégration
- Docling = **parser par défaut** (`parsing.parser: docling`), isolé en **sous-processus**
  (`src/cqg/docling_worker.py`) : un OOM (SIGKILL, ~1,15 Go sur 1,2 Go) est détecté via le
  returncode et bascule sur `legacy` sans crasher le pipeline.
- `parser: legacy` = repli léger (pdfminer + pdfplumber), conservé et testé.
- La combinaison de l'itération #1 (merge) reste à câbler comme stratégie de parser.

## Fichiers
- `verify_parse_quality.py` — Verify (métrique).
- `sample_tables.pdf` — fixture 5 pages.
- `../benchmark-docling-cahier-ma-sante.md` — benchmark complet (corrigé, honnête).
