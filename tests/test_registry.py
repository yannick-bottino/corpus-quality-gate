from cqg.registry.loader import load_registry


def test_loads_57_criteria():
    reg = load_registry()
    assert len(reg.criteria) == 57


def test_dimension_weights_sum_31():
    reg = load_registry()
    assert sum(reg.dimension_weights.values()) == 31


def test_external_dep_criteria_present():
    reg = load_registry()
    ext = {c.id for c in reg.criteria if c.external_dep}
    assert ext == {"2.7", "2.9", "5.4", "8.3"}


def test_registry_fingerprint_is_content_derived(tmp_path):
    # Run provenance: the grid's fingerprint must follow its CONTENT, so that
    # editing the criteria changes it. A hardcoded version string would not.
    from cqg.registry.loader import registry_fingerprint
    a = tmp_path / "a.yaml"
    a.write_text("scale_max: 5\ndimension_weights: {\"1\": 2}\ncriteria: []\n", encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text("scale_max: 4\ndimension_weights: {\"1\": 2}\ncriteria: []\n", encoding="utf-8")
    fa, fb = registry_fingerprint(str(a)), registry_fingerprint(str(b))
    assert fa != fb
    assert fa == registry_fingerprint(str(a))          # deterministic
    assert len(registry_fingerprint()) == 16           # shipped grid
