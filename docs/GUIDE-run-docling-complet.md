# Guide — exécuter le parsing Docling complet + couverture LLM

Tout est intégré et testé (123 tests). Ce qui suit permet de lancer le run **complet**
(222 pages) + le jugement LLM de fond (critère 3b du handoff) — idéalement sur une machine
**≥ 8 Go de RAM** (le bac à sable d'origine, ~1,2 Go, ne peut faire tourner Docling qu'à
batch=1 et tue les runs > ~2 min).

## Pré-requis (déjà faits dans ce dépôt, à refaire ailleurs)
```bash
cd corpus-quality-gate
export VIRTUAL_ENV="$PWD/.venv"
uv pip install --python .venv/bin/python "torch==2.13.0" "torchvision==0.28.0" \
    --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/bin/python opencv-python-headless   # serveur headless : évite libGL.so.1
uv pip install --python .venv/bin/python -e ".[dev]"              # docling est désormais dep cœur
```

## 1. Régler la taille de lot selon la RAM
`config/config.claude_cli.yaml` → `parsing.docling_batch_pages` :
- **1** (défaut) : ~1,1 Go de pic, sûr sous ~1,2 Go, mais lent (~37 min / 222 p, rechargement modèles par page).
- **10–20** sur machine ≥ 8 Go : bien plus rapide (un seul chargement de modèles par lot).
Repère mesuré : 1 p = 1092 Mo, 5 p = 1708 Mo, 10 p = 1625 Mo (frais). Prendre une marge.

## 2. Lancer le pipeline complet (parsing Docling + jugement LLM sans clé API)
```bash
cd corpus-quality-gate && . .venv/bin/activate
python main.py run ../test_data --config config/config.claude_cli.yaml --out ../outputs/run_docling
```
- `parser: docling` est déjà le défaut dans cette config → le parsing utilise Docling
  (sous-processus par lot, repli pdfminer par page si un lot OOM).
- Le jugement de fond est délégué au CLI `claude` (provider `claude_cli`, ~0,30 $/appel,
  ~45 appels). Le triage corrigé route « Le Cahier Ma Santé » en **full** → il est bien jugé.

## 3. Vérifier le résultat
```bash
# Le doc cible doit être jugé (n_calls > 0, couverture > 0), pas "screen:light"
cat "../outputs/run_docling/Le Cahier Ma Santé (AGA - AEP).score.json"
cat ../outputs/run_docling/cost.json          # n_calls par doc
```
Critère 3b satisfait si `coverage_pct > 0` et `n_calls > 0` sur le doc cible.

## 4. Mesurer la qualité d'extraction (harnais autoresearch)
```bash
python outputs/autoresearch/verify_parse_quality.py docling   # assoc libellé→valeur (attendu ~83%)
python outputs/autoresearch/verify_parse_quality.py legacy    # baseline (~37%)
```

## Itération suivante recommandée (autoresearch #2)
Câbler la stratégie gagnante **Docling + complétude pdfminer** (100 % de recall des valeurs ;
récupère `145/200/220/400 %`) comme mode de parser, puis relancer `verify_parse_quality.py`.
Voir `outputs/autoresearch/README.md` (Goal/Metric/Verify) et `benchmark-docling-cahier-ma-sante.md`.

## Rappel des faits mesurés
- Docling : association libellé→valeur **37 % → 83 %** ; sortie en tables Markdown structurées.
- Faiblesse Docling seul : perd quelques valeurs (`55/145/200/220/400 %`) → corrigée par le merge.
- Le parser legacy (pdfminer) reste disponible (`parsing.parser: legacy`) comme repli léger.
