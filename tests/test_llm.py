import pytest
from cqg.llm.base import from_config
from cqg.llm.mock import MockLLM

def test_mock_returns_scripted():
    llm = MockLLM(default={"status": "scored", "score": 4, "justification": "ok", "evidence": "s1"})
    out = llm.judge("note le critere 2.5", {"type": "object"})
    assert out["score"] == 4

def test_factory_builds_mock():
    llm = from_config({"provider": "mock"})
    assert isinstance(llm, MockLLM)

def test_factory_unknown_provider_raises():
    with pytest.raises(ValueError):
        from_config({"provider": "nope"})

def test_factory_builds_providers():
    from cqg.llm.providers import ProviderLLM
    for p in ("openai", "azure_openai", "anthropic"):
        assert isinstance(from_config({"provider": p}), ProviderLLM)

def test_provider_missing_key_raises(monkeypatch):
    monkeypatch.delenv("CQG_LLM_API_KEY", raising=False)
    llm = from_config({"provider": "openai", "api_key_env": "CQG_LLM_API_KEY"})
    with pytest.raises(RuntimeError):
        llm.judge("x", {"type": "object"})

def test_extract_json_from_fenced_or_prose():
    from cqg.llm.providers import _extract_json
    assert _extract_json('```json\n{"a": 1}\n```')["a"] == 1
    assert _extract_json('Voici la reponse: {"b": 2} fin')["b"] == 2

def test_mock_describe_image(tmp_path):
    from cqg.llm.mock import MockLLM
    png = tmp_path / "i.png"; png.write_bytes(b"x")
    out = MockLLM(image_desc="desc mock").describe_image(str(png), context="p12")
    assert out == "desc mock"

def test_provider_describe_image_missing_key_raises(monkeypatch, tmp_path):
    from cqg.llm.providers import ProviderLLM
    monkeypatch.delenv("CQG_ABSENT_KEY", raising=False)
    llm = ProviderLLM({"provider": "anthropic", "api_key_env": "CQG_ABSENT_KEY"})
    png = tmp_path / "i.png"; png.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        llm.describe_image(str(png))

def test_manual_vlm_writes_manifest(tmp_path):
    import json
    from cqg.llm.manual import ManualVLM
    man = tmp_path / "m.json"
    vlm = ManualVLM(str(man))
    assert vlm.describe_image("a.png", context="p1") == ""
    vlm.flush()
    data = json.loads(man.read_text(encoding="utf-8"))
    assert data[0]["image_path"] == "a.png" and data[0]["context"] == "p1"

def test_manual_vlm_reloads_filled_descriptions(tmp_path):
    # Manifeste-aware : un manifeste deja rempli hors ligne / in-session est relu, et
    # describe_image restitue la description -> un second run enrichit le markdown AVANT
    # l'evaluation, sans passe apply_descriptions separee.
    import json
    from cqg.llm.manual import ManualVLM
    man = tmp_path / "m.json"
    man.write_text(json.dumps([
        {"image_path": "a.png", "context": "p1|[[IMAGE:p=1;idx=1]]",
         "placeholder": "[[IMAGE:p=1;idx=1]]", "description": "un histogramme"}
    ]), encoding="utf-8")
    vlm = ManualVLM(str(man))
    assert vlm.describe_image("a.png", context="p1|[[IMAGE:p=1;idx=1]]") == "un histogramme"
    vlm.flush()
    data = json.loads(man.read_text(encoding="utf-8"))
    assert data[0]["description"] == "un histogramme"
