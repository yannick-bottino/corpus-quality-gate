# src/cqg/config.py
import hashlib
import json
from pathlib import Path
import yaml

# Config sections that cannot change a score: excluded from the run fingerprint
# so that relocating the output does not look like a different evaluation.
_NON_SCORING_SECTIONS = {"paths"}

def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))

def config_hash(cfg: dict, registry_version: str, policy_version: str | None = None) -> str:
    # Run provenance stamped into every DocScore: tells whether two score files are
    # comparable. Covers the WHOLE configuration except the non-scoring sections, so a
    # section added later is fingerprinted without editing this function. An allowlist
    # was the previous design and silently omitted judge/parsing/enrichment, letting two
    # runs with different section sizing, parser or enrichment share a hash while
    # producing different scores. Erring towards over-sensitivity is deliberate: a false
    # "different" makes someone look twice, a false "same" licenses a wrong comparison.
    payload = {k: v for k, v in (cfg or {}).items() if k not in _NON_SCORING_SECTIONS}
    payload["registry_version"] = registry_version
    if policy_version is not None:
        # Redundant once golden.policy is inside the payload; kept for signature stability.
        payload["policy_version"] = policy_version
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
