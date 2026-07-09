# src/cqg/llm/providers.py
import os
import json
import re
from .base import LLMClient


def _extract_json(text: str) -> dict:
    """Extrait un objet JSON d'une reponse LLM, meme entouree de prose ou de balises code."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


class ProviderLLM(LLMClient):
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.provider = cfg["provider"]
        self.model = cfg.get("model")
        self.api_key_env = cfg.get("api_key_env", "CQG_LLM_API_KEY")
        self.api_key = os.environ.get(self.api_key_env)
        self.base_url = cfg.get("base_url") or None

    def _client(self):
        if self.provider in ("openai", "azure_openai"):
            from openai import OpenAI, AzureOpenAI
            return (AzureOpenAI(api_key=self.api_key, azure_endpoint=self.base_url,
                                api_version=self.cfg.get("api_version", "2024-06-01"))
                    if self.provider == "azure_openai"
                    else OpenAI(api_key=self.api_key, base_url=self.base_url))
        from anthropic import Anthropic
        return Anthropic(api_key=self.api_key, base_url=self.base_url)

    def judge(self, prompt: str, schema: dict) -> dict:
        if self.api_key is None:
            raise RuntimeError(
                f"Cle API absente: definir la variable d'environnement {self.api_key_env}")
        if self.provider in ("openai", "azure_openai"):
            client = self._client()
            resp = client.chat.completions.create(
                model=self.model, temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}])
            return _extract_json(resp.choices[0].message.content)
        client = self._client()
        msg = client.messages.create(model=self.model, max_tokens=1024, temperature=0,
                                     messages=[{"role": "user", "content": prompt}])
        return _extract_json(msg.content[0].text)

    def judge_batch(self, prompt: str, schema: dict) -> dict[str, dict]:
        # Levier A : un seul appel couvre tous les criteres qualitatifs d'une section.
        # La reponse attendue est un objet JSON {crit_id: {status, score, justification,
        # evidence}}. Meme transport que judge, seul le prompt et le parsing different.
        if self.api_key is None:
            raise RuntimeError(
                f"Cle API absente: definir la variable d'environnement {self.api_key_env}")
        if self.provider in ("openai", "azure_openai"):
            client = self._client()
            resp = client.chat.completions.create(
                model=self.model, temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}])
            return _extract_json(resp.choices[0].message.content)
        client = self._client()
        msg = client.messages.create(model=self.model, max_tokens=4096, temperature=0,
                                     messages=[{"role": "user", "content": prompt}])
        return _extract_json(msg.content[0].text)

    def describe_image(self, image_path: str, context: str = "") -> str:
        if self.api_key is None:
            raise RuntimeError(
                f"Cle API absente: definir la variable d'environnement {self.api_key_env}")
        import base64
        with open(image_path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode()
        prompt = ("Decris cette image en detail pour un index de recherche documentaire. "
                  "Restitue le texte visible, les donnees des graphiques et tableaux, et le sens. "
                  "Reponds dans la langue du document. Ne fabrique aucune valeur incertaine. "
                  f"Contexte: {context}")
        if self.provider in ("openai", "azure_openai"):
            client = self._client()
            resp = client.chat.completions.create(
                model=self.model, temperature=0,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{data}"}}]}])
            return resp.choices[0].message.content or ""
        client = self._client()
        msg = client.messages.create(model=self.model, max_tokens=1024, temperature=0,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/png", "data": data}}]}])
        return msg.content[0].text
