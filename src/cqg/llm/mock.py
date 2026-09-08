from .base import LLMClient

class MockLLM(LLMClient):
    def __init__(self, default: dict | None = None, responses: dict | None = None,
                 image_desc: str = "mock: description image",
                 batch_default: dict | None = None, batch_responses: dict | None = None):
        self.default = default or {"status": "not_evaluated", "score": None,
                                   "justification": "mock: non evalue", "evidence": None}
        self.responses = responses or {}
        self.image_desc = image_desc
        # Lever A: batched responses. batch_responses is indexed by prompt substring
        # (typically a marker present in the section content) and holds a dict
        # {crit_id: response}. batch_default applies if no key matches.
        self.batch_default = batch_default if batch_default is not None else {}
        self.batch_responses = batch_responses or {}

    def judge(self, prompt: str, schema: dict) -> dict:
        for key, resp in self.responses.items():
            if key in prompt:
                return resp
        return self.default

    def judge_batch(self, prompt: str, schema: dict) -> dict[str, dict]:
        for key, resp in self.batch_responses.items():
            if key in prompt:
                return resp
        return dict(self.batch_default)

    def describe_image(self, image_path: str, context: str = "") -> str:
        return self.image_desc
