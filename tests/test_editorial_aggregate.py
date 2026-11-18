"""Splitting aggregate 联播快讯 blocks without losing a single character (task 3)."""
from __future__ import annotations

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.editorial import extractor

GLUED = (
    "国家防总办公室安排部署2026—2027年度凌汛期防凌工作近日，国家防总办公室安排部署2026—2027年度凌汛期防凌工作，要求相关省份严格落实责任制。"
    "2026年版国家基本医保药品目录发布 新增107种药品2026年版国家基本医保药品目录今天（11月14日）发布，将于明年1月1日起正式实施。"
    "我国10吨级电动商用飞机完成首次有人驾驶智能飞行今天（11月14日），由中国商飞研制的10吨级电动商用飞机CE-25A完成首次有人驾驶智能飞行。"
)
BODY = f"国内联播快讯\n\n{GLUED}\n"
PIECES = [
    "国家防总办公室安排部署2026—2027年度凌汛期防凌工作近日，国家防总办公室安排部署2026—2027年度凌汛期防凌工作，要求相关省份严格落实责任制。",
    "2026年版国家基本医保药品目录发布 新增107种药品2026年版国家基本医保药品目录今天（11月14日）发布，将于明年1月1日起正式实施。",
    "我国10吨级电动商用飞机完成首次有人驾驶智能飞行今天（11月14日），由中国商飞研制的10吨级电动商用飞机CE-25A完成首次有人驾驶智能飞行。",
]


@pytest.fixture()
def cfg() -> dict:
    return load_config()


def fake_llm(spans):
    def call(stage, payload, check=None):
        assert stage == "aggregate_split"
        result = {"items": spans}
        return check(result) if check is not None else result
    return call


def test_verify_verbatim_accepts_item_objects():
    spans = extractor.verify_verbatim(GLUED, PIECES)
    assert len(spans) == 3


def test_verify_verbatim_accepts_a_faithful_split():
    spans = extractor.verify_verbatim(GLUED, PIECES)
    assert len(spans) == 3
    assert GLUED[spans[0][0]:spans[0][1]] == PIECES[0]
    assert spans[-1][1] == len(GLUED)


def test_verify_verbatim_rejects_a_paraphrase():
    with pytest.raises(ValueError, match="verbatim"):
        extractor.verify_verbatim(GLUED, ["国家防总部署了防凌工作。", PIECES[1], PIECES[2]])


def test_verify_verbatim_rejects_dropped_text():
    with pytest.raises(ValueError, match="verbatim"):
        extractor.verify_verbatim(GLUED, PIECES[:2])


def test_verify_verbatim_rejects_reordered_text():
    with pytest.raises(ValueError, match="verbatim"):
        extractor.verify_verbatim(GLUED, [PIECES[1], PIECES[0], PIECES[2]])


def test_verify_verbatim_tolerates_whitespace_only_differences():
    spans = extractor.verify_verbatim(GLUED, [f" {PIECES[0]} ", PIECES[1], PIECES[2]])
    assert len(spans) == 3


def test_split_aggregate_keeps_the_container_as_a_record(cfg):
    blocks = extractor.split_blocks(BODY, cfg)
    pieces = extractor.split_aggregate(blocks[0], cfg, fake_llm(PIECES))
    assert [p.split_status for p in pieces] == ["llm_verified"] * 3
    assert {p.section for p in pieces} == {"国内联播快讯"}
    assert "".join(p.text for p in pieces) == GLUED
    assert all(BODY[p.start:p.end] == p.text for p in pieces)


def test_split_aggregate_falls_back_to_the_whole_block(cfg):
    blocks = extractor.split_blocks(BODY, cfg)
    pieces = extractor.split_aggregate(blocks[0], cfg, fake_llm(["改写过的标题和正文。", PIECES[1], PIECES[2]]))
    assert len(pieces) == 1
    assert pieces[0].split_status == "uncertain"
    assert pieces[0].text == blocks[0].text


def test_split_aggregate_never_invents_a_story_when_the_llm_fails(cfg):
    blocks = extractor.split_blocks(BODY, cfg)

    def broken(stage, payload):
        raise RuntimeError("gateway timeout")

    pieces = extractor.split_aggregate(blocks[0], cfg, broken)
    assert len(pieces) == 1
    assert pieces[0].split_status == "uncertain"


def test_split_aggregate_rejects_a_single_item_answer(cfg):
    """One item is not a split; the container stays whole and uncertain."""
    blocks = extractor.split_blocks(BODY, cfg)
    pieces = extractor.split_aggregate(blocks[0], cfg, fake_llm([GLUED]))
    assert len(pieces) == 1
    assert pieces[0].split_status == "uncertain"


def test_extract_candidates_splits_aggregates_when_an_llm_is_given(cfg):
    candidates, report = extractor.extract_candidates(BODY, "t", cfg, llm=fake_llm(PIECES))
    split = [c for c in candidates if c.section == "国内联播快讯"]
    assert len(split) == 3
    assert {c.split_status for c in split} == {"llm_verified"}
    assert report["aggregate_blocks"] == 1
    assert report["split_briefs"] == 3
    assert all(c.duplicate_of is None for c in split)
    for candidate in split:
        assert "".join(BODY[s.start:s.end] for s in candidate.source_spans) == candidate.source_text


def test_derived_headline_recovers_a_repeated_title_without_a_connective():
    """Real 联播快讯 items glue `标题正文`; only the repeated prefix is provable.

    The site's own heading for this brief is longer, but from the glued text alone
    the honest answer is the longest prefix that provably repeats.
    """
    glued = "2026年版国家基本医保药品目录发布 新增107种药品2026年版国家基本医保药品目录今天（11月14日）发布，将于明年1月1日起正式实施。"
    recovered = extractor.derived_headline(glued)
    assert glued.startswith(recovered)
    assert len(recovered) >= extractor.MIN_REPEAT_PREFIX
    assert glued.find(recovered, len(recovered)) != -1, "a recovered headline must provably repeat"
    assert "今天" not in recovered and "发布，将于" not in recovered


def test_split_aggregate_prefers_a_verbatim_llm_headline(cfg):
    blocks = extractor.split_blocks(BODY, cfg)
    items = [{"headline": PIECES[0][:20], "text": PIECES[0]},
             {"headline": PIECES[1][:24], "text": PIECES[1]},
             {"headline": PIECES[2][:22], "text": PIECES[2]}]
    pieces = extractor.split_aggregate(blocks[0], cfg, fake_llm(items))
    assert [p.heading for p in pieces] == [PIECES[0][:20], PIECES[1][:24], PIECES[2][:22]]


def test_split_aggregate_rejects_a_headline_that_is_not_in_the_text(cfg):
    blocks = extractor.split_blocks(BODY, cfg)
    items = [{"headline": "编造出来的标题", "text": PIECES[0]}, PIECES[1], PIECES[2]]
    pieces = extractor.split_aggregate(blocks[0], cfg, fake_llm(items))
    assert pieces[0].heading != "编造出来的标题"
    assert pieces[0].heading in pieces[0].text


def test_derived_headline_strips_a_leading_connective():
    glued = "国家防总办公室安排部署2026—2027年度凌汛期防凌工作近日，国家防总办公室安排部署2026—2027年度凌汛期防凌工作，要求落实责任制。"
    assert extractor.derived_headline(glued) == "国家防总办公室安排部署2026—2027年度凌汛期防凌工作"


def test_derived_headline_falls_back_to_the_first_clause():
    glued = "我国10吨级电动商用飞机完成首次有人驾驶智能飞行今天（11月14日），由中国商飞研制。"
    assert extractor.derived_headline(glued) == "我国10吨级电动商用飞机完成首次有人驾驶智能飞行"


def test_derived_headline_never_exceeds_the_limit():
    glued = "一个非常长的标题" * 12
    assert len(extractor.derived_headline(glued, limit=20)) <= 21


def test_split_pieces_get_distinct_headlines_from_their_own_text(cfg):
    candidates, _ = extractor.extract_candidates(BODY, "t", cfg, llm=fake_llm(PIECES))
    headlines = [c.headline for c in candidates]
    assert len(set(headlines)) == len(headlines)
    assert headlines[0].startswith("国家防总办公室")


def test_no_characters_are_lost_when_splitting(cfg):
    candidates, report = extractor.extract_candidates(BODY, "t", cfg, llm=fake_llm(PIECES))
    claimed = [(s.start, s.end) for c in candidates for s in c.source_spans]
    claimed += [(b["start"], b["end"]) for b in report["skipped_blocks"]]
    orphans = [i for i, ch in enumerate(BODY)
               if not ch.isspace() and not any(s <= i < e for s, e in claimed)]
    assert orphans == []
