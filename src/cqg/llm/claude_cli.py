import json
import os
import shutil
import subprocess
from .base import LLMClient
from .providers import _extract_json


class ClaudeCLILLM(LLMClient):
    """Provider SANS cle API : delegue le jugement au CLI `claude` (souscription Claude
    Code). Chaque appel = un sous-processus `claude -p --output-format json`, le prompt
    passe par stdin (pas de limite d'argv). L'enveloppe renvoyee par le CLI expose le
    texte du modele dans le champ `result`, qu'on parse avec le meme `_extract_json` que
    le provider API. Utile quand aucune cle n'est disponible mais qu'une session Claude
    Code authentifiee l'est (l'auth de la souscription n'est pas exposee comme cle API).
    """

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.model = cfg.get("model") or None
        self.bin = cfg.get("cli_path") or shutil.which("claude") or "claude"
        self.timeout = int(cfg.get("cli_timeout", 300))

    def _run(self, prompt: str) -> str:
        cmd = [self.bin, "-p", "--output-format", "json"]
        if self.model:
            cmd += ["--model", self.model]
        env = dict(os.environ)
        # Evite tout garde-fou d'imbrication de session lors de l'appel en sous-processus.
        env.pop("CLAUDE_CODE_CHILD_SESSION", None)
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              timeout=self.timeout, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                f"CLI claude a echoue (rc={proc.returncode}): {(proc.stderr or '')[:500]}")
        envelope = json.loads(proc.stdout)
        if envelope.get("is_error"):
            raise RuntimeError(f"CLI claude erreur: {str(envelope.get('result', ''))[:500]}")
        return envelope.get("result", "") or ""

    def judge(self, prompt: str, schema: dict) -> dict:
        return _extract_json(self._run(prompt))

    def judge_batch(self, prompt: str, schema: dict) -> dict[str, dict]:
        return _extract_json(self._run(prompt))
