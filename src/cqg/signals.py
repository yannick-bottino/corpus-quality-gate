# src/cqg/signals.py
import re
from .models import ParsedDoc

_CID_RE = re.compile(r"\(cid:\d+\)")


def cid_failure_fraction(text: str) -> float:
    """Proportion de contenu perdu a l'extraction : jetons (cid:NNN) et glyphes non mappes.

    Un echec de mapping police (frequent sur les PDF anciens) laisse pdfminer emettre
    des jetons '(cid:NNN)' au lieu des caracteres, ou des caracteres de remplacement
    U+FFFD. Ce signal mesure la part du texte occupee par ces artefacts, rapportee a la
    longueur totale. 0.0 sur du texte propre ; eleve sur une extraction degradee.
    """
    if not text:
        return 0.0
    n = len(text)
    cid_chars = sum(len(m.group(0)) for m in _CID_RE.finditer(text))
    replacement_chars = text.count("�")
    return round(min(1.0, (cid_chars + replacement_chars) / n), 4)

def non_alpha_fraction(text: str) -> float:
    if not text:
        return 1.0
    alpha = sum(c.isalpha() for c in text)
    return round(1 - alpha / len(text), 4)

def mean_words_per_sentence(text: str) -> float:
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if not sentences:
        return 0.0
    return round(sum(len(s.split()) for s in sentences) / len(sentences), 2)

def duplicate_line_fraction(text: str) -> float:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    seen, dup = set(), 0
    for l in lines:
        if l in seen:
            dup += 1
        seen.add(l)
    return round(dup / len(lines), 4)

def type_token_ratio(text: str) -> float:
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return 0.0
    return round(len(set(tokens)) / len(tokens), 4)

def mattr(text: str, window: int = 1000) -> float:
    """TTR normalise par fenetre (Mean Segmental TTR) : robuste a la longueur.

    Le TTR global (type_token_ratio) decroit mecaniquement avec la longueur : sur un
    document long, le vocabulaire sature et le denominateur (nombre total de tokens)
    ecrase le ratio, quel que soit l'etat reel de l'extraction. Exemple mesure sur "Le
    Cahier Ma Sante" (222 pages) : ttr global=0.0042 alors que le vocabulaire est sain.

    On decoupe donc le texte en segments de `window` tokens, on calcule le TTR de chaque
    segment et on renvoie la moyenne. Un texte au vocabulaire sain garde un TTR de segment
    eleve meme sur des centaines de pages ; une extraction reellement degradee (texte
    repete/illisible) reste basse sur chaque fenetre. Pour un texte plus court que
    `window`, se reduit au TTR global.
    """
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return 0.0
    if len(tokens) < window:
        return round(len(set(tokens)) / len(tokens), 4)
    ratios = []
    for i in range(0, len(tokens) - window + 1, window):
        seg = tokens[i:i + window]
        ratios.append(len(set(seg)) / window)
    return round(sum(ratios) / len(ratios), 4)

def token_count(text: str) -> int:
    """Nombre de tokens mots (meme tokenisation que le TTR). Sert de proxy de taille
    pour le garde-fou metadonnees du triage (cf. screen.py)."""
    return len(re.findall(r"\w+", text.lower()))

def block_integrity(doc: ParsedDoc) -> float:
    if not doc.blocks:
        return 0.0
    good = sum(1 for b in doc.blocks if b.text.strip())
    return round(good / len(doc.blocks), 4)
