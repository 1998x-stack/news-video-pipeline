from pathlib import Path

import pytest

from news_video_pipeline.planner import heuristic_plan, read_input, sentences


def test_sentences_keeps_decimal():
    assert sentences("增长31.2%。PMI有变化。") == ["增长31.2%。", "PMI有变化。"]


def test_never_silently_truncate():
    with pytest.raises(ValueError, match="increase config"):
        heuristic_plan("标题", "第一段。\n\n第二段。\n\n第三段。", 40, 2)


def test_input_json(tmp_path: Path):
    source = tmp_path / "a.json"
    source.write_text('{"title":"标题","body":"正文。"}', encoding="utf-8")
    assert read_input(source) == ("标题", "正文。")


def test_empty_input_rejected(tmp_path: Path):
    source = tmp_path / "x.txt"
    source.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        read_input(source)
