"""Two-stage editorial selection with a complete audit trail (task 6)."""
from __future__ import annotations

import json

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.editorial import ranking, selection
from news_video_pipeline.editorial.models import DIMENSIONS, SourceSpan, StoryCandidate, StoryRating


def candidate(story_id: str, headline: str, block_index: int, topic: str = "", **overrides) -> StoryCandidate:
    payload = dict(
        story_id=story_id,
        headline=headline,
        source_id="input_x",
        source_spans=(SourceSpan(block_index * 10, block_index * 10 + 40),),
        source_text=f"{headline}的正文内容，包含具体数据。" * 3,
        block_index=block_index,
        topic=topic,
    )
    payload.update(overrides)
    return StoryCandidate(**payload)


def rating(story_id: str, total: float, topic: str = "economy", confidence: float = 0.8, **overrides) -> StoryRating:
    payload = dict(
        story_id=story_id,
        scores={d: int(total / 10) for d in DIMENSIONS},
        reasons={d: "理由" for d in DIMENSIONS},
        weighted_total=total,
        topic=topic,
        confidence=confidence,
    )
    payload.update(overrides)
    return StoryRating(**payload)


class FakeLLM:
    def __init__(self, comparisons, fail_stage: str | None = None):
        self.comparisons = comparisons
        self.fail_stage = fail_stage
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, stage, payload, check=None):
        """Mirror EditorialLLM: validate the answer here so `check` is exercised."""
        return check(self._answer(stage, payload)) if check is not None else self._answer(stage, payload)

    def _answer(self, stage, payload):
        self.calls.append((stage, payload))
        if stage == self.fail_stage:
            raise AssertionError(f"stage {stage} must not be called")
        return {"comparisons": self.comparisons}


def comparison(story_id: str, **overrides) -> dict:
    payload = {"story_id": story_id, "same_event_as": None, "repeat_without_progress": False,
               "adjustment": 0, "note": "与原文一致", "evidence_gap": False}
    payload.update(overrides)
    return payload


@pytest.fixture()
def cfg() -> dict:
    return load_config()


def test_shortlist_takes_the_best_by_effective_total(cfg):
    ratings = [rating("story_001", 90.0), rating("story_002", 40.0), rating("story_003", 70.0)]
    assert [r.story_id for r in selection.shortlist(ratings, 2)] == ["story_001", "story_003"]


def test_compare_validates_every_shortlisted_story_is_answered(cfg):
    items = [candidate("story_001", "甲", 1), candidate("story_002", "乙", 2)]
    llm = FakeLLM([comparison("story_001")])
    with pytest.raises(ValueError, match="story_002"):
        selection.compare([rating("story_001", 90.0), rating("story_002", 80.0)], items, cfg, llm)


def test_compare_rejects_an_unknown_story_id(cfg):
    items = [candidate("story_001", "甲", 1)]
    llm = FakeLLM([comparison("story_001", same_event_as="story_404")])
    with pytest.raises(ValueError, match="story_404"):
        selection.compare([rating("story_001", 90.0)], items, cfg, llm)


def test_compare_bounds_the_adjustment(cfg):
    items = [candidate("story_001", "甲", 1)]
    llm = FakeLLM([comparison("story_001", adjustment=99)])
    with pytest.raises(ValueError, match="adjustment"):
        selection.compare([rating("story_001", 90.0)], items, cfg, llm)


def test_compare_rejects_a_non_boolean_flag(cfg):
    items = [candidate("story_001", "甲", 1)]
    llm = FakeLLM([comparison("story_001", evidence_gap="yes")])
    with pytest.raises(ValueError, match="evidence_gap"):
        selection.compare([rating("story_001", 90.0)], items, cfg, llm)


def test_select_never_exceeds_top_k(cfg):
    cfg["editorial"].update({"top_k": 3, "min_candidates": 1, "shortlist": 8, "min_total_score": 0})
    items = [candidate(f"story_{i:03d}", f"标题{i}", i) for i in range(1, 8)]
    ratings = [rating(f"story_{i:03d}", 90.0 - i, topic=f"topic_{i}") for i in range(1, 8)]
    llm = FakeLLM([comparison(f"story_{i:03d}") for i in range(1, 8)])
    result = selection.select(items, ratings, cfg, llm)
    assert len(result.selected) == 3
    assert result.selected == ("story_001", "story_002", "story_003")


def test_select_never_takes_a_duplicate(cfg):
    cfg["editorial"].update({"top_k": 2, "min_candidates": 1, "min_total_score": 0})
    items = [
        candidate("story_001", "甲", 1, topic="a"),
        candidate("story_002", "甲快评", 2, topic="b", duplicate_of="story_001", cluster_id="c1"),
        candidate("story_003", "丙", 3, topic="c"),
    ]
    ratings = [rating("story_001", 80.0, topic="a"), rating("story_002", 95.0, topic="b"), rating("story_003", 70.0, topic="c")]
    llm = FakeLLM([comparison("story_001"), comparison("story_002"), comparison("story_003")])
    result = selection.select(items, ratings, cfg, llm)
    assert "story_002" not in result.selected
    assert {"story_001", "story_003"} == set(result.selected)
    rejected = {row["story_id"]: row for row in result.rejected}
    assert rejected["story_002"]["duplicate"] is True


def test_select_demotes_the_lower_scored_side_of_a_compare_duplicate(cfg):
    cfg["editorial"].update({"top_k": 2, "min_candidates": 1, "min_total_score": 0})
    items = [candidate("story_001", "甲", 1, topic="a"), candidate("story_002", "乙", 2, topic="b")]
    ratings = [rating("story_001", 90.0, topic="a"), rating("story_002", 60.0, topic="b")]
    llm = FakeLLM([comparison("story_001", same_event_as="story_002"), comparison("story_002", same_event_as="story_001")])
    result = selection.select(items, ratings, cfg, llm)
    assert result.selected == ("story_001",)


def test_select_rejects_below_threshold_with_a_reason(cfg):
    cfg["editorial"].update({"top_k": 3, "min_candidates": 1, "min_total_score": 55})
    items = [candidate("story_001", "甲", 1, topic="a"), candidate("story_002", "乙", 2, topic="b")]
    ratings = [rating("story_001", 80.0, topic="a"), rating("story_002", 40.0, topic="b")]
    llm = FakeLLM([comparison("story_001"), comparison("story_002")])
    result = selection.select(items, ratings, cfg, llm)
    assert result.selected == ("story_001",)
    rejected = {row["story_id"]: row for row in result.rejected}
    assert rejected["story_002"]["reason"] == "below_min_score"
    assert rejected["story_002"]["total"] == 40.0


def test_select_rejects_low_confidence_and_evidence_gaps(cfg):
    cfg["editorial"].update({"top_k": 5, "min_candidates": 1, "min_total_score": 0, "min_confidence": 0.5})
    items = [candidate("story_001", "甲", 1, topic="a"), candidate("story_002", "乙", 2, topic="b"),
             candidate("story_003", "丙", 3, topic="c"), candidate("story_004", "丁", 4, topic="d")]
    ratings = [rating("story_001", 90.0, topic="a"), rating("story_002", 88.0, topic="b", confidence=0.2),
               rating("story_003", 86.0, topic="c"), rating("story_004", 84.0, topic="d")]
    llm = FakeLLM([comparison("story_001"), comparison("story_002"), comparison("story_003", evidence_gap=True),
                   comparison("story_004")])
    result = selection.select(items, ratings, cfg, llm)
    rejected = {row["story_id"]: row for row in result.rejected}
    assert rejected["story_002"]["reason"] == "low_confidence"
    assert rejected["story_003"]["weak_evidence"] is True
    assert "story_003" not in result.selected


def test_select_rejects_a_repeat_without_progress(cfg):
    cfg["editorial"].update({"top_k": 5, "min_candidates": 1, "min_total_score": 0})
    items = [candidate("story_001", "甲", 1, topic="a"), candidate("story_002", "乙", 2, topic="b")]
    ratings = [rating("story_001", 90.0, topic="a"), rating("story_002", 85.0, topic="b")]
    llm = FakeLLM([comparison("story_001"), comparison("story_002", repeat_without_progress=True)])
    result = selection.select(items, ratings, cfg, llm)
    rejected = {row["story_id"]: row for row in result.rejected}
    assert result.selected == ("story_001",)
    assert rejected["story_002"]["low_novelty"] is True
    assert rejected["story_002"]["reason"] == "repeat_without_progress"


def test_select_reports_insufficiency_without_padding(cfg):
    cfg["editorial"].update({"top_k": 5, "min_candidates": 3, "min_total_score": 55})
    items = [candidate(f"story_{i:03d}", f"标题{i}", i, topic=f"t{i}") for i in range(1, 6)]
    ratings = [rating("story_001", 90.0, topic="t1"), rating("story_002", 70.0, topic="t2"),
               rating("story_003", 30.0, topic="t3"), rating("story_004", 20.0, topic="t4"),
               rating("story_005", 10.0, topic="t5")]
    llm = FakeLLM([comparison(f"story_{i:03d}") for i in range(1, 6)])
    result = selection.select(items, ratings, cfg, llm)
    assert result.insufficient is True
    assert len(result.selected) == 2
    assert any("insufficient" in note for note in result.notes)


def test_select_keeps_topic_diversity_while_good_candidates_last(cfg):
    cfg["editorial"].update({"top_k": 3, "min_candidates": 1, "min_total_score": 0, "max_topic_share": 0.4})
    items = [candidate(f"story_{i:03d}", f"标题{i}", i, topic=t)
             for i, t in enumerate(["economy", "economy", "economy", "diplomacy"], 1)]
    ratings = [rating("story_001", 90.0, topic="economy"), rating("story_002", 89.0, topic="economy"),
               rating("story_003", 88.0, topic="economy"), rating("story_004", 50.0, topic="diplomacy")]
    llm = FakeLLM([comparison(f"story_{i:03d}") for i in range(1, 5)])
    result = selection.select(items, ratings, cfg, llm)
    assert "story_004" in result.selected
    assert len(result.selected) == 3


def test_select_fills_up_when_only_one_topic_exists(cfg):
    cfg["editorial"].update({"top_k": 3, "min_candidates": 1, "min_total_score": 0, "max_topic_share": 0.4})
    items = [candidate(f"story_{i:03d}", f"标题{i}", i, topic="economy") for i in range(1, 5)]
    ratings = [rating(f"story_{i:03d}", 90.0 - i, topic="economy") for i in range(1, 5)]
    llm = FakeLLM([comparison(f"story_{i:03d}") for i in range(1, 5)])
    result = selection.select(items, ratings, cfg, llm)
    assert len(result.selected) == 3
    assert any("topic_concentration" in note for note in result.notes)


def test_every_candidate_appears_exactly_once_in_the_audit(cfg):
    cfg["editorial"].update({"top_k": 2, "min_candidates": 1, "min_total_score": 40})
    items = [candidate(f"story_{i:03d}", f"标题{i}", i, topic=f"t{i}") for i in range(1, 6)]
    ratings = [rating(f"story_{i:03d}", 90.0 - i * 10, topic=f"t{i}") for i in range(1, 6)]
    llm = FakeLLM([comparison(f"story_{i:03d}") for i in range(1, 6)])
    result = selection.select(items, ratings, cfg, llm)
    seen = list(result.selected) + [row["story_id"] for row in result.rejected]
    assert sorted(seen) == sorted(item.story_id for item in items)
    assert len(seen) == len(set(seen))


def test_selection_config_is_recorded_for_audit(cfg):
    cfg["editorial"].update({"top_k": 2, "min_candidates": 1, "min_total_score": 0, "max_topic_share": 0.6})
    items = [candidate("story_001", "甲", 1, topic="a")]
    llm = FakeLLM([comparison("story_001")])
    result = selection.select(items, [rating("story_001", 90.0, topic="a")], cfg, llm)
    assert result.selection_config["top_k"] == 2
    assert result.selection_config["weights"] == cfg["editorial"]["weights"]
    assert result.selection_config["min_total_score"] == 0
    assert json.loads(json.dumps(result.to_dict(), ensure_ascii=False))


def test_compare_is_only_called_for_the_shortlist(cfg):
    cfg["editorial"].update({"top_k": 2, "min_candidates": 1, "shortlist": 2, "min_total_score": 0})
    items = [candidate(f"story_{i:03d}", f"标题{i}", i, topic=f"t{i}") for i in range(1, 5)]
    ratings = [rating(f"story_{i:03d}", 90.0 - i, topic=f"t{i}") for i in range(1, 5)]
    llm = FakeLLM([comparison("story_001"), comparison("story_002")])
    selection.select(items, ratings, cfg, llm)
    sent = {row["story_id"] for row in llm.calls[0][1]["candidates"]}
    assert sent == {"story_001", "story_002"}


def test_empty_ratings_report_insufficient(cfg):
    result = selection.select([], [], cfg, FakeLLM([]))
    assert result.selected == ()
    assert result.insufficient is True
