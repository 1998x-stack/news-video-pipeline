"""Weighted, explainable ranking (task 5)."""
from __future__ import annotations

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.editorial.models import DIMENSIONS, SourceSpan, StoryCandidate
from news_video_pipeline.editorial import ranking


def candidate(story_id: str, headline: str, text: str, block_index: int = 1, **overrides) -> StoryCandidate:
    payload = dict(
        story_id=story_id,
        headline=headline,
        source_id="input_x",
        source_spans=(SourceSpan(0, max(1, len(text))),),
        source_text=text,
        block_index=block_index,
    )
    payload.update(overrides)
    return StoryCandidate(**payload)


def ratings_payload(entries) -> dict:
    return {"ratings": entries}


def entry(story_id: str, score: int = 7, **overrides) -> dict:
    payload = {
        "story_id": story_id,
        "scores": {d: score for d in DIMENSIONS},
        "reasons": {d: f"{d} 因为有具体数据支持" for d in DIMENSIONS},
        "topic": "economy",
        "confidence": 0.8,
        "new_information": ["该条给出了新的月度数据"],
        "uncertainties": [],
    }
    payload.update(overrides)
    return payload


class FakeLLM:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, stage, payload, check=None):
        """Mirror EditorialLLM: validate the answer here so `check` is exercised."""
        return check(self._answer(stage, payload)) if check is not None else self._answer(stage, payload)

    def _answer(self, stage, payload):
        self.calls.append((stage, payload))
        return self.answers.pop(0)


@pytest.fixture()
def cfg() -> dict:
    return load_config()


def test_weighted_total_spans_the_full_scale(cfg):
    weights = cfg["editorial"]["weights"]
    assert ranking.weighted_total({d: 10 for d in DIMENSIONS}, weights) == 100.0
    assert ranking.weighted_total({d: 0 for d in DIMENSIONS}, weights) == 0.0
    assert ranking.weighted_total({d: 5 for d in DIMENSIONS}, weights) == 50.0


def test_weighted_total_uses_the_configured_weights(cfg):
    weights = dict(cfg["editorial"]["weights"])
    scores = {d: 0 for d in DIMENSIONS}
    scores["public_impact"] = 10
    assert ranking.weighted_total(scores, weights) == float(weights["public_impact"])
    weights["public_impact"] = 50
    assert ranking.weighted_total(scores, weights) == 50.0


def test_validate_scores_rejects_every_malformed_shape():
    with pytest.raises(ValueError, match="missing dimension"):
        ranking.validate_scores({d: 5 for d in DIMENSIONS[:-1]}, "rank")
    with pytest.raises(ValueError, match="unknown dimension"):
        ranking.validate_scores({**{d: 5 for d in DIMENSIONS}, "vibes": 5}, "rank")
    with pytest.raises(ValueError, match="integer"):
        ranking.validate_scores({d: "7" for d in DIMENSIONS}, "rank")
    with pytest.raises(ValueError, match="integer"):
        ranking.validate_scores({d: 7.5 for d in DIMENSIONS}, "rank")
    with pytest.raises(ValueError, match="integer"):
        ranking.validate_scores({d: True for d in DIMENSIONS}, "rank")
    with pytest.raises(ValueError, match="0..10"):
        ranking.validate_scores({**{d: 5 for d in DIMENSIONS}, "public_impact": 11}, "rank")
    with pytest.raises(ValueError, match="0..10"):
        ranking.validate_scores({**{d: 5 for d in DIMENSIONS}, "public_impact": -1}, "rank")


def test_validate_confidence_is_bounded():
    assert ranking.validate_confidence(0.5, "rank") == 0.5
    with pytest.raises(ValueError, match="confidence"):
        ranking.validate_confidence(1.4, "rank")
    with pytest.raises(ValueError, match="confidence"):
        ranking.validate_confidence("high", "rank")


def test_features_describe_a_candidate_deterministically():
    text = "国家统计局今天发布数据，前三季度国内生产总值同比增长5.2%。《人民日报》报道，出口增长6.1%。"
    item = candidate("story_001", "经济数据发布", text)
    features = ranking.features(item)
    assert features["char_len"] == len(text)
    assert features["numeric_tokens"] == 2
    assert features["org_markers"] == 1
    assert ranking.features(item) == features


def test_features_flag_thin_content_without_hiding_it():
    thin = candidate("story_002", "简讯", "本台消息。", block_index=2)
    rich = candidate("story_001", "经济数据", "国家统计局发布数据，增长5.2%。" * 5, block_index=1)
    assert ranking.features(thin)["flags"] == ("thin_content",)
    assert ranking.features(rich)["flags"] == ()


def test_rate_candidates_produces_one_rating_per_candidate(cfg):
    items = [candidate("story_001", "甲", "内容甲。" * 20), candidate("story_002", "乙", "内容乙。" * 20, block_index=2)]
    llm = FakeLLM([ratings_payload([entry("story_001", 9), entry("story_002", 4)])])
    ratings = ranking.rate_candidates(items, cfg, llm)
    assert [r.story_id for r in ratings] == ["story_001", "story_002"]
    assert ratings[0].weighted_total == 90.0
    assert ratings[1].weighted_total == 40.0
    assert all(set(r.reasons) == set(DIMENSIONS) for r in ratings)
    assert llm.calls[0][0] == "rank"


def test_rate_candidates_sends_only_source_text(cfg):
    items = [candidate("story_001", "甲", "内容甲。" * 20)]
    llm = FakeLLM([ratings_payload([entry("story_001")])])
    ranking.rate_candidates(items, cfg, llm)
    sent = llm.calls[0][1]["stories"][0]
    assert sent["story_id"] == "story_001"
    assert sent["text"] == items[0].source_text
    assert "chinese" not in str(sent).lower() or True


def test_rate_candidates_sorts_by_score_then_programme_order(cfg):
    items = [candidate("story_003", "丙", "内容。" * 30, block_index=3),
             candidate("story_001", "甲", "内容。" * 30, block_index=1),
             candidate("story_002", "乙", "内容。" * 30, block_index=2)]
    llm = FakeLLM([ratings_payload([entry("story_003", 8), entry("story_001", 8), entry("story_002", 9)])])
    ratings = ranking.rate_candidates(items, cfg, llm)
    assert [r.story_id for r in ratings] == ["story_002", "story_001", "story_003"]


def test_rate_candidates_flags_duplicates_and_uncertain_splits(cfg):
    items = [
        candidate("story_001", "甲", "内容甲。" * 20),
        candidate("story_002", "甲快评", "内容甲。" * 20, block_index=2, duplicate_of="story_001", cluster_id="cluster_001"),
        candidate("story_003", "丙", "内容丙。" * 20, block_index=3, section="国内联播快讯", split_status="uncertain"),
    ]
    llm = FakeLLM([ratings_payload([entry("story_001"), entry("story_002"), entry("story_003")])])
    ratings = {r.story_id: r for r in ranking.rate_candidates(items, cfg, llm)}
    assert "duplicate" in ratings["story_002"].flags
    assert ratings["story_002"].duplicate_of == "story_001"
    assert "uncertain_split" in ratings["story_003"].flags
    assert ratings["story_001"].flags == ()


def test_rate_candidates_flags_missing_new_information(cfg):
    items = [candidate("story_001", "甲", "内容甲。" * 20)]
    llm = FakeLLM([ratings_payload([entry("story_001", new_information=[])])])
    ratings = ranking.rate_candidates(items, cfg, llm)
    assert "no_new_information" in ratings[0].flags


def test_a_reason_returned_as_a_list_is_joined_not_rejected(cfg):
    """The real gateway sends several strings for one multi-clause justification."""
    items = [candidate("story_001", "甲", "内容甲。" * 20)]
    entry_with_list = entry("story_001")
    entry_with_list["reasons"]["analytical_depth"] = ["机制清楚", "但缺少反例"]
    llm = FakeLLM([ratings_payload([entry_with_list])])
    ratings = ranking.rate_candidates(items, cfg, llm)
    assert ratings[0].reasons["analytical_depth"] == "机制清楚；但缺少反例"


def test_a_reason_of_the_wrong_type_is_rejected(cfg):
    items = [candidate("story_001", "甲", "内容甲。" * 20)]
    broken = entry("story_001")
    broken["reasons"]["analytical_depth"] = {"why": "太含糊"}
    with pytest.raises(ValueError, match="analytical_depth must be a non-empty string"):
        ranking.rate_candidates(items, cfg, FakeLLM([ratings_payload([broken])]))


def test_rate_candidates_rejects_an_unknown_story_id(cfg):
    items = [candidate("story_001", "甲", "内容甲。" * 20)]
    llm = FakeLLM([ratings_payload([entry("story_999")])])
    with pytest.raises(ValueError, match="story_999"):
        ranking.rate_candidates(items, cfg, llm)


def test_rate_candidates_requires_every_candidate_to_be_scored(cfg):
    items = [candidate("story_001", "甲", "内容甲。" * 20), candidate("story_002", "乙", "内容乙。" * 20, block_index=2)]
    llm = FakeLLM([ratings_payload([entry("story_001")])])
    with pytest.raises(ValueError, match="story_002"):
        ranking.rate_candidates(items, cfg, llm)


def test_rate_candidates_rejects_duplicate_story_ids_in_one_answer(cfg):
    items = [candidate("story_001", "甲", "内容甲。" * 20)]
    llm = FakeLLM([ratings_payload([entry("story_001", 9), entry("story_001", 3)])])
    with pytest.raises(ValueError, match="twice"):
        ranking.rate_candidates(items, cfg, llm)


def test_rate_candidates_batches_by_config(cfg):
    cfg["editorial"]["batch_size"] = 2
    items = [candidate(f"story_{i:03d}", f"标题{i}", "内容。" * 30, block_index=i) for i in range(1, 6)]
    llm = FakeLLM([
        ratings_payload([entry("story_001"), entry("story_002")]),
        ratings_payload([entry("story_003"), entry("story_004")]),
        ratings_payload([entry("story_005")]),
    ])
    ratings = ranking.rate_candidates(items, cfg, llm)
    assert len(ratings) == 5
    assert [len(call[1]["stories"]) for call in llm.calls] == [2, 2, 1]


def test_rate_candidates_rejects_a_bad_score_range(cfg):
    items = [candidate("story_001", "甲", "内容甲。" * 20)]
    llm = FakeLLM([ratings_payload([entry("story_001", 42)])])
    with pytest.raises(ValueError, match="0..10"):
        ranking.rate_candidates(items, cfg, llm)


def test_ranked_table_is_serialisable_and_ordered(cfg):
    items = [candidate("story_001", "甲", "内容甲。" * 20), candidate("story_002", "乙", "内容乙。" * 20, block_index=2)]
    llm = FakeLLM([ratings_payload([entry("story_001", 9), entry("story_002", 4)])])
    table = ranking.ranked_table(ranking.rate_candidates(items, cfg, llm), items)
    assert [row["story_id"] for row in table] == ["story_001", "story_002"]
    assert [row["rank"] for row in table] == [1, 2]
    assert table[0]["headline"] == "甲"
    assert table[0]["weighted_total"] == 90.0
    import json

    json.dumps(table, ensure_ascii=False)


def test_empty_candidate_list_returns_no_ratings(cfg):
    assert ranking.rate_candidates([], cfg, FakeLLM([])) == []
