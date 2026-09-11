# Plan d'implémentation — 2 features Corpus Quality Gate

Issu du grilling du 2026-09-11. 26 décisions arbitrées, frontière vide.
**Statut : EN ATTENTE DE VALIDATION — aucune ligne de code ecrite.**

Méthode d'exécution retenue : **subagent-driven development + TDD** (test rouge, puis
implémentation, puis revue). Un sous-agent = une tache du plan, avec brief structuré
(objectif / contraintes / fichiers d'entrée / format de sortie).

---

## Feature 1 — Parsing à deux chemins (déterministe ou LLM)

**Besoin.** Poser les documents bruts dans `raw_input/`, récupérer les documents parsés
dans `parsed_input/`. Deux chemins de parsing au choix, même entrée, même sortie ; seule
la manière de parser change.

**Conséquence structurante.** `run` devient une étape de **scoring pur** : elle ne touche
plus jamais au fichier source. L'enrichissement image -> texte descend dans `parse`,
puisque `parsed_input/` doit contenir « le document tel qu'il sera ingéré en RAG ».

## Feature 2 — Grille de critères paramétrable par Excel

**Besoin.** L'équipe Data Management pilote les tests joués depuis un classeur Excel
(quels tests, pourquoi, ce qu'on évalue), et le détail des tests s'adapte tout seul,
qu'ils soient déterministes, cognitifs ou hybrides.

**Conséquence structurante.** L'appel LLM a lieu à la **compilation**, pas au run :
`registry_fingerprint()` hache les octets du fichier de grille, donc un registre
regénéré a chaque run rendrait tous les rapports incomparables entre eux.

---

## Décisions arbitrées

### Architecture du parsing

| # | Décision |
|---|---|
| Q1 | Nouvelle sous-commande `cqg parse <raw> --out <parsed>`. `run` et `golden` acceptent **soit** un dossier brut (parsing à la volée, comportement actuel) **soit** un `parsed_input/` (scoring pur). `main()` passe à `choices=["parse", "run", "golden"]`. |
| Q2 | `parsed_input/` contient `<doc>.md` (éditable à la main) **+** `<doc>.parse.json` (sidecar : `blocks`, `parse_confidence`, `images`, provenance). Sans le sidecar, `na_decisions` verrait zéro bloc et les critères 3.1-3.6/3.8/3.9 basculeraient en `na` : le score changerait pour une raison étrangère à la qualité du document. |
| Q9 | L'enrichissement VLM descend dans `cqg parse`. Sur le chemin LLM, `_typing_pdfplumber` tourne **en parallele** pour fournir typage et coordonnées d'images — même motif que `_docling_extraction`. Aucune géométrie n'est jamais inventée (précédent `_direct_extraction` pour docx/pptx). |
| Q11 | `cqg parse` saute un document déjà présent (sauf `--force`). Le sidecar stocke le hash du markdown : si le `.md` a été édité à la main, `run` recalcule les blocs depuis le markdown et pose un flag `manually_edited`. L'édition humaine est un cas de première classe. |
| Q12 | Le parser LLM s'applique au **PDF uniquement**. `.docx`/`.pptx`/`.txt`/`.md` gardent leurs extracteurs directs (python-docx lit la vraie structure : passer par un LLM ne peut que dégrader), avec une ligne de provenance qui le dit. |
| Q24 | **Arbitré → Q24(b).** `--enrich` est disponible sur `cqg parse` ET reste actif sur `run` **quand on lui passe un dossier brut** (il parse, donc il peut enrichir). Sur un `parsed_input/` l'option est sans objet : avertissement explicite. Les commandes e2e existantes continuent de marcher à l'identique, et le test de non-régression du lot 1 couvre enrichi et non enrichi en une seule comparaison. |

### Parsing LLM et anti-fabrication

| # | Décision |
|---|---|
| Q3 | PDF natif quand le provider le supporte, **repli sur rendu page → image** sinon. Batching par lots de pages calqué sur `_DOCLING_BATCH_PAGES` (le corpus de test contient un document de 222 pages). |
| Q4 | `parse_confidence` du chemin LLM = **contrôle croisé** contre une extraction pdfminer bon marché (taux de recouvrement / divergence). Un score de confiance auto-déclaré par le modèle qui vient de fabriquer le texte n'est pas une preuve. Motif : `cid_failure_fraction` est aveugle sur ce chemin — un LLM n'emet jamais de `(cid:NNN)`, il comble le trou en inventant, et tous les garde-fous passent au vert (cas « CG Auto à 0.947 »). |
| Q10 | Divergence au-dessus du seuil → **flag seul** (`llm_parse_divergence`) + `parse_confidence` abaissée. Pas de repli automatique : ce serait prendre une décision qualité à la place de l'humain, et c'est contre-productif (on choisit le LLM justement quand le parser déterministe échoue). |

### Providers LLM

| # | Décision |
|---|---|
| Q8/Q16 | Nouveau provider **`openai_compatible`** (`base_url` + `api_key_env` + `model` + `api_version`). Cible pressentie : tenant Azure AXA exposant OpenAI, Claude et Mistral. Specs non disponibles à ce jour → livraison d'un `config/config.axa.yaml` à trous documentant les deux routes (déploiement OpenAI classique via `azure_openai` ; modèles tiers via la route d'inférence compatible). |
| Q25bis | **Arbitré → option (i) complétée.** Le provider et le modèle **résolus** entrent dans `config_hash` : deux runs notés par des modèles différents cessent d'être déclarés comparables. **Et** ils deviennent visibles — champ `resolved_provider` dans chaque `<doc>.score.json`, colonne `modele_evaluateur` dans l'onglet `Synthese` et dans `synthese.csv`. Motif : un hash dit « différent », jamais « pourquoi ». Le hash contraint, la colonne explique ; sans elle, on produit des rapports qui refusent de se comparer sans le dire, et les gens contournent l'outil. |
| Q17 | Chaîne de repli **ordonnée et déclarative** : `llm: { chain: [...] }`. Résolue **une seule fois au démarrage** (clé présente ? binaire `claude` présent ?), tracée dans `cost.json` et dans la provenance du sidecar. Une erreur en cours de run ne bascule **jamais** de provider : un rapport dont la moitié des documents est notée par un autre modèle est incomparable en interne, et `config_hash` ne le verrait pas (il hache la config, pas ce qui s'est passé). |
| Q18 | Repli sans clé = `claude_cli`. Fait vérifié : `ClaudeCLILLM` n'implémente pas `describe_image` (il hérite du `NotImplementedError` de la base) — donc ni vision ni parsing LLM en l'état. Solution retenue : **passer le chemin du fichier dans le prompt** et laisser le CLI le lire lui-même (un seul mécanisme couvre parsing PDF et description d'image, sans clé ni base64). Si le CLI est absent : erreur explicite et repli sur Docling. Le mock est formellement exclu — il injecterait du texte fabriqué dans le markdown qui sert de base à la notation. Réserve tracée dans la provenance : le CLI est un agent, moins déterministe qu'un endpoint. |

### Grille Excel

| # | Décision |
|---|---|
| Q5 | **Compilation** : `cqg criteria compile grille.xlsx`. L'appel LLM a lieu là, une fois, et produit un YAML lisible et versionnable. Les runs ne font plus jamais d'appel LLM sur la grille. |
| Q6 | Un critère « Automatique » que l'outil ne sait pas implémenter est **re-taggé explicitement** en IA ou Mixte, avec motif, remonté dans le rapport. Piège réel évité : le périmètre LLM de `judge.py` est `not (c.tag == "D" and c.id in d_scores)` — un critère taggé `D` sans entrée dans `d_scores` tombe **silencieusement** dans le prompt LLM et se fait noter comme qualitatif, sans que `_valid_scored` ne l'attrape. |
| Q7 | **Non-régression stricte** : les 57 critères actuels passés par le chemin Excel → YAML doivent redonner exactement les scores actuels. Force le schéma Excel à être un sur-ensemble sans perte de `Criterion`. |
| Q13 | Classeur à **3 feuilles** : `Critères` (une ligne = un test), `Dimensions` (noms, poids, échelle), `Lexique` (référence en lecture seule). Template livré : [`config/criteres/grille_template.xlsx`](../config/criteres/grille_template.xlsx). |
| Q14 | La colonne `intention` est **injectée dans le prompt du juge** quand elle est renseignée. Intention vide = prompt strictement identique à aujourd'hui, donc la non-régression Q7 tient. |
| Q15 | **Blocage conditionnel** : la grille compilée est bloquée uniquement si l'outil a pris au moins une décision non triviale à la place d'un humain (re-tag, désactivation, correction de valeur). Sinon, utilisable immédiatement. Évite la cérémonie que l'équipe contournerait au bout de deux semaines. |
| Q19 | **5 mesures automatiques v1** : rechercher une mention / exiger deux mentions / comparer à un seuil / compter des occurrences / mesurer une proportion. Elles re-couvrent 100 % des 8 règles déterministes actuelles — condition de la non-régression Q7. |
| Q20 | Rapport de compilation en **Excel**, onglet `Rapport` d'une **copie** (`grille_compilee.xlsx`), jamais dans le fichier source de l'équipe. Format Excel parce que c'est celui dans lequel l'équipe travaille. Le rapport nomme **la mesure retenue ET ses paramètres, en clair** — sans les paramètres, un référent métier ne peut pas repérer le cas où le compilateur a choisi la bonne famille de mesure mais le mauvais motif. |
| Q21 | `config/criteres/grille.xlsx` (source) → `config/criteres/criteria_registry.yaml` (artefact versionné, relu en diff Git). `src/cqg/registry/criteria_registry.yaml` **reste le défaut livré** ; la config pointe ailleurs via `registry.path`. |
| Q23 | **Vocabulaire métier côté Excel, codes techniques côté YAML.** L'équipe lit « Automatique / Analysé par l'IA / Mixte / Au choix de l'outil » et « Rechercher une mention » ; le compilateur traduit en `D`/`H`/`L` et `presence_motif`. Contrainte de vulgarisation : lisible par l'équipe DMO **et** par des référents métier, sans jargon. |

### Instrumentation

| # | Décision |
|---|---|
| Q22 | `cost.json` gagne des rubriques séparées : `judge` (n_calls, prompt_chars), `parse` (n_calls, pages traitées), `enrich` (n_images). Le parsing LLM page par page est le poste le plus cher du pipeline ; c'est le chiffre qui tranchera entre les deux chemins. |

---

## Réserves — TRANCHÉES le 2026-09-11

### R1 — résolu : bascule sur Q24(b)

`--enrich` reste actif sur `run <dossier_brut>`. Ferme les deux problèmes d'un coup :
compatibilité des commandes e2e existantes, et existence d'un `run` direct produisant du
markdown enrichi auquel comparer le chemin `parse` + `run` dans le test de non-régression.

### R2 — résolu : provider résolu dans le hash, ET visible dans le rapport

Voir la ligne Q25bis du tableau « Providers LLM ».

**Note de migration à écrire dans le README.** `_NON_SCORING_SECTIONS = {"paths"}` : tout
le reste de la config entre dans l'empreinte. Ajouter `llm.chain` (lot 2), `registry.path`
(lot 3) et le provider résolu (lot 2) **change le hash de toutes les configs existantes** :
les `*.score.json` déjà produits cesseront de matcher. C'est attendu et voulu (la
sur-sensibilité est délibérée, cf. le commentaire de `config.py`), mais ça doit être
annoncé, pas subi.

## Lots de livraison

### Lot 1 — Découplage raw/parsed, **sans aucun LLM**

Le seul lot qui touche le cœur du pipeline existant. Le livrer sans LLM permet de
prouver par les tests que les scores n'ont pas bougé avant d'ajouter de l'incertain.

- [ ] `models.py` : modèle du sidecar (`ParsedDocFile` : markdown_hash, provenance, blocks, images, parse_confidence)
- [ ] `parse_store.py` (nouveau) : écriture/lecture de `parsed_input/`, détection d'édition manuelle
- [ ] Sous-commande `cqg parse` avec les parsers existants (`docling` / `legacy`)
- [ ] Descente de l'enrichissement VLM dans `parse`
- [ ] `run` et `golden` : auto-détection dossier brut vs `parsed_input/`
- [ ] `--force` sur `parse`, flag `manually_edited` sur `run`
- [ ] README + wiki OpenWiki mis à jour

**Fini quand** : `pytest` vert **et** un test de non-régression fait tourner `parse` puis
`run` sur `test_data/`, et compare les `*.score.json` à ceux d'un `run` direct —
**égalité stricte hors `config_hash`**, sur les deux cas (non enrichi et enrichi avec un
VLM mock), R1 ayant tranché vers Q24(b).

### Lot 2 — Chemin de parsing LLM

- [ ] Provider `openai_compatible` + `config/config.axa.yaml` a trous
- [ ] Chaine de repli `llm.chain`, résolue une fois au démarrage, tracée
- [ ] `describe_image` + lecture de fichier par chemin sur `ClaudeCLILLM`
- [ ] Parser LLM : PDF natif, repli rendu page → image, batching par lots
- [ ] `_typing_pdfplumber` en parallèle (blocs + géométrie d'images)
- [ ] Contrôle croisé pdfminer → `parse_confidence` + flag `llm_parse_divergence`
- [ ] `parser: llm` dans la config et `--parser llm` en CLI
- [ ] Rubrique `parse` dans `cost.json`
- [ ] `resolved_provider` dans `DocScore` + colonne `modele_evaluateur` dans `Synthese`/`synthese.csv` (R2)
- [ ] Provider et modèle résolus injectés dans `config_hash` (R2)
- [ ] Note de migration `config_hash` dans le README : `llm.chain` + provider résolu changent l'empreinte de toutes les configs existantes

**Fini quand** : sur un PDF dont le parsing déterministe échoue, le chemin LLM produit un
markdown lisible ; sur un PDF sain, la divergence pdfminer reste sous le seuil ; un test
vérifie que la chaîne de repli se résout **une seule fois** et que le provider retenu
apparaît dans `cost.json`.

### Lot 3 — Grille Excel paramétrable

- [ ] Lecture du classeur 3 feuilles + validation (dimensions sans poids, ids dupliqués, N/A impossible)
- [ ] Bibliothèque des 5 mesures automatiques, paramétrables
- [ ] Compilateur LLM : intention → mesure + paramètres, ou re-tag motivé
- [ ] Génération du YAML + onglet `Rapport` dans `grille_compilee.xlsx`
- [ ] `registry.path` en config, blocage conditionnel (Q15)
- [ ] `declencheur_na` piloté par la donnée — aujourd'hui `inventory.py` code en dur `_IMG = {"3.1","3.2","3.3"}`, `_TAB = {"3.4","3.8","3.9"}` : un nouveau critère `na_possible` hors de ces sets ne pourrait **jamais** être N/A
- [ ] Injection de `intention` dans `_batch_prompt` (vide = prompt inchangé)
- [ ] Export de la grille des 57 critères vers `grille.xlsx`, **dans l'ordre du fichier actuel**
- [ ] Note de migration `config_hash` (R2) : l'ajout de `registry.path` change l'empreinte de toutes les configs existantes

**Fini quand** : la grille des 57 critères exportée en Excel puis recompilée redonne un
YAML fonctionnellement identique à l'actuel — **ordre des critères compris** — et un `run`
sur `test_data/` avec ce YAML redonne les **mêmes scores**.

> **Piège à tester explicitement.** `_batch_prompt` construit ses lignes
> `- {id} : {label}{suffixe}` en itérant `reg.criteria` **dans l'ordre du fichier**. Un
> compilateur qui émet les critères triés autrement (par dimension, ou dans l'ordre des
> lignes Excel) change le texte du prompt, donc les scores. Avec un LLM mock le test
> passerait quand même : c'est exactement l'angle mort. Le compilateur doit émettre dans
> l'ordre de la grille source, et un test doit l'asserter.

---

## Points de vigilance techniques relevés pendant le grilling

- `compute_doc_score` fait `reg.dimension_weights[d]` **sans garde** : le compilateur doit
  valider que chaque dimension citée a un poids, sinon `KeyError` en plein run.
- Le loader ne valide aujourd'hui que l'unicité des ids.
- `parse_document` a **deux** appelants (`run` et `run_golden`) : le lecteur de
  `parsed_input/` doit servir les deux.
- `enrich_document` a besoin du PDF source (`render_image` crop la page) : d'où la
  descente de l'enrichissement dans `parse` (Q9).
- `CountingLLM` exclut explicitement les appels VLM du comptage de jugement : les
  nouvelles rubriques de `cost.json` doivent rester séparées pour ne pas fausser la
  comparaison avec les runs passés.
