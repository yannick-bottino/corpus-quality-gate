"""Cost instrumentation for the LLM layer.

Wraps an LLMClient and counts the number of judgment calls and the total prompt
characters sent. Serves as the central criterion for levers A (batched) and
C (triage): number of LLM calls/doc and prompt chars/doc, to be logged per run.
Image description calls (VLM) are not counted as judgment calls.
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
        # Lever A: one batched call = one section. Counts as one judgment call
        # (new cost driver: calls/doc = number of sections).
        self.n_calls += 1
        self.total_prompt_chars += len(prompt)
        return self.inner.judge_batch(prompt, schema)

    def describe_image(self, image_path: str, context: str = "") -> str:
        return self.inner.describe_image(image_path, context)

    def reset(self):
        self.n_calls = 0
        self.total_prompt_chars = 0
