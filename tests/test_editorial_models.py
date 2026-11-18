"""Editorial data contracts and configuration (task 1 of the implementation plan)."""
from __future__ import annotations

import copy

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.editorial.models import (
    CLAIM_KINDS,
    CRITIQUE_DIMENSIONS,
    DIMENSIONS,
    SCHEMA_VERSION,
    AnalysisBrief,
    Claim,
    EditorialSelection,
    EditorialScript,
    ScoreSet,
    SourceSpan,
    StoryCandidate,
)


def candidate(**overrides) -> StoryCandidate:
    base = dict(
        story_id="story_001",
        headline="政策发力显效 多项先行指标持续改善",
        source_id="input_20261114",
        source_spans=(SourceSpan(0, 12), SourceSpan(20, 30)),
        source_text="政策发力显效。多项先行指标持续改善。",
        block_index=1,
        section="",
        entities=("国家发展改革委",),
        topic="economy",
        event_time="2026-11-14",
        core_facts=("10月份工程机械开工率同比提高0.7个百分点",),
        new_information=("新型基础设施项目中标金额同比增长45.4%",),
        uncertainties=("未公布分省数据",),
        source_status="unverified",
        split_status="exact",
        cluster_id="c1",
        duplicate_of=None,
    )
    base.update(overrides)
    return StoryCandidate(**base)


def test_schema_version_is_pinned():
    assert SCHEMA_VERSION == 1


def test_candidate_round_trips_through_dict():
    original = candidate()
    restored = StoryCandidate.from_dict(original.to_dict())
    assert restored == original
    assert restored.source_spans[1] == SourceSpan(20, 30)
    assert isinstance(restored.source_spans, tuple)
    assert isinstance(restored.core_facts, tuple)


def test_candidate_to_dict_is_json_serialisable():
    import json

    payload = candidate().to_dict()
    json.dumps(payload, ensure_ascii=False)
    assert payload["source_spans"] == [{"start": 0, "end": 12}, {"start": 20, "end": 30}]
    assert payload["split_status"] == "exact"


def test_score_set_keeps_dimensions_complete():
    scores = ScoreSet(scores={d: 5 for d in DIMENSIONS}, reasons={d: "r" for d in DIMENSIONS})
    assert set(scores.scores) == set(DIMENSIONS)
    with pytest.raises(ValueError, match="missing"):
        ScoreSet(scores={d: 5 for d in DIMENSIONS[:-1]}, reasons={d: "r" for d in DIMENSIONS[:-1]})


def test_claim_round_trips_and_kinds_are_pinned():
    claim = Claim(
        claim_id="claim_001",
        story_id="story_001",
        kind="FACT",
        text="工程机械开工率同比提高0.7个百分点。",
        source_spans=(SourceSpan(0, 12),),
        depends_on=(),
        reasoning="节目稿直接给出的数字。",
        limitation="仅有全国口径。",
    )
    assert Claim.from_dict(claim.to_dict()) == claim
    assert CLAIM_KINDS == ("FACT", "INFERENCE", "OPINION", "UNKNOWN")
    with pytest.raises(ValueError, match="kind"):
        Claim(**{**claim.__dict__, "kind": "GUESS"})


def test_analysis_brief_and_script_round_trip():
    brief = AnalysisBrief(
        story_id="story_001",
        headline="政策发力显效",
        angle="先行指标回暖说明政策落地节奏加快",
        mechanisms=("专项债与项目开工的传导",),
        second_order=("就业与地方财政的滞后改善",),
        counterpoints=("单月数据可能受季节因素影响",),
        watch_indicators=("下月开工率与中标金额",),
        claims=(),
        uncertainty=("缺少分省数据",),
        topic="economy",
    )
    assert AnalysisBrief.from_dict(brief.to_dict()) == brief

    script = EditorialScript(
        title="今日解读",
        opening_hook="先行指标为什么突然回暖？",
        sections=(),
        closing_synthesis="值得观察的是政策传导的下一环。",
        body="全文",
        story_ids=("story_001",),
    )
    assert EditorialScript.from_dict(script.to_dict()) == script


def test_editorial_selection_round_trips():
    selection = EditorialSelection(
        top_k=3,
        selected=("story_001", "story_003"),
        rejected=({"story_id": "story_002", "total": 40.0, "reason": "duplicate"},),
        insufficient=True,
        selection_config={"min_total_score": 55},
    )
    assert EditorialSelection.from_dict(selection.to_dict()) == selection


def test_default_config_has_editorial_section():
    cfg = load_config()
    assert cfg["editorial"]["mode"] == "none"
    assert sum(cfg["editorial"]["weights"].values()) == 100
    assert set(cfg["editorial"]["weights"]) == set(DIMENSIONS)
    assert set(cfg["editorial"]["critique_min"]) == set(CRITIQUE_DIMENSIONS)
    assert "国内联播快讯" in cfg["editorial"]["aggregate_headings"]


def _editorial_cfg(**overrides) -> dict:
    """A config dict whose editorial overrides are applied through load_config."""
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "override.yaml"
        import yaml

        path.write_text(yaml.safe_dump({"editorial": overrides}, allow_unicode=True), encoding="utf-8")
        return load_config(path)


def test_weights_must_sum_to_one_hundred():
    # load_config deep-merges, so a partial override changes one dimension only.
    with pytest.raises(ValueError, match="weights must sum to 100"):
        _editorial_cfg(weights={"public_impact": 30})


def test_unknown_weight_dimension_is_rejected():
    broken = {d: 100 // len(DIMENSIONS) for d in DIMENSIONS}
    broken["gut_feeling"] = 0
    with pytest.raises(ValueError, match="unknown dimension"):
        _editorial_cfg(weights=broken)


def test_negative_weight_is_rejected():
    broken = {d: 0 for d in DIMENSIONS}
    broken["public_impact"] = 100
    broken["audience_utility"] = -5
    with pytest.raises(ValueError, match="non-negative"):
        _editorial_cfg(weights=broken)


def test_critique_rubric_keys_are_validated():
    with pytest.raises(ValueError, match="critique_min"):
        _editorial_cfg(critique_min={"vibes": 7})


def test_critique_rubric_threshold_must_be_in_range():
    with pytest.raises(ValueError, match="critique_min"):
        _editorial_cfg(critique_min={"clarity": 11})


def test_top_k_cannot_be_below_min_candidates():
    with pytest.raises(ValueError, match="top_k"):
        _editorial_cfg(top_k=2, min_candidates=4)


def test_shortlist_must_cover_top_k():
    with pytest.raises(ValueError, match="shortlist"):
        _editorial_cfg(shortlist=3, top_k=5)


def test_mode_must_be_known():
    with pytest.raises(ValueError, match="editorial.mode"):
        _editorial_cfg(mode="curated")


def test_probabilities_are_bounded():
    with pytest.raises(ValueError, match="min_confidence"):
        _editorial_cfg(min_confidence=1.5)
    with pytest.raises(ValueError, match="max_topic_share"):
        _editorial_cfg(max_topic_share=0)


def test_batch_size_and_revisions_are_positive_ints():
    with pytest.raises(ValueError, match="batch_size"):
        _editorial_cfg(batch_size=0)
    with pytest.raises(ValueError, match="max_revisions"):
        _editorial_cfg(max_revisions=-1)


def test_target_duration_window_must_ascend():
    with pytest.raises(ValueError, match="target_duration_ms"):
        _editorial_cfg(target_duration_ms=[900000, 300000])


def test_aggregate_headings_must_be_non_empty_strings():
    with pytest.raises(ValueError, match="aggregate_headings"):
        _editorial_cfg(aggregate_headings=[])


def test_load_config_does_not_mutate_defaults():
    cfg = load_config()
    before = copy.deepcopy(cfg["editorial"]["weights"])
    cfg["editorial"]["weights"]["public_impact"] = 0
    assert load_config()["editorial"]["weights"] == before
