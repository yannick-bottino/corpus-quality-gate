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
