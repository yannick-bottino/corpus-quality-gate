"""Instrumentation de cout de la couche LLM.

Enveloppe un LLMClient et compte le nombre d'appels de jugement et le total de
caracteres de prompt envoyes. Sert de critere central aux leviers A (batche) et
C (triage) : nb d'appels LLM/doc et chars de prompt/doc, a consigner par run.
Les appels de description d'image (VLM) ne sont pas comptes comme appels de jugement.
"""
from .base import LLMClient


class CountingLLM(LLMClient):
    def __init__(self, inner: LLMClient):
        self.inner = inner
        self.n_calls = 0
        self.total_prompt_chars = 0

    def judge(self, prompt: str, schema: dict) -> dict:
        self.n_calls += 1
        self.total_prompt_chars += len(prompt)
        return self.inner.judge(prompt, schema)

    def judge_batch(self, prompt: str, schema: dict) -> dict[str, dict]:
        # Levier A : un appel batche = une section. Compte comme un appel de jugement
        # (nouveau driver de cout : appels/doc = nb de sections).
        self.n_calls += 1
        self.total_prompt_chars += len(prompt)
        return self.inner.judge_batch(prompt, schema)

    def describe_image(self, image_path: str, context: str = "") -> str:
        return self.inner.describe_image(image_path, context)

    def reset(self):
        self.n_calls = 0
        self.total_prompt_chars = 0
