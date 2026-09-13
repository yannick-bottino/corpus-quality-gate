import pytest
from cqg.models import Block, ImageRef, ParsedDoc, ParseProvenance
from cqg import parse_store


def _doc(doc_id="doc", markdown="Paragraphe un.\n\nParagraphe deux."):
    return ParsedDoc(
        doc_id=doc_id, markdown=markdown,
        blocks=[Block(kind="table", text="", page=1),
                Block(kind="image", text="", page=1),
                Block(kind="text", text="Paragraphe un.", page=1)],
        parse_confidence=0.842,
        images=[ImageRef(page=1, idx=1, x0=10.0, top=20.0, x1=110.0, bottom=140.0,
                         placeholder="[[IMAGE:p=1;idx=1]]")])


def _prov(**kw):
    base = dict(parser="legacy", source_name="doc.pdf", source_type="pdf",
                source_sha256="0" * 64, source_pages=3, category="born_digital",
                enriched=False)
    base.update(kw)
    return ParseProvenance(**base)


def test_round_trip_preserves_the_scored_markdown_byte_for_byte(tmp_path):
    # The markdown read back IS the string every downstream signal is computed on:
    # a stray \r turned into \n by universal-newline decoding would silently shift
    # non_alpha_fraction, token_count and duplicate_line_fraction.
    doc = _doc(markdown="ligne\r\nsuite\r\n\r\nparagraphe\ttabule")
    parse_store.write_parsed_doc(doc, str(tmp_path), _prov())
    entry = parse_store.read_parsed_doc(str(tmp_path / "doc.md"))
    assert entry.doc.markdown == doc.markdown
    assert (tmp_path / "doc.md").read_bytes().decode("utf-8") == doc.markdown
    assert entry.flags == []


def test_sidecar_carries_blocks_images_and_confidence(tmp_path):
    # Without the sidecar, na_decisions would see zero block and flip the
    # structure criteria to `na` for a reason foreign to document quality.
    doc = _doc()
    parse_store.write_parsed_doc(doc, str(tmp_path), _prov())
    entry = parse_store.read_parsed_doc(str(tmp_path / "doc.md"))
    assert entry.doc.blocks == doc.blocks
    assert entry.doc.images == doc.images
    assert entry.doc.parse_confidence == doc.parse_confidence
    assert entry.doc.doc_id == "doc"
    assert entry.sidecar.provenance.source_sha256 == "0" * 64


def test_hand_edited_markdown_is_flagged_and_text_blocks_recomputed(tmp_path):
    doc = _doc()
    parse_store.write_parsed_doc(doc, str(tmp_path), _prov())
    (tmp_path / "doc.md").write_bytes("Texte corrige.\n\nNouveau paragraphe.".encode("utf-8"))
    entry = parse_store.read_parsed_doc(str(tmp_path / "doc.md"))
    assert entry.flags == ["manually_edited"]
    assert entry.doc.markdown == "Texte corrige.\n\nNouveau paragraphe."
    texts = [b.text for b in entry.doc.blocks if b.kind == "text"]
    assert texts == ["Texte corrige.", "Nouveau paragraphe."]


def test_hand_edited_markdown_keeps_typed_blocks_from_the_sidecar(tmp_path):
    # Tables, images and formulas are parse-time facts about the SOURCE. A markdown
    # edit cannot re-derive them, and fabricating them from the prose would gut the
    # inventory na_decisions reads.
    doc = _doc()
    parse_store.write_parsed_doc(doc, str(tmp_path), _prov())
    (tmp_path / "doc.md").write_bytes("Texte corrige.".encode("utf-8"))
    entry = parse_store.read_parsed_doc(str(tmp_path / "doc.md"))
    kinds = [b.kind for b in entry.doc.blocks]
    assert kinds.count("table") == 1
    assert kinds.count("image") == 1
    assert entry.doc.images == doc.images


def test_missing_sidecar_is_flagged_never_dropped(tmp_path):
    (tmp_path / "ajoute.md").write_bytes("Document depose a la main.".encode("utf-8"))
    entry = parse_store.read_parsed_doc(str(tmp_path / "ajoute.md"))
    assert entry.flags == ["missing_sidecar"]
    assert entry.sidecar is None
    assert entry.doc.doc_id == "ajoute"
    assert [b.text for b in entry.doc.blocks] == ["Document depose a la main."]


def test_missing_markdown_is_flagged_never_dropped(tmp_path):
    doc = _doc()
    parse_store.write_parsed_doc(doc, str(tmp_path), _prov())
    (tmp_path / "doc.md").unlink()
    entry = parse_store.read_parsed_doc(str(tmp_path / "doc.md"))
    assert entry.flags == ["missing_markdown"]
    assert entry.doc.markdown == ""


def test_a_corrupt_sidecar_is_flagged_never_fatal(tmp_path):
    # A sidecar edited or truncated by hand must not bring down the corpus: the
    # document is scored on what can still be read, and said to be degraded.
    doc = _doc()
    parse_store.write_parsed_doc(doc, str(tmp_path), _prov())
    (tmp_path / "doc.parse.json").write_text("{ pas du json", encoding="utf-8")
    entry = parse_store.read_parsed_doc(str(tmp_path / "doc.md"))
    assert entry.flags == ["invalid_sidecar"]
    assert entry.sidecar is None
    assert entry.doc.markdown == doc.markdown


def test_markdown_saved_in_another_encoding_degrades_instead_of_crashing(tmp_path):
    # Same precedent as _plain_text_extraction: decoding damage becomes U+FFFD, which
    # cid_failure_fraction counts and flags, rather than an exception that loses the doc.
    doc = _doc()
    parse_store.write_parsed_doc(doc, str(tmp_path), _prov())
    (tmp_path / "doc.md").write_bytes("Texte accentu\xe9 en latin-1.".encode("latin-1"))
    entry = parse_store.read_parsed_doc(str(tmp_path / "doc.md"))
    assert "�" in entry.doc.markdown
    assert entry.flags == ["manually_edited"]


def test_a_sidecar_from_a_newer_cqg_is_flagged(tmp_path):
    # A field this version cannot honour must not be read as if it understood it:
    # a sidecar written by a later cqg is scored, and said to be beyond this schema.
    import json
    doc = _doc()
    parse_store.write_parsed_doc(doc, str(tmp_path), _prov())
    side = json.loads((tmp_path / "doc.parse.json").read_text(encoding="utf-8"))
    side["schema_version"] = parse_store.SIDECAR_SCHEMA_VERSION + 1
    (tmp_path / "doc.parse.json").write_text(json.dumps(side), encoding="utf-8")
    entry = parse_store.read_parsed_doc(str(tmp_path / "doc.md"))
    assert entry.flags == [f"sidecar_schema_unsupported:{parse_store.SIDECAR_SCHEMA_VERSION + 1}"]
    assert entry.doc.markdown == doc.markdown


def test_doc_id_with_spaces_accents_and_parentheses_round_trips(tmp_path):
    doc = _doc(doc_id="Le Cahier Ma Santé (AGA - AEP)")
    written = parse_store.write_parsed_doc(doc, str(tmp_path), _prov())
    assert written["sidecar"].endswith("Le Cahier Ma Santé (AGA - AEP).parse.json")
    entry = parse_store.read_parsed_doc(written["markdown"])
    assert entry.doc.doc_id == "Le Cahier Ma Santé (AGA - AEP)"
    assert entry.flags == []


def test_is_parsed_input_detects_a_sidecar(tmp_path):
    assert parse_store.is_parsed_input(str(tmp_path)) is False
    parse_store.write_parsed_doc(_doc(), str(tmp_path), _prov())
    assert parse_store.is_parsed_input(str(tmp_path)) is True


def test_a_folder_holding_both_sidecars_and_raw_sources_is_refused(tmp_path):
    # Ambiguous: scoring it as raw would re-parse the .md exports, scoring it as
    # parsed would drop the PDF. Loud failure beats a silent mode choice.
    parse_store.write_parsed_doc(_doc(), str(tmp_path), _prov())
    (tmp_path / "brut.pdf").write_bytes(b"%PDF-1.4")
    with pytest.raises(ValueError):
        parse_store.is_parsed_input(str(tmp_path))


def test_markdown_only_folder_stays_a_raw_corpus(tmp_path):
    # A folder of hand-written .md files is a legitimate raw corpus: .md is a
    # supported source format, so its absence of sidecars must not be ambiguous.
    (tmp_path / "note.md").write_text("Une note.", encoding="utf-8")
    assert parse_store.is_parsed_input(str(tmp_path)) is False


def test_parsed_entries_are_listed_in_stable_order(tmp_path):
    for name in ("b", "a", "c"):
        parse_store.write_parsed_doc(_doc(doc_id=name), str(tmp_path), _prov())
    assert [p.stem for p in parse_store.parsed_markdown_paths(str(tmp_path))] == ["a", "b", "c"]


def test_orphan_sidecar_is_listed_so_the_document_is_never_lost(tmp_path):
    parse_store.write_parsed_doc(_doc(doc_id="perdu"), str(tmp_path), _prov())
    (tmp_path / "perdu.md").unlink()
    assert [p.stem for p in parse_store.parsed_markdown_paths(str(tmp_path))] == ["perdu"]
