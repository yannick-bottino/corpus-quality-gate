from abc import ABC, abstractmethod

class LLMClient(ABC):
    @abstractmethod
    def judge(self, prompt: str, schema: dict) -> dict: ...

    def judge_batch(self, prompt: str, schema: dict) -> dict[str, dict]:
        # Lever A: judges all the qualitative criteria of a section in a single call.
        # Returns {crit_id: {status, score, justification, evidence}}.
        raise NotImplementedError("Ce provider LLM ne supporte pas le jugement batche")

    def describe_image(self, image_path: str, context: str = "") -> str:
        raise NotImplementedError("Ce provider LLM ne supporte pas la description d'image")

def from_config(cfg: dict) -> "LLMClient":
    provider = cfg.get("provider", "mock")
    if provider == "mock":
        from .mock import MockLLM
        return MockLLM()
    if provider in ("openai", "azure_openai", "anthropic"):
        from .providers import ProviderLLM
        return ProviderLLM(cfg)
    if provider == "claude_cli":
        from .claude_cli import ClaudeCLILLM
        return ClaudeCLILLM(cfg)
    if provider == "manual":
        from .manual import ManualVLM
        return ManualVLM(cfg.get("manifest_path", "workdir/image_manifest.json"))
    raise ValueError(f"Provider LLM inconnu: {provider}")
