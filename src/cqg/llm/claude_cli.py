import json
import os
import shutil
import subprocess
from .base import LLMClient
from .providers import _extract_json


class ClaudeCLILLM(LLMClient):
    """Provider with NO API key: delegates judgment to the `claude` CLI (Claude Code
    subscription). Each call = a `claude -p --output-format json` subprocess, the prompt
    goes through stdin (no argv limit). The envelope returned by the CLI exposes the
    model text in the `result` field, which we parse with the same `_extract_json` as
    the API provider. Useful when no key is available but an authenticated Claude Code
    session is (subscription auth is not exposed as an API key).
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
        # Avoids any session-nesting guard when calling out as a subprocess.
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
