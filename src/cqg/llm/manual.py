import json
from pathlib import Path
from .base import LLMClient

class ManualVLM(LLMClient):
    # Rend un manifeste des images a decrire ; les descriptions sont remplies
    # hors ligne (LLM in-session) puis injectees via enrich.apply_descriptions.
    # Au chargement, relit un manifeste existant : si des descriptions y ont ete
    # remplies, describe_image les restitue -> un second run enrichit le markdown
    # AVANT l'evaluation (enrich-avant-eval), sans passe apply_descriptions separee.
    def __init__(self, manifest_path: str):
        self.manifest_path = manifest_path
        self._items: list[dict] = []
        self._filled: dict[str, str] = {}
        p = Path(manifest_path)
        if p.exists():
            try:
                prev = json.loads(p.read_text(encoding="utf-8"))
                for it in prev:
                    ph = it.get("placeholder")
                    desc = (it.get("description") or "").strip()
                    if ph and desc:
                        self._filled[ph] = desc
            except (ValueError, OSError):
                pass  # manifeste illisible : on repart d'un manifeste vide

    def judge(self, prompt: str, schema: dict) -> dict:
        raise RuntimeError("ManualVLM ne juge pas de texte")

    def describe_image(self, image_path: str, context: str = "") -> str:
        placeholder = context.split("|", 1)[1] if "|" in context else ""
        desc = self._filled.get(placeholder, "")
        self._items.append({"image_path": image_path, "context": context,
                            "placeholder": placeholder, "description": desc})
        return desc

    def flush(self) -> str:
        Path(self.manifest_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.manifest_path).write_text(
            json.dumps(self._items, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.manifest_path
