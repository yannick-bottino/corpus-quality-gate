# tests/test_signals.py
from cqg.signals import (non_alpha_fraction, duplicate_line_fraction, block_integrity,
                         cid_failure_fraction)
from cqg.models import ParsedDoc, Block


def test_cid_failure_fraction_clean_text_is_zero():
    assert cid_failure_fraction("Bonjour le monde, ceci est du texte propre.") == 0.0


def test_cid_failure_fraction_empty_is_zero():
    assert cid_failure_fraction("") == 0.0


def test_cid_failure_fraction_high_when_cid_dominates():
    # texte majoritairement compose de jetons (cid:NNN) non mappes
    cid = "(cid:114)(cid:97)(cid:103) " * 50
    frac = cid_failure_fraction(cid + "un peu de texte")
    assert frac > 0.5


def test_cid_failure_fraction_counts_replacement_char():
    # U+FFFD (caractere de remplacement) = glyphe non mappe
    text = "abcd" + "�" * 6  # 6 sur 10
    assert cid_failure_fraction(text) > 0.5

def test_non_alpha_fraction():
    assert non_alpha_fraction("abc123") == 0.5

def test_duplicate_line_fraction():
    txt = "ligne a\nligne a\nligne b"
    assert round(duplicate_line_fraction(txt), 2) == 0.33

def test_block_integrity_all_good():
    doc = ParsedDoc(doc_id="d", markdown="x",
                    blocks=[Block(kind="text", text="ok"), Block(kind="text", text="ok2")],
                    parse_confidence=1.0)
    assert block_integrity(doc) == 1.0
