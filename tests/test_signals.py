# tests/test_signals.py
from cqg.signals import (non_alpha_fraction, duplicate_line_fraction, block_integrity,
                         cid_failure_fraction, type_token_ratio, mattr)
from cqg.models import ParsedDoc, Block


def test_cid_failure_fraction_clean_text_is_zero():
    assert cid_failure_fraction("Bonjour le monde, ceci est du texte propre.") == 0.0


def test_cid_failure_fraction_empty_is_zero():
    assert cid_failure_fraction("") == 0.0


def test_cid_failure_fraction_high_when_cid_dominates():
    # text mostly composed of unmapped (cid:NNN) tokens
    cid = "(cid:114)(cid:97)(cid:103) " * 50
    frac = cid_failure_fraction(cid + "un peu de texte")
    assert frac > 0.5


def test_cid_failure_fraction_counts_replacement_char():
    # U+FFFD (replacement character) = unmapped glyph
    text = "abcd" + "�" * 6  # 6 out of 10
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


def test_mattr_falls_back_to_global_when_shorter_than_window():
    # Text shorter than the window -> MATTR reduces to the global TTR.
    text = "un deux trois deux un"  # 5 tokens, 3 unique
    assert mattr(text, window=1000) == type_token_ratio(text)


def test_mattr_stays_high_on_long_repetitive_document():
    # Healthy vocabulary repeated over a long document: the global TTR collapses
    # (denominator = total length) while each window stays varied.
    # This is the "Le Cahier Ma Sante" case: 222 pages, global ttr=0.0042, healthy vocabulary.
    passage = " ".join(f"mot{i}" for i in range(300))  # 300 unique tokens
    text = (passage + " ") * 200                        # 60000 tokens, 300 unique
    assert type_token_ratio(text) < 0.01               # global TTR crushed by the length
    assert mattr(text, window=1000) > 0.05             # windowed TTR stays healthy
