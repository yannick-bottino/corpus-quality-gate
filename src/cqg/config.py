# src/cqg/config.py
import hashlib
import json
from pathlib import Path
import yaml

def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))

def config_hash(cfg: dict, registry_version: str, policy_version: str) -> str:
    payload = {
        "llm": cfg.get("llm", {}),
        "thresholds": cfg.get("thresholds", {}),
        "registry_version": registry_version,
        "policy_version": policy_version,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
