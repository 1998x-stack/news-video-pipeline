"""Grounding + gateway-control tests for the optional LLM planner.

These tests never call a network API: `planner._openai_client` is replaced with a
fake OpenAI-compatible client.
"""
import json
from types import SimpleNamespace

import pytest

from news_video_pipeline import planner
from news_video_pipeline.config import load_config
from news_video_pipeline.models import Scene
from news_video_pipeline.planner import (assert_grounded, collect_stream, grounding_report, llm_plan,
                                         pack_narration, read_input, sentences)

SOURCE = (
    "国家统计局今天发布数据，前三季度国内生产总值同比增长5.2%。"
    "其中第三季度增长4.8%，服务业增加值同比增长5.4%。"
)

NARRATION = [
    "今天发布的数据显示经济运行总体平稳",
    "生产需求持续恢复就业物价总体稳定",
    "高质量发展取得新进展创新动能不断增强",
    "市场预期有所改善企业信心逐步回升",
    "重点行业稳步增长结构优化持续深入",
    "新型消费加快成长服务需求加快释放",
    "基础设施投资保持增长民生保障有力",
    "全年发展目标有望实现势头良好",
]
LONG_SOURCE = "。".join(NARRATION) + "。"


def llm_config(**overrides):
    cfg = load_config()
    cfg["planner"]["provider"] = "openai-compatible"
    cfg["planner"]["model"] = "test-model"
    cfg["planner"].update(overrides)
    return cfg


def chunk(content=None, reasoning=None):
    delta = SimpleNamespace(content=content, reasoning=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


class FakeClient:
    """Minimal stand-in for openai.OpenAI tracking the last request body."""

    def __init__(self, chunks, captured):
        self._chunks = chunks
        self._captured = captured
        outer = self

        class Completions:
            def create(self, **kwargs):
                outer._captured.update(kwargs)
                return iter(outer._chunks)

        class Chat:
            completions = Completions()

        self.chat = Chat()


def install(monkeypatch, chunks, captured):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(planner, "_openai_client", lambda config: FakeClient(chunks, captured))
    return captured


def json_chunks(payload_text):
    return [chunk(content=payload_text[:20]), chunk(content=payload_text[20:])]


# ---------------------------------------------------------------- grounding

def test_faithful_copy_is_grounded():
    scenes = [Scene("scene_001", "统计", SOURCE, (SOURCE,))]
    report = assert_grounded(SOURCE, scenes, 0.75)
    assert report["coverage"] > 0.95
    assert report["invented_tokens"] == []


def test_invented_number_is_rejected():
    scenes = [Scene("scene_001", "统计", "", ("前三季度国内生产总值同比增长6.1%。",))]
    assert grounding_report(SOURCE, scenes)["invented_tokens"] == ["6.1"]
    with pytest.raises(ValueError, match="absent from the source"):
        assert_grounded(SOURCE, scenes, 0.75)


def test_wholesale_invention_is_rejected_by_coverage():
    scenes = [Scene("scene_001", "无关", "", ("今天天气很好，我们一起出去散步吧。",))]
    with pytest.raises(ValueError, match="min_source_coverage"):
        assert_grounded(SOURCE, scenes, 0.75)


def test_grounding_ignores_punctuation_and_spacing():
    rewritten = "国家统计局发布数据，前三季度国内生产总值同比增长 5.2%。"
    scenes = [Scene("scene_001", "统计", "", (rewritten,))]
    report = grounding_report(SOURCE, scenes)
    assert report["invented_tokens"] == []
    assert report["coverage"] > 0.6


# ---------------------------------------------------------------- llm_plan

def test_pack_narration_never_exceeds_the_slide_budget():
    pieces = ["x" * 300 + "，" + "y" * 40, "短句。"]
    groups = pack_narration(pieces, 125)
    assert all(len("".join(group)) <= 125 for group in groups)
    assert "".join("".join(group) for group in groups) == "".join(pieces)


def test_heuristic_plan_splits_a_single_overlong_sentence():
    from news_video_pipeline.planner import heuristic_plan

    body = "这是一个很长的句子" * 30 + "，" + "另一段内容" * 20 + "。"
    scenes = heuristic_plan("标题", body, 125, 50)
    assert len(scenes) > 1
    assert all(len(scene.body) <= 125 for scene in scenes)
    assert "".join(sentence for scene in scenes for sentence in scene.sentences) == body


def test_scene_title_is_bounded_for_the_heading_box():
    from news_video_pipeline.planner import TITLE_LIMIT, heuristic_plan

    scenes = heuristic_plan("标题", "甲" * 200 + "。甲。", 125, 10)
    assert all(len(scene.title) <= TITLE_LIMIT + 1 for scene in scenes)


# ---------------------------------------------------------------- llm scene contract

def _long_payload(sentences=None, title="经济数据"):
    chunks = sentences if sentences is not None else [s + "。" for s in NARRATION]
    body = "".join(chunks)
    return json.dumps({"scenes": [{"title": title, "body": body, "sentences": chunks}]}, ensure_ascii=False)


def test_llm_scenes_are_regrouped_to_the_slide_contract(monkeypatch):
    """A model ignoring the length instruction must not overflow the slide layout."""
    install(monkeypatch, json_chunks(_long_payload()), {})
    scenes = llm_plan("标题", LONG_SOURCE, llm_config(max_chars_per_scene=125))
    assert len(scenes) >= 2
    assert all(len(scene.body) <= 125 for scene in scenes)
    assert all(len(scene.title) <= 41 for scene in scenes)
    delivered = "".join(sentence for scene in scenes for sentence in scene.sentences)
    assert delivered == LONG_SOURCE, "regrouping must never drop or reword narration"
    assert scenes[0].title == "经济数据"
    assert scenes[1].title == scenes[1].sentences[0], "continuation scenes derive a heading from their first sentence"


def test_llm_regrouping_fails_when_scene_ceiling_is_reached(monkeypatch):
    install(monkeypatch, json_chunks(_long_payload()), {})
    with pytest.raises(ValueError, match="raise planner.max_scenes"):
        llm_plan("标题", LONG_SOURCE, llm_config(max_chars_per_scene=60, max_scenes=1))


def test_llm_plan_accepts_valid_json_and_sends_gateway_controls(monkeypatch):
    payload = '{"scenes":[{"title":"统计发布","body":"x","sentences":["国家统计局今天发布数据，前三季度国内生产总值同比增长5.2%。"]}]}'
    captured = install(monkeypatch, json_chunks(payload), {})
    scenes = llm_plan("标题", SOURCE, llm_config(max_tokens=4321, reasoning_effort="none"))
    assert [s.id for s in scenes] == ["scene_001"]
    assert captured["stream"] is True
    assert captured["max_tokens"] == 4321
    assert captured["reasoning_effort"] == "none"
    assert captured["model"] == "test-model"


def test_llm_plan_omits_reasoning_effort_when_unset(monkeypatch):
    payload = '{"scenes":[{"title":"t","body":"b","sentences":["国家统计局今天发布数据。"]}]}'
    captured = install(monkeypatch, json_chunks(payload), {})
    llm_plan("标题", SOURCE, llm_config(reasoning_effort=""))
    assert "reasoning_effort" not in captured


def test_llm_plan_reports_reasoning_only_response(monkeypatch):
    install(monkeypatch, [chunk(reasoning="thinking"), chunk(reasoning="more")], {})
    with pytest.raises(ValueError, match="no content"):
        llm_plan("标题", SOURCE, llm_config())


def test_llm_plan_rejects_non_json(monkeypatch):
    install(monkeypatch, json_chunks("```json\n{}\n```"), {})
    with pytest.raises(ValueError, match="valid JSON"):
        llm_plan("标题", SOURCE, llm_config())


def test_llm_plan_rejects_scene_overflow_without_truncating(monkeypatch):
    scene = '{"title":"t","body":"b","sentences":["国家统计局今天发布数据。"]}'
    install(monkeypatch, json_chunks('{"scenes":[' + ",".join([scene] * 3) + "]}"), {})
    with pytest.raises(ValueError, match="max_scenes=2"):
        llm_plan("标题", SOURCE, llm_config(max_scenes=2))


def test_llm_plan_rejects_empty_sentences(monkeypatch):
    install(monkeypatch, json_chunks('{"scenes":[{"title":"t","body":"b","sentences":["  "]}]}'), {})
    with pytest.raises(ValueError, match="narration sentences"):
        llm_plan("标题", SOURCE, llm_config())


def test_llm_plan_fails_closed_on_invented_fact(monkeypatch):
    payload = '{"scenes":[{"title":"t","body":"b","sentences":["前三季度国内生产总值同比增长6.1%。"]}]}'
    install(monkeypatch, json_chunks(payload), {})
    with pytest.raises(ValueError, match="absent from the source"):
        llm_plan("标题", SOURCE, llm_config())


def test_llm_plan_requires_credentials(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        llm_plan("标题", SOURCE, llm_config())


def test_missing_optional_sdk_raises_an_install_hint(monkeypatch):
    """The offline suite must run with only the `test` extra installed."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("openai is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(RuntimeError, match=r"pip install '\.\[llm\]'"):
        planner._openai_client(llm_config())


def test_collect_stream_enforces_a_wall_clock_deadline():
    ticks = iter([0.0, 1.0, 999.0])
    with pytest.raises(TimeoutError, match="max_total_s"):
        collect_stream([chunk(content="a"), chunk(content="b")], max_total_s=10,
                       clock=lambda: next(ticks))


def test_collect_stream_without_deadline_still_joins_content():
    assert collect_stream([chunk(content="甲"), chunk(reasoning="hidden"), chunk(content="乙")]) == "甲乙"


# ---------------------------------------------------------------- config gate

@pytest.mark.parametrize("overrides", [
    {"timeout_s": 0},
    {"max_total_s": 0},
    {"max_tokens": 8},
    {"max_retries": -1},
    {"min_source_coverage": 0},
    {"min_source_coverage": 1.5},
])
def test_invalid_gateway_config_is_rejected(tmp_path, overrides):
    import yaml

    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump({"planner": overrides}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)


# ---------------------------------------------------------------- existing behaviour

def test_sentences_keeps_decimal():
    assert sentences("增长31.2%。PMI有变化。") == ["增长31.2%。", "PMI有变化。"]


def test_never_silently_truncate():
    from news_video_pipeline.planner import heuristic_plan

    with pytest.raises(ValueError, match="raise planner.max_scenes"):
        heuristic_plan("标题", "第一段。\n\n第二段。\n\n第三段。", 40, 2)


def test_input_json(tmp_path):
    source = tmp_path / "a.json"
    source.write_text('{"title":"标题","body":"正文。"}', encoding="utf-8")
    assert read_input(source) == ("标题", "正文。")


def test_empty_input_rejected(tmp_path):
    source = tmp_path / "x.txt"
    source.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        read_input(source)
