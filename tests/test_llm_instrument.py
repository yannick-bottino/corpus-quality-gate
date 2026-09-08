"""Tests of the cost instrumentation of the LLM layer (call counter + chars)."""
from cqg.llm.mock import MockLLM
from cqg.llm.instrument import CountingLLM


def test_counts_judge_calls_and_prompt_chars():
    inner = MockLLM()
    client = CountingLLM(inner)

    client.judge("abcde", {})       # 5 chars
    client.judge("xyz", {})         # 3 chars

    assert client.n_calls == 2
    assert client.total_prompt_chars == 8


def test_judge_passes_through_inner_response():
    inner = MockLLM(default={"status": "scored", "score": 4, "justification": "j", "evidence": None})
    client = CountingLLM(inner)

    resp = client.judge("prompt", {})

    assert resp["status"] == "scored"
    assert resp["score"] == 4


def test_describe_image_not_counted_as_judge_call():
    client = CountingLLM(MockLLM(image_desc="desc"))

    out = client.describe_image("img.png", context="ctx")

    assert out == "desc"
    assert client.n_calls == 0
    assert client.total_prompt_chars == 0


def test_reset_zeroes_counters():
    client = CountingLLM(MockLLM())
    client.judge("abc", {})
    client.reset()
    assert client.n_calls == 0
    assert client.total_prompt_chars == 0
