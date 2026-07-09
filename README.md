# Corpus Quality Gate (cqg)

Evaluateur de qualite intrinseque de documents AVANT ingestion RAG. Score et flag chaque
document (reference-free, document-level : ni verite terrain ni requetes requises), agrege au
niveau corpus. Principe : **score-and-flag, human-in-the-loop** (rien n'est supprime, tout est
signale pour revue). Corpus cible : PDF numeriques heterogenes et multimodaux, bilingue FR/EN.

## Installation

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows ; sous Unix : source .venv/bin/activate
pip install -e .
```

Python 3.11+. Dependances MIT / Apache-2.0 / BSD uniquement (usage commercial). Le gate de
licences est verifiable : `python scripts/check_licenses.py`.

## Utilisation

Deux sous-commandes. Aucune cle API en clair : les cles sont lues via des variables d'environnement
(champs `*_api_key_env` de la config).

```bash
# 1) Verdict qualite du corpus
python main.py run    <dossier_pdf> --config config/config.example.yaml --out <sortie> --enrich

# 2) Jeu de questions/reponses de reference (golden set) a faire valider par le metier
python main.py golden <dossier_pdf> --config config/config.example.yaml --out <sortie>
```

(Apres `pip install -e .`, la commande `cqg run ...` / `cqg golden ...` est aussi disponible.)

## Pipeline

```
triage (pypdf)
  -> parse (pdfminer.six + pdfplumber, fallback cid)     # extraction fidele, detection d'echec cid
  -> enrich (image -> texte, VLM, injecte AVANT l'eval)  # optionnel (--enrich)
  -> screen (triage a deux vitesses)                     # doc degrade/propre -> route "light"
  -> metriques deterministes (Gopher/RedPajama, integrite de blocs, redondance de contenu)
  -> jugement LLM par sections (couverture 100% du document, appel batche par section)
  -> rapport Excel/CSV + redondance de corpus
```

Points cles integres :
- **Robustesse du parsing** : detection des echecs de mapping police `(cid:NNN)` et penalisation
  de `parse_confidence` (un document a moitie illisible ne sort plus avec une confiance elevee),
  avec tentative de reextraction pdfplumber.
- **Jugement par sections avec recouvrement** : le document est decoupe en sections a
  recouvrement (facon chunking RAG, reglable) et juge a 100%, au lieu d'un simple extrait.
- **Triage a deux vitesses** : un document manifestement degrade ou manifestement propre est
  route en jugement leger (flague, sans depenser le budget LLM complet).
- **Anti-fabrication** : trois etats `scored | na | not_evaluated`. Une note n'est retenue
  qu'entiere, dans le bareme, ET justifiee. Jamais de note devinee.

## Sorties

`run` (dans `--out`) :
- `corpus_report.xlsx` : onglets **Synthese** (note, niveau, couverture, flags par document),
  **Detail** (les 57 criteres avec statut / note / justification / preuve), **Remediation**.
- `synthese.csv`, `detail.csv`, `remediation.csv`, `<doc>.score.json`, `<doc>.enriched.md`,
  `corpus_redundancy.json`, `cost.json` (appels LLM et volume de prompt par document).

`golden` (dans `--out`) :
- `golden_qa.xlsx` / `golden_qa.csv` : questions/reponses de reference, colonnes
  `question / reponse / sources / couvert / statut_validation / commentaire_beta`. Questions en
  langage naturel d'usager. Nombre variable (auto selon la densite d'information, ou fixe via la
  config). Inclut des questions **transverses au corpus** (reponse croisant plusieurs documents),
  ancrees par retrieval sur le texte integral. Reponse conservee seulement si couverte par les
  documents, sinon "Non couvert par le document".

## Configuration

Modele documente : `config/config.example.yaml`. Sections : `llm` (provider mock / openai /
azure_openai / anthropic + `api_key_env`), `judge` (taille et recouvrement des sections),
`enrichment` (VLM images), `golden` (profil, politique, nombre de questions, questions
transverses + parametres de retrieval).

## Tests

```bash
python -m pytest -q
```

Portable en batch (ex. Azure OpenAI) via le champ `llm.provider` de la configuration.
