import pytest

from news_video_pipeline.timeline import srt_time, validate_timeline


def test_srt_format():
    assert srt_time(3_723_004) == "01:02:03,004"


def test_contiguous_timeline():
    data = {"duration_ms": 2000, "scenes": [
        {"id": "s1", "slide_index": 1, "start_ms": 0, "end_ms": 1000},
        {"id": "s2", "slide_index": 2, "start_ms": 1000, "end_ms": 2000}],
        "cues": [{"scene_id": "s1", "start_ms": 0, "end_ms": 750},
                 {"scene_id": "s2", "start_ms": 1000, "end_ms": 1900}]}
    validate_timeline(data, 2)
    data["cues"][1]["start_ms"] = 700
    with pytest.raises(ValueError):
        validate_timeline(data, 2)
