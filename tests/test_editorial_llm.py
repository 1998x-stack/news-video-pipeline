"""Bounded, cached, schema-checked LLM stages (task 4)."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.editorial.llm import EditorialLLM, json_object, require_keys


def chunk(content, usage=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))], usage=usage)


def make_client(answer: str, calls: list, usage=None, error: Exception | None = None):
    """A minimal stand-in for an OpenAI-compatible streaming client."""

    def create(**request):
        calls.append(request)
        if error is not None:
            raise error
        return iter([chunk(answer, usage)])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.fixture()
def cfg(monkeypatch) -> dict:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    config = load_config()
    config["planner"]["model"] = "test-model"
    config["planner"]["max_retries"] = 0
    return config


def fake(cfg, answer, calls, usage=None, error=None, cache_dir=None):
    return EditorialLLM(cfg, cache_dir=cache_dir, client_factory=lambda _cfg: make_client(answer, calls, usage, error))


def test_json_object_accepts_plain_and_fenced_answers():
    assert json_object('{"a": 1}') == {"a": 1}
    assert json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError, match="valid JSON"):
        json_object("抱歉，我无法回答。")
    with pytest.raises(ValueError, match="expected a JSON object"):
        json_object("[1, 2]")


def test_require_keys_names_the_stage_and_the_missing_key():
    require_keys({"items": []}, ("items",), "aggregate_split")
    with pytest.raises(ValueError, match="aggregate_split: response is missing required key"):
        require_keys({"wrong": []}, ("items",), "aggregate_split")


def test_calls_are_logged_with_latency_hash_and_retries(cfg):
    calls: list = []
    model = fake(cfg, '{"items": ["甲", "乙"]}', calls)
    result = model("aggregate_split", {"text": "..."})
    assert result == {"items": ["甲", "乙"]}
    assert model.call_count == 1
    entry = model.stage_log[0]
    assert entry["stage"] == "aggregate_split"
    assert entry["cache_hit"] is False
    assert entry["retries"] == 0
    assert entry["error"] is None
    assert entry["latency_s"] >= 0
    assert entry["content_sha256"] == hashlib.sha256('{"items": ["甲", "乙"]}'.encode()).hexdigest()
    assert model.summary()["requests"] == 1
    assert model.summary()["failures"] == 0


def test_request_carries_the_gateway_controls(cfg):
    cfg["planner"]["reasoning_effort"] = "none"
    calls: list = []
    fake(cfg, '{"items": []}', calls)("aggregate_split", {"text": "x"})
    request = calls[0]
    assert request["model"] == "test-model"
    assert request["stream"] is True
    assert request["reasoning_effort"] == "none"
    assert request["max_tokens"] > 0
    assert request["messages"][0]["role"] == "system"


def test_non_json_answer_names_the_stage(cfg):
    calls: list = []
    with pytest.raises(ValueError, match="aggregate_split.*valid JSON"):
        fake(cfg, "我觉得这条新闻很重要。", calls)("aggregate_split", {"text": "x"})


def test_missing_stage_key_fails_closed(cfg):
    calls: list = []
    with pytest.raises(ValueError, match="missing required key"):
        fake(cfg, '{"wrong": 1}', calls)("aggregate_split", {"text": "x"})


def test_unknown_stage_is_rejected(cfg):
    calls: list = []
    with pytest.raises(ValueError, match="Unknown editorial stage"):
        fake(cfg, "{}", calls)("summarise_everything", {})


def test_identical_payload_is_served_from_cache(cfg, tmp_path):
    calls: list = []
    model = fake(cfg, '{"items": ["甲"]}', calls, cache_dir=tmp_path / "cache")
    first = model("aggregate_split", {"text": "same"})
    second = model("aggregate_split", {"text": "same"})
    assert first == second
    assert len(calls) == 1
    assert model.call_count == 1
    assert [entry["cache_hit"] for entry in model.stage_log] == [False, True]
    assert model.summary()["cache_hits"] == 1


def test_changed_payload_misses_the_cache(cfg, tmp_path):
    calls: list = []
    model = fake(cfg, '{"items": ["甲"]}', calls, cache_dir=tmp_path / "cache")
    model("aggregate_split", {"text": "one"})
    model("aggregate_split", {"text": "two"})
    assert len(calls) == 2


def test_cache_does_not_leak_between_stages(cfg, tmp_path):
    calls: list = []
    model = fake(cfg, '{"items": []}', calls, cache_dir=tmp_path / "cache")
    model("aggregate_split", {"text": "same"})
    fake(cfg, '{"ratings": []}', calls, cache_dir=tmp_path / "cache")("rank", {"text": "same"})
    assert len(calls) == 2


def test_timeout_is_retried_then_raised(cfg):
    calls: list = []
    cfg["planner"]["max_retries"] = 1
    model = fake(cfg, "", calls, error=TimeoutError("gateway stalled"))
    with pytest.raises(ValueError, match="failed after 2 attempt"):
        model("aggregate_split", {"text": "x"})
    assert len(calls) == 2
    assert [entry["retries"] for entry in model.stage_log] == [0, 1]
    assert all("TimeoutError" in entry["error"] for entry in model.stage_log)
    assert model.summary()["failures"] == 2


def test_usage_is_recorded_when_the_provider_reports_it(cfg):
    calls: list = []
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    model = fake(cfg, '{"items": ["甲"]}', calls, usage=usage)
    assert model("aggregate_split", {"text": "x"}) == {"items": ["甲"]}
    assert model.stage_log[0]["usage"] == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}


def test_usage_is_null_when_the_provider_sends_none(cfg):
    calls: list = []
    model = fake(cfg, '{"items": []}', calls)
    model("aggregate_split", {"text": "x"})
    assert model.stage_log[0]["usage"] is None


def test_missing_credentials_fail_closed(cfg, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        fake(cfg, "{}", [])("aggregate_split", {})


def test_missing_model_fails_closed(cfg):
    cfg["planner"]["model"] = ""
    with pytest.raises(ValueError, match="planner.model"):
        fake(cfg, "{}", [])("aggregate_split", {})


def test_no_cache_dir_means_no_cache(cfg):
    calls: list = []
    model = fake(cfg, '{"items": []}', calls)
    model("aggregate_split", {"text": "same"})
    model("aggregate_split", {"text": "same"})
    assert len(calls) == 2
    assert json.loads(json.dumps(model.summary()))["calls"] == 2
