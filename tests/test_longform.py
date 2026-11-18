
"""Deterministic longform and hard-timeout regression coverage."""
import json
import time
from types import SimpleNamespace

import pytest

from news_video_pipeline import planner
from news_video_pipeline.config import load_config
from news_video_pipeline.models import Scene


def test_source_chunks_keep_every_character_and_prefer_punctuation():
    original = "甲" * 75 + "。" + "乙" * 75 + "\n" + "丙" * 37
    chunks = planner.split_source_chunks(original, 100)
    assert len(chunks) >= 2
    assert chunks[0].endswith("。")
    assert "".join(chunks) == original
    assert max(map(len, chunks)) <= 100


def test_source_chunks_hard_split_without_punctuation():
    body = "abc" * 107
    chunks = planner.split_source_chunks(body, 80)
    assert "".join(chunks) == body
    assert all(len(c) <= 80 for c in chunks)


def test_longform_calls_each_chunk_and_renumbers(monkeypatch):
    body = "甲" * 75 + "。" + "乙" * 75 + "。" + "丙" * 75 + "。"
    cfg = load_config()
    cfg["planner"].update(provider="openai-compatible", chunk_chars=90, max_chunks=8,
                          max_scenes=12, chunk_min_retention=1.0)
    calls = []

    def fake_one(title, part, config):
        calls.append(part)
        return [Scene("scene_001", "片段", part, (part,))]

    monkeypatch.setattr(planner, "_llm_plan_one", fake_one)
    scenes = planner.llm_plan("新闻", body, cfg)
    assert "".join(calls) == body
    assert len(calls) > 1
    assert [s.id for s in scenes] == [f"scene_{i:03d}" for i in range(1, len(scenes) + 1)]
    assert "".join(s.body for s in scenes) == body


def test_longform_dropped_number_fails_closed(monkeypatch):
    body = ("甲" * 70 + "，增长5.2%。" + "乙" * 70 + "，增长4.8%。")
    cfg = load_config()
    cfg["planner"].update(provider="openai-compatible", chunk_chars=90,
                          max_scenes=10, chunk_min_retention=0.5)
    def fake_one(title, part, config):
        # Omit one numerical statement while retaining most characters
        out = part.replace("5.2", "").replace("4.8", "")
        return [Scene("scene_001", "t", out, (out,))]
    monkeypatch.setattr(planner, "_llm_plan_one", fake_one)
    with pytest.raises(ValueError, match="omitted source numeric"):
        planner.llm_plan("t", body, cfg)


def test_longform_fails_before_paid_call_if_too_many_chunks(monkeypatch):
    cfg = load_config()
    cfg["planner"].update(provider="openai-compatible", chunk_chars=64, max_chunks=1)
    monkeypatch.setattr(planner, "_llm_plan_one",
                        lambda *a: pytest.fail("should not make paid call"))
    with pytest.raises(ValueError, match="max_chunks"):
        planner.llm_plan("t", "甲" * 200, cfg)


def test_longform_rejects_missing_body_segments(monkeypatch):
    cfg = load_config()
    cfg["planner"].update(provider="openai-compatible", chunk_chars=90,
                          max_scenes=20, chunk_min_retention=0.8)
    monkeypatch.setattr(planner, "_llm_plan_one",
                        lambda title, part, config: [Scene("s", "t", "甲", ("甲",))])
    with pytest.raises(ValueError, match="source retention"):
        planner.llm_plan("t", "甲" * 260, cfg)


def test_hard_deadline_interrupts_blocking_operation():
    with pytest.raises(TimeoutError, match="max_total_s"):
        with planner.hard_deadline(0.03):
            time.sleep(0.25)


def test_hard_deadline_restores_previous_handler():
    import signal
    previous = signal.getsignal(signal.SIGALRM)
    with planner.hard_deadline(0.5):
        pass
    assert signal.getsignal(signal.SIGALRM) == previous


@pytest.mark.parametrize("bad", [
    {"chunk_chars": -1}, {"chunk_chars": 32},
    {"max_chunks": 0}, {"chunk_min_retention": 0},
    {"chunk_min_retention": 1.1}
])
def test_invalid_longform_config(tmp_path, bad):
    import yaml
    config = tmp_path / "invalid.yaml"
    config.write_text(yaml.safe_dump({"planner": bad}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(config)
