# Benchmark parsing — "Le Cahier Ma Santé (AGA - AEP).pdf" (222 pages)

Objectif : préserver les tableaux de garanties comme texte **structuré et récupérable** (RAG).
Environnement : ~1,2 Go RAM libre, sans swap, sans clé API. Docling installé (CPU, ocr=off).

## Ground truth
Valeurs de garanties (montants €, taux %) reconstruites depuis le flux de **caractères**
(propre, vérifié) via `extract_words` position-aware, sur 5 pages échantillon (2, 42, 90,
108, 217). GT = 19 montants distincts + 13 taux distincts.

## Résultat décisif : APLATISSEMENT (association label→valeur détruite)

> Correction (data integrity) : une première version de cette note attribuait au parser
> actuel un taux de "lettres doublées" de 31 % (`HHOonSoPrIaTiArLeIsSATION`). C'était une
> ERREUR de mesure : ce chiffre venait de `pdfplumber.extract_text()`, PAS du parser réel
> (`_pages_text_pdfminer`, pdfminer). Le parser réel n'est **pas** corrompu.

Le vrai défaut est celui diagnostiqué dans le handoff : le parser actuel (pdfminer)
**aplatit les tableaux**. Le texte est propre (cid≈0, lettres doublées = 1,4 %) mais les
colonnes sont sérialisées séparément : tous les libellés d'abord, toutes les valeurs
ensuite. **L'association libellé→valeur est perdue.**

Preuve : dans la sortie du parser actuel, le libellé « Honoraires des médecins » et sa
valeur « 100 % » sont séparés de **17 005 caractères**. En RAG, un chunk contenant le
libellé ne contient pas le taux → la garantie n'est pas récupérable en contexte.

| Candidat | Lettres doublées | Valeurs propres | Association libellé→valeur (RAG) | Verdict |
|---|---|---|---|---|
| **pdfminer (parser actuel)** | 1,4 % | oui (montants + %) | ❌ **détruite** (aplatissement, ~17k car.) | inexploitable en RAG sur tableaux |
| pdfplumber `extract_tables` | — | non (9/19 montants, `3327,,5500 €€`) | ❌ cellules mélangées (grilles A/D) | pire |
| **Docling (ocr=off, tables=on)** | 1,34 % | oui (19/19 montants ; perd `55%`, `000%`) | ✅ **préservée** (Markdown `\| … \|`) | ✅ retenu |

### Preuve visuelle

Parser actuel (pdfminer) — libellés et valeurs séparés (aplatissement) :
```
HOSPITALISATION
Honoraires des médecins
Frais de séjour
   - En établissement conventionné
...   (les taux 100 % correspondants apparaissent ~17 000 caractères plus loin)
```

Docling — association libellé → valeur préservée :
```
| Médicaments à service médical rendu majeur ou important (ex-vignette blanche) | 100 % |
| Médicaments à service médical rendu modéré (ex-vignette bleue)                | 100 % |
```

Sur la grille optique A/D (page 217), Docling récupère **19/19** montants proprement
(`32,50 € 75,00 € 37,50 € 90,00 €…`), structurés en table.

### Nuance honnête sur le gain
Le gain de Docling n'est **pas** "corrige du texte illisible" (le parser actuel est propre)
mais "**préserve la structure table → association libellé/valeur exploitable en RAG**", ce
que l'aplatissement détruit. Contreparties réelles : Docling perd quelques valeurs isolées
(`55%`, `000%`) et duplique certains libellés de lignes adjacentes — faiblesses que
l'orchestration `/autoresearch` doit cibler (ex. compléter Docling par les valeurs pdfminer).

## Passage à l'échelle — plancher mémoire mesuré (décisif)

Pic RSS d'un convert Docling **frais** (process neuf) selon le nombre de pages :

| Pages / convert | Pic RSS | Tient sous 1,2 Go ? |
|---|---|---|
| 1 | **1092 Mo** | ✅ (marge ~110 Mo) |
| 2 | 1249 Mo | ❌ |
| 3 | 1274 Mo | ❌ |
| 5 | 1708 Mo | ❌ |

- Convert du **doc entier** : OOM (SIGKILL).
- Batch à **convertisseur réutilisé** : fuite 1625→2225 Mo sur 100 pages (RAM libérée
  seulement à la sortie du process).
- **Seul batch=1 en sous-processus frais tient** (~1092 Mo). L'empreinte des modèles seule
  est ~1 Go → 2 pages débordent déjà.

**Design retenu (validé par mesure)** : `docling_worker` traite un `page_range` ; `parse.py`
boucle **1 page par sous-processus frais** (batch configurable via `parsing.docling_batch_pages`,
défaut **1** ici), avec **repli pdfminer par page** si un lot OOM (dégradation gracieuse, jamais
de crash). Coût : ~37 min pour 222 pages (rechargement modèles par page). Sur machine ≥8 Go,
augmenter `docling_batch_pages` (ex. 20) pour la vitesse.

## Coût / faisabilité (contrainte 1,2 Go RAM)
- Docling : **pic RSS 1158 Mo** sur 1202 Mo dispo (fits, mais marge quasi nulle, pas de swap).
- ⚠️ **OOM = SIGKILL (137), NON rattrapable par try/except.** Un fallback `try/except → legacy`
  ne couvre PAS l'OOM (le process meurt). Pour un parser par défaut : isoler Docling en
  **sous-processus** (détecter la mort → repli legacy), ou documenter + garder legacy joignable.
- Vitesse : ~8–20 s/page → **~30–60 min** pour les 222 pages.
- `ocr=false` (demandé) allège les deps (pas de moteur OCR) ; vision image = chemin LLM existant.
- Correctifs d'install nécessaires : torch **CPU** + torchvision **+cpu** appariés ;
  `opencv-python-headless` (libGL absent sur serveur headless).

## Métrique autoresearch proposée (Verify → nombre)
Le défaut réel étant l'**aplatissement** (association détruite), la métrique pertinente
mesure l'**adjacence libellé→valeur**, PAS les lettres doublées (parser actuel et Docling
sont à égalité ≈1,4 % là-dessus). `Metric: proportion de paires (libellé de garantie, taux/€)
co-occurrentes dans une fenêtre de N caractères (higher_is_better)`. Le parser aplati score
~0 (séparation ~17k car.) ; Docling score haut (table `\| libellé \| valeur \|`). Complément :
recall de valeurs propres vs GT (Docling ne doit pas régresser en couverture de valeurs).

## Itération autoresearch #1 : combinaison orchestrée (résultat)

Métrique = **adjacence libellé→valeur** (assoc) + **recall de valeurs** (ne pas régresser),
sur les pages échantillon. Baseline pdfminer extraite directement.

| Stratégie | assoc (libellé→valeur) | value_recall | valeurs distinctes |
|---|---|---|---|
| pdfminer (actuel) | 37,3 % | 92,6 % | 25 |
| Docling seul | 82,6 % | 85,2 % | 23 |
| **Docling + merge pdfminer** | **78,7 %** | **100,0 %** | **27** |

- Docling seul **double** l'association (37→83 %) mais **perd 4 valeurs** : `145%, 200%,
  220%, 400%` — précisément les **taux d'hospitalisation** cités dans le handoff (`220%(1)
  400%(1)`). Faiblesse réelle, pas cosmétique.
- **Combinaison gagnante** : Docling en primaire (structure) + passe de complétude des
  valeurs manquantes récupérées du texte pdfminer natif → **100 % de recall** tout en
  gardant une association élevée (78,7 % >> 37,3 %). C'est la stratégie que la boucle
  `/autoresearch` doit retenir et raffiner (itérations suivantes : réduire la duplication
  de libellés Docling, rattacher les valeurs récupérées à leur libellé plutôt qu'en annexe).

Harnais reproductible : `scratchpad/assoc_metric.py` (Verify), `scratchpad/combo.py`
(comparaison de stratégies). Métrique `higher_is_better` sur `assoc`, contrainte
`value_recall == 100 %`.

## Politique existante du repo (à arbitrer)
Docling a été **délibérément retiré** des dépendances `cqg` et verrouillé par 3 tests
(`test_parse_document_no_docling_symbols`, `test_docling_removed_from_declared_deps`,
allowlist de parsers). Cœur volontairement léger (pas de torch/modèles). PyMuPDF banni (AGPL).
