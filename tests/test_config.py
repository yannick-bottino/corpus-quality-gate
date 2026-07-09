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
