"""Analysis briefs: independent insight with verifiable claims (task 7, part 2)."""
from __future__ import annotations

import json

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.editorial import insight
from news_video_pipeline.editorial.models import SourceSpan, StoryCandidate

TEXT = (
    "国家统计局今天发布数据，前三季度国内生产总值同比增长5.2%。"
    "其中第三季度增长4.8%，服务业增加值同比增长5.4%。"
)


def candidate(story_id: str = "story_001", text: str = TEXT, block_index: int = 1, **overrides) -> StoryCandidate:
    payload = dict(
        story_id=story_id,
        headline="经济数据发布",
        source_id="input_x",
        source_spans=(SourceSpan(0, len(text)),),
        source_text=text,
        block_index=block_index,
    )
    payload.update(overrides)
    return StoryCandidate(**payload)


def brief_payload(**overrides) -> dict:
    payload = {
        "angle": "先行指标与服务业数据同时改善，说明政策落地开始转化为需求。",
        "mechanisms": ["服务业增加值增速高于总体，说明结构在向服务业主导倾斜。"],
        "second_order": ["若服务业继续走强，就业指标可能滞后改善。"],
        "counterpoints": ["单月与累计数据可能受季节因素影响，一个季度不足以确认趋势。"],
        "watch_indicators": ["下月服务业增加值与城镇调查失业率。"],
        "uncertainty": ["缺少分省数据，无法判断改善是否普遍。"],
        "claims": [
            {"claim_id": "c1", "kind": "FACT", "text": "前三季度国内生产总值同比增长5.2%",
             "quote": "前三季度国内生产总值同比增长5.2%", "reasoning": "节目稿原文", "limitation": "全国口径"},
            {"claim_id": "c2", "kind": "FACT", "text": "服务业增加值同比增长5.4%",
             "quote": "服务业增加值同比增长5.4%", "reasoning": "节目稿原文", "limitation": ""},
            {"claim_id": "c3", "kind": "INFERENCE", "text": "这意味着服务业是当前的主要拉动项。",
             "quote": "服务业增加值同比增长5.4%", "depends_on": ["c2"], "reasoning": "5.4%高于总体5.2%"},
            {"claim_id": "c4", "kind": "OPINION", "text": "我认为结构性改善比总量数字更值得关注。",
             "quote": "服务业增加值同比增长5.4%", "reasoning": "判断标准是结构变化"},
            {"claim_id": "c5", "kind": "UNKNOWN", "text": "尚不能判断这一改善能否持续。", "quote": ""},
        ],
    }
    payload.update(overrides)
    return payload


SECOND_TEXT = "海关总署发布数据，出口同比增长6.1%，机电产品占比提高。"


def simple_brief(quote: str, label: str) -> dict:
    """A minimal valid brief whose claims quote the given story's own text."""
    return {
        "angle": f"{label}的核心判断",
        "mechanisms": [f"{label}背后的机制说明"],
        "claims": [
            {"claim_id": "c1", "kind": "FACT", "text": quote, "quote": quote,
             "reasoning": "节目稿原文", "limitation": ""},
            {"claim_id": "c2", "kind": "INFERENCE", "text": f"{label}说明趋势仍在延续。",
             "quote": quote, "depends_on": ["c1"], "reasoning": "由事实推出"},
        ],
    }


class FakeLLM:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, stage, payload, check=None):
        """Mirror EditorialLLM: validate the answer here so `check` is exercised."""
        return check(self._answer(stage, payload)) if check is not None else self._answer(stage, payload)

    def _answer(self, stage, payload):
        self.calls.append((stage, payload))
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture()
def cfg() -> dict:
    return load_config()


def test_build_brief_produces_typed_claims(cfg):
    brief = insight.build_brief(brief_payload(), candidate(), cfg)
    assert brief.story_id == "story_001"
    assert brief.headline == "经济数据发布"
    kinds = [claim.kind for claim in brief.claims]
    assert kinds == ["FACT", "FACT", "INFERENCE", "OPINION", "UNKNOWN"]
    assert brief.claims[0].claim_id == "story_001_claim_01"
    assert brief.claims[2].depends_on == ("story_001_claim_02",)
    assert insight.claim_report([brief])["counts"] == {"FACT": 2, "INFERENCE": 1, "OPINION": 1, "UNKNOWN": 1}
    json.dumps(brief.to_dict(), ensure_ascii=False)


def test_build_brief_rejects_an_empty_angle(cfg):
    with pytest.raises(ValueError, match="no angle"):
        insight.build_brief(brief_payload(angle="  "), candidate(), cfg)


def test_build_brief_rejects_a_brief_with_no_mechanism(cfg):
    with pytest.raises(ValueError, match="explains no mechanism"):
        insight.build_brief(brief_payload(mechanisms=[]), candidate(), cfg)


def test_build_brief_rejects_a_brief_with_no_fact(cfg):
    payload = brief_payload()
    payload["claims"] = [claim for claim in payload["claims"] if claim["kind"] in {"OPINION", "UNKNOWN"}]
    with pytest.raises(ValueError, match="no FACT claim"):
        insight.build_brief(payload, candidate(), cfg)


def test_build_brief_rejects_an_invented_number_anywhere_in_the_prose(cfg):
    with pytest.raises(ValueError, match="not in the story source"):
        insight.build_brief(brief_payload(mechanisms=["投资增长7.9%，说明政策见效。"]), candidate(), cfg)


def test_a_dependency_written_as_an_ordinal_is_resolved(cfg):
    """The gateway labels a claim `c2` and may then refer to it as `claim_2`."""
    payload = brief_payload()
    payload["claims"] = [
        {"kind": "OPINION", "text": "我认为结构比总量更值得看。", "reasoning": "判断标准是结构。"},
        {"kind": "FACT", "text": "前三季度国内生产总值同比增长5.2%",
         "quote": "前三季度国内生产总值同比增长5.2%", "reasoning": "原文"},
        {"kind": "INFERENCE", "text": "这意味着增长保持稳定。",
         "quote": "前三季度国内生产总值同比增长5.2%", "depends_on": ["claim_2"], "reasoning": "由事实推出"},
    ]
    brief = insight.build_brief(payload, candidate(), cfg)
    assert brief.claims[2].depends_on == (brief.claims[1].claim_id,)


def test_build_brief_rejects_an_unknown_dependency(cfg):
    payload = brief_payload()
    payload["claims"][2]["depends_on"] = ["c404"]
    with pytest.raises(ValueError, match="c404"):
        insight.build_brief(payload, candidate(), cfg)


def test_build_brief_rejects_a_duplicated_claim_id(cfg):
    payload = brief_payload()
    payload["claims"][1]["claim_id"] = "c1"
    with pytest.raises(ValueError, match="used twice"):
        insight.build_brief(payload, candidate(), cfg)


def test_build_brief_tolerates_a_missing_optional_prose_field(cfg):
    payload = brief_payload()
    payload.pop("counterpoints")
    brief = insight.build_brief(payload, candidate(), cfg)
    assert brief.counterpoints == ()


def test_build_briefs_keeps_selection_order_and_isolates_sources(cfg):
    items = [candidate("story_001"), candidate("story_002", text=SECOND_TEXT, block_index=2)]
    llm = FakeLLM([
        {"brief": simple_brief("出口同比增长6.1%", "上条出口")},
        {"brief": simple_brief("前三季度国内生产总值同比增长5.2%", "经济数据")},
    ])
    briefs = insight.build_briefs(["story_002", "story_001"], items, cfg, llm)
    assert [brief.story_id for brief in briefs] == ["story_002", "story_001"]
    assert [call[0] for call in llm.calls] == ["brief", "brief"]
    assert SECOND_TEXT in llm.calls[0][1]["text"]
    assert TEXT not in llm.calls[0][1]["text"]
    assert SECOND_TEXT not in llm.calls[1][1]["text"]


def test_build_briefs_rejects_an_unknown_story_id(cfg):
    with pytest.raises(ValueError, match="story_404"):
        insight.build_briefs(["story_404"], [candidate()], cfg, FakeLLM([]))


def test_build_briefs_rejects_a_brief_that_is_not_an_object(cfg):
    llm = FakeLLM([{"brief": "这两条新闻都很重要"}])
    with pytest.raises(ValueError, match="must contain a JSON object"):
        insight.build_briefs(["story_001"], [candidate()], cfg, llm)


def test_build_briefs_reports_every_story(cfg):
    items = [candidate("story_001"), candidate("story_002", text=SECOND_TEXT, block_index=2)]
    llm = FakeLLM([
        {"brief": simple_brief("前三季度国内生产总值同比增长5.2%", "甲")},
        {"brief": simple_brief("出口同比增长6.1%", "乙")},
    ])
    briefs = insight.build_briefs(["story_001", "story_002"], items, cfg, llm)
    assert insight.claim_report(briefs) == {"claims": 4, "counts": {"FACT": 2, "INFERENCE": 2, "OPINION": 0, "UNKNOWN": 0}}
