import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel


class Criterion(BaseModel):
    id: str
    dimension: str
    label: str
    weight: int
    tag: str
    external_dep: bool = False
    na_possible: bool = False


class Registry(BaseModel):
    scale_max: int
    dimension_weights: dict[str, int]
    criteria: list[Criterion]


_DEFAULT = Path(__file__).parent / "criteria_registry.yaml"


def registry_fingerprint(path: str | None = None) -> str:
    """Short content hash of the criteria grid, for run provenance.

    Derived from the file CONTENT so that editing the grid changes the run
    fingerprint. A hardcoded version string cannot do that: the criteria drive
    every score, so an edited grid must not share a fingerprint with the old one.
    """
    return hashlib.sha256(Path(path or _DEFAULT).read_bytes()).hexdigest()[:16]


def load_registry(path: str | None = None) -> Registry:
    data = yaml.safe_load(Path(path or _DEFAULT).read_text(encoding="utf-8"))
    reg = Registry(**data)
    ids = [c.id for c in reg.criteria]
    if len(ids) != len(set(ids)):
        raise ValueError("Ids de criteres dupliques dans le registre")
    return reg
