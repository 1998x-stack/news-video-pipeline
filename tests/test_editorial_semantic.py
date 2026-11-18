"""Structured model-assisted semantic risk review. No self-certified news facts."""
from __future__ import annotations

import pytest
from news_video_pipeline.config import load_config
from news_video_pipeline.editorial.models import (
    AnalysisBrief, Claim, SourceSpan, StoryCandidate,
)
from news_video_pipeline.editorial import semantic


@pytest.fixture
def objects():
    source = "官方公布部分行业增长5.2%，其他行业仍然下降。"
    candidate = StoryCandidate(story_id="s1", headline="行业变化", source_id="doc",
        source_spans=(SourceSpan(0, len(source)),), source_text=source, block_index=1)
    claims = (
        Claim("f1", "s1", "FACT", "官方公布部分行业增长5.2%",
              (SourceSpan(0, len("官方公布部分行业增长5.2%")),)),
        Claim("i1", "s1", "INFERENCE", "所有行业都在增长。",
              (SourceSpan(0, len(source)),), ("f1",), reasoning="假设外推"),
    )
    brief = AnalysisBrief(story_id="s1", headline="行业变化", angle="不是所有行业都改善",
        claims=claims, mechanisms=("行业间不均衡",))
    return candidate, brief


def response(objects, inference="contradicted"):
    candidate, brief = objects
    return {"reviews": [
        {"claim_id": "f1", "verdict": "supported",
         "evidence_quote": "官方公布部分行业增长5.2%", "reason": "原文逐字存在", "flags": []},
        {"claim_id": "i1", "verdict": inference,
         "evidence_quote": "其他行业仍然下降", "reason": "以部分推整体不成立", "flags": ["scope", "polarity"]},
    ]}


def test_off_does_not_invoke_model(objects):
    candidate, brief = objects
    cfg = load_config()
    result = semantic.semantic_review([brief], [candidate], cfg, lambda *a, **k: pytest.fail("paid call"))
    assert result["mode"] == "off"


def test_report_captures_contradictions_without_granting_publication(objects):
    candidate, brief = objects
    cfg = load_config()
    cfg["editorial"]["semantic_review_mode"] = "report"
    result = semantic.semantic_review([brief], [candidate], cfg,
                  lambda stage, payload, check: check(response(objects)))
    assert result["contradiction_claim_ids"] == ["i1"]
    assert result["independently_fact_verified"] is False
    assert result["human_review_required"] is True
    assert len(result["reviews"]) == 2


def test_strict_requires_supported_fact_and_inference(objects):
    candidate, brief = objects
    cfg = load_config()
    cfg["editorial"]["semantic_review_mode"] = "strict"
    with pytest.raises(ValueError, match="unresolved claims"):
        semantic.semantic_review([brief], [candidate], cfg,
                       lambda stage, payload, check: check(response(objects)))


def test_reject_invented_quote(objects):
    candidate, brief = objects
    wrong = response(objects)
    wrong["reviews"][0]["evidence_quote"] = "原文没有这句话"
    with pytest.raises(ValueError, match="evidence_quote"):
        semantic.parse_verdicts(wrong, brief, candidate)


def test_reject_missing_or_duplicate_judgments(objects):
    candidate, brief = objects
    wrong = response(objects)
    wrong["reviews"] = wrong["reviews"][:1]
    with pytest.raises(ValueError, match="missing claim IDs"):
        semantic.parse_verdicts(wrong, brief, candidate)
    wrong["reviews"].append(wrong["reviews"][0])
    with pytest.raises(ValueError, match="duplicate"):
        semantic.parse_verdicts(wrong, brief, candidate)


def test_supported_requires_source_anchor(objects):
    candidate, brief = objects
    wrong = response(objects)
    wrong["reviews"][0]["evidence_quote"] = ""
    with pytest.raises(ValueError, match="requires a verbatim"):
        semantic.parse_verdicts(wrong, brief, candidate)


def test_semantic_review_config_rejects_invalid_mode():
    from news_video_pipeline.config import validate_editorial
    cfg = load_config()
    cfg["editorial"]["semantic_review_mode"] = "auto-truth"
    with pytest.raises(ValueError, match="semantic_review_mode"):
        validate_editorial(cfg["editorial"])
