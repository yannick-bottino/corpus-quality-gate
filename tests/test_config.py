# tests/test_config.py
from cqg.config import config_hash

def test_config_hash_deterministic():
    cfg = {"llm": {"provider": "mock", "model": "m", "temperature": 0}}
    h1 = config_hash(cfg, "reg-v1", "pol-v1")
    h2 = config_hash(cfg, "reg-v1", "pol-v1")
    assert h1 == h2 and len(h1) == 16

def test_config_hash_changes_with_model():
    a = config_hash({"llm": {"model": "m1"}}, "r", "p")
    b = config_hash({"llm": {"model": "m2"}}, "r", "p")
    assert a != b


_BASE = {
    "llm": {"provider": "mock"},
    "thresholds": {"coverage_flag_below": 0.7},
    "judge": {"section_chars": 8000, "section_overlap": "auto"},
    "parsing": {"parser": "docling"},
    "enrichment": {"enabled": False},
}


def test_config_hash_covers_every_scoring_section():
    # Provenance: any setting that can move a score must change the fingerprint.
    # judge (section count -> median aggregation), parsing (extracted text) and
    # enrichment (scored text) were previously excluded, so two runs producing
    # different scores could share a hash and be wrongly compared.
    h = config_hash(_BASE, "r", "p")
    for section, key, value in (("judge", "section_chars", 2000),
                                ("parsing", "parser", "legacy"),
                                ("enrichment", "enabled", True)):
        variant = {**_BASE, section: {**_BASE[section], key: value}}
        assert config_hash(variant, "r", "p") != h, f"{section}.{key} not covered"


def test_config_hash_covers_unknown_future_sections():
    # Whole-config coverage: a section added later is fingerprinted without
    # editing config_hash (the failure mode that produced the original gap).
    variant = {**_BASE, "section_inventee": {"x": 1}}
    assert config_hash(variant, "r", "p") != config_hash(_BASE, "r", "p")


def test_config_hash_ignores_paths():
    # paths.workdir only says where output lands; it cannot change a score.
    a = config_hash({**_BASE, "paths": {"workdir": "./a"}}, "r", "p")
    b = config_hash({**_BASE, "paths": {"workdir": "./b"}}, "r", "p")
    assert a == b


def test_config_hash_changes_with_registry_version():
    assert config_hash(_BASE, "reg-a", "p") != config_hash(_BASE, "reg-b", "p")


def test_config_hash_policy_version_optional():
    # policy_version is redundant now that golden.policy is inside the payload;
    # it stays optional for signature stability.
    assert len(config_hash(_BASE, "r")) == 16
