# tests/test_inventory.py
from cqg.models import ParsedDoc, Block
from cqg.registry.loader import load_registry
from cqg.inventory import block_inventory, na_decisions

def _doc(blocks):
    return ParsedDoc(doc_id="d", markdown="", blocks=blocks, parse_confidence=1.0)

def test_no_images_marks_image_criteria_na():
    doc = _doc([Block(kind="text", text="para")])
    na = na_decisions(doc, load_registry())
    assert {"3.1", "3.2", "3.3"} <= na
    assert "1.1" not in na  # 1.1 n'est pas na_possible : jamais marque N/A

def test_inventory_counts_tables():
    doc = _doc([Block(kind="table", text="a"), Block(kind="text", text="b")])
    assert block_inventory(doc)["tables"] == 1
