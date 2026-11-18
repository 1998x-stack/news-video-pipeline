"""Claim anchoring: FACT / INFERENCE / OPINION / UNKNOWN (task 7, part 1)."""
from __future__ import annotations

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.editorial import evidence
from news_video_pipeline.editorial.models import Claim, SourceSpan, StoryCandidate

TEXT = (
    "国家统计局今天发布数据，前三季度国内生产总值同比增长5.2%。"
    "其中第三季度增长4.8%，服务业增加值同比增长5.4%。"
)
BODY = TEXT + "下一步将扩大有效投资。"


def candidate(spans=None, text=TEXT) -> StoryCandidate:
    return StoryCandidate(
        story_id="story_001",
        headline="经济数据发布",
        source_id="input_x",
        source_spans=tuple(spans or [SourceSpan(0, len(text))]),
        source_text=text,
        block_index=1,
    )


@pytest.fixture()
def cfg() -> dict:
    return load_config()


def fact(text="前三季度国内生产总值同比增长5.2%", quote="前三季度国内生产总值同比增长5.2%", **overrides) -> Claim:
    start = TEXT.index(quote)
    payload = dict(claim_id="claim_001", story_id="story_001", kind="FACT", text=text,
                   source_spans=(SourceSpan(start, start + len(quote)),), depends_on=(),
                   reasoning="节目稿原文。", limitation="仅有全国口径。")
    payload.update(overrides)
    return Claim(**payload)


def test_valid_fact_is_anchored(cfg):
    report = evidence.validate_claims([fact()], candidate(), cfg)
    assert report["counts"] == {"FACT": 1, "INFERENCE": 0, "OPINION": 0, "UNKNOWN": 0}
    assert report["anchored_ratio"] == 1.0
    assert report["claims"] == 1


def test_a_fact_with_an_invented_number_is_rejected(cfg):
    claim = fact(text="前三季度国内生产总值同比增长7.9%", quote="前三季度国内生产总值同比增长5.2%")
    with pytest.raises(ValueError, match="not present in its cited source"):
        evidence.validate_claims([claim], candidate(), cfg)


def test_an_inference_with_a_dangling_dependency_is_rejected(cfg):
    claim = Claim(claim_id="claim_002", story_id="story_001", kind="INFERENCE",
                  text="这意味着全年目标更容易实现。", source_spans=(SourceSpan(0, 10),),
                  depends_on=("claim_404",), reasoning="由数据推出。")
    with pytest.raises(ValueError, match="depends_on"):
        evidence.validate_claims([claim], candidate(), cfg)


def test_an_inference_may_not_depend_on_another_inference(cfg):
    fact_claim = fact(claim_id="claim_010")
    first = Claim(claim_id="claim_011", story_id="story_001", kind="INFERENCE", text="这可能延续。",
                  source_spans=(SourceSpan(11, 28),), depends_on=("claim_010",))
    second = Claim(claim_id="claim_012", story_id="story_001", kind="INFERENCE", text="因此还会更高。",
                   source_spans=(SourceSpan(11, 28),), depends_on=("claim_011",))
    with pytest.raises(ValueError, match="must depend on FACT"):
        evidence.validate_claims([fact_claim, first, second], candidate(), cfg)


def test_an_inference_without_dependencies_is_rejected(cfg):
    claim = Claim(claim_id="claim_013", story_id="story_001", kind="INFERENCE", text="这意味着趋势稳固。",
                  source_spans=(SourceSpan(11, 28),))
    with pytest.raises(ValueError, match="must declare depends_on"):
        evidence.validate_claims([claim], candidate(), cfg)


def test_a_valid_inference_depending_on_a_fact_is_accepted(cfg):
    fact_claim = fact(claim_id="claim_001")
    inference = Claim(claim_id="claim_002", story_id="story_001", kind="INFERENCE",
                      text="这意味着服务业是主要拉动项。", source_spans=(SourceSpan(11, 28),),
                      depends_on=("claim_001",), reasoning="由5.4%高于总体推出。")
    report = evidence.validate_claims([fact_claim, inference], candidate(), cfg)
    assert report["counts"]["INFERENCE"] == 1
    assert report["anchored_ratio"] == 1.0


def test_an_unanchored_fact_is_rejected(cfg):
    claim = fact(text="中国经济长期向好的基本面没有改变并且仍然具备大量有利条件",
                 quote="前三季度国内生产总值同比增长5.2%")
    with pytest.raises(ValueError, match="anchor"):
        evidence.validate_claims([claim], candidate(), cfg)


def test_a_claim_citing_a_span_outside_the_story_is_rejected(cfg):
    claim = fact(source_spans=(SourceSpan(0, 5),))
    shifted = StoryCandidate(
        story_id="story_001", headline="经济数据发布", source_id="input_x",
        source_spans=(SourceSpan(200, 260),), source_text=TEXT, block_index=1,
    )
    with pytest.raises(ValueError, match="outside"):
        evidence.validate_claims([claim], shifted, cfg)


def test_unknown_may_not_smuggle_an_out_of_source_number(cfg):
    claim = Claim(claim_id="claim_003", story_id="story_001", kind="UNKNOWN",
                  text="明年的目标可能是6.5%。", source_spans=(SourceSpan(11, 28),))
    with pytest.raises(ValueError, match="not present in the story source"):
        evidence.validate_claims([claim], candidate(), cfg)


def test_opinion_states_its_standard_without_needing_a_number(cfg):
    claim = Claim(claim_id="claim_004", story_id="story_001", kind="OPINION",
                  text="我认为这条数据的意义大于单月波动。", source_spans=(SourceSpan(11, 28),),
                  reasoning="判断标准是结构与趋势而非单月读数。")
    report = evidence.validate_claims([claim], candidate(), cfg)
    assert report["counts"]["OPINION"] == 1
    assert report["anchored_ratio"] == 1.0


def test_a_claim_without_any_span_is_rejected(cfg):
    claim = Claim(claim_id="claim_005", story_id="story_001", kind="FACT", text="某项数据增长。")
    with pytest.raises(ValueError, match="no cited source span"):
        evidence.validate_claims([claim], candidate(), cfg)


def test_claim_from_llm_locates_the_verbatim_quote(cfg):
    raw = {"kind": "FACT", "text": "前三季度国内生产总值同比增长5.2%",
           "quote": "国内生产总值同比增长5.2%", "reasoning": "原文", "limitation": ""}
    claim = evidence.claim_from_llm(raw, "story_001", candidate(), "claim_007", {})
    assert claim.claim_id == "claim_007"
    assert BODY[claim.source_spans[0].start:claim.source_spans[0].end] == "国内生产总值同比增长5.2%"


def test_claim_from_llm_rejects_a_quote_that_is_not_verbatim(cfg):
    raw = {"kind": "FACT", "text": "增长强劲", "quote": "经济增速大幅提升", "reasoning": "", "limitation": ""}
    with pytest.raises(ValueError, match="verbatim"):
        evidence.claim_from_llm(raw, "story_001", candidate(), "claim_008", {})


def test_claim_from_llm_rejects_an_unknown_kind(cfg):
    raw = {"kind": "GUESS", "text": "也许上涨", "quote": "增长5.2%"}
    with pytest.raises(ValueError, match="kind"):
        evidence.claim_from_llm(raw, "story_001", candidate(), "claim_009", {})


def test_claim_from_llm_requires_an_existing_fact_for_depends_on(cfg):
    raw = {"kind": "INFERENCE", "text": "这说明趋势稳固。", "depends_on": ["claim_404"]}
    with pytest.raises(ValueError, match="claim_404"):
        evidence.claim_from_llm(raw, "story_001", candidate(), "claim_010", {})


def test_assert_claims_supported_summarises_a_valid_set(cfg):
    report = evidence.assert_claims_supported([fact()], candidate(), cfg)
    assert report["claims"] == 1
    assert report["anchored_ratio"] == 1.0


def test_brief_claim_report_is_serialisable():
    report = evidence.validate_claims([fact()], candidate(), load_config())
    import json

    json.dumps(report, ensure_ascii=False)


def test_fact_rejects_high_overlap_polarity_reversal(cfg):
    """Even near-identical text can reverse an important factual conclusion."""
    source = "今天发布数据，经济增长保持稳定。"
    story = candidate(text=source)
    quote = "经济增长保持稳定"
    start = source.index(quote)
    reversed_claim = Claim(
        claim_id="claim_polarity", story_id="story_001", kind="FACT",
        text="经济下降保持稳定",
        source_spans=(SourceSpan(start, start + len(quote)),),
    )
    with pytest.raises(ValueError, match="exact source quotation"):
        evidence.validate_claims([reversed_claim], story, cfg)


def test_fact_rejects_paraphrase_even_at_low_config_threshold(cfg):
    cfg["editorial"]["fact_anchor_min"] = 0.01
    with pytest.raises(ValueError, match="exact source quotation"):
        evidence.validate_claims([fact(text="前三季度国内生产总值同比升高5.2%")], candidate(), cfg)


def test_fact_quote_cannot_drop_negative_or_percent_sign(cfg):
    """Numeric signs and units convey meaning; generic text normalization drops them."""
    source = "项目收益率为-5.2%，过去为5.2%。"
    story = candidate(text=source)
    quote = "收益率为-5.2%"
    start = source.index(quote)
    for altered in ("收益率为5.2%", "收益率为-5.2"):
        changed = Claim(
            claim_id="claim_sign", story_id="story_001", kind="FACT",
            text=altered, source_spans=(SourceSpan(start, start + len(quote)),),
        )
        with pytest.raises(ValueError, match="exact source quotation"):
            evidence.validate_claims([changed], story, cfg)
