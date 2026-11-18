"""Deterministic story extraction with traceable source spans (task 2)."""
from __future__ import annotations

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.editorial import extractor

BODY = (
    "新闻联播\n\n"
    "【建设亚太共同体 促进共同繁荣】创新亚太 携手同行\n"
    "“创新”是2026年APEC“中国年”确定的三大优先领域之一。如今，亚太地区正以协同创新为引领，打造绿色亚太、数字亚太的新招牌。\n\n"
    "持之以恒推进全面从严治党 以高质量党建引领企业高质量发展\n"
    "习近平总书记近日对国有企业党的建设工作作出重要指示，强调要持之以恒推进全面从严治党。\n\n"
    "国内联播快讯\n"
    "国家防总办公室安排部署2026—2027年度凌汛期防凌工作近日，国家防总办公室安排部署2026—2027年度凌汛期防凌工作，要求相关省份严格落实责任制。"
    "2026年版国家基本医保药品目录发布 新增107种药品2026年版国家基本医保药品目录今天（11月14日）发布，将于明年1月1日起正式实施。\n\n"
    "奋力开创粤港澳大湾区高质量发展新局面\n"
    "中共中央总书记习近平在广东中山考察时强调，要奋力开创粤港澳大湾区高质量发展新局面。\n\n"
    "央视快评：奋力开创粤港澳大湾区高质量发展新局面\n"
    "本台今天（11月16日）播发央视快评《奋力开创粤港澳大湾区高质量发展新局面》。\n\n"
    "国际联播快讯\n"
    "俄称扩大乌问题谈判取决于欧洲真实意愿欧洲理事会主席科斯塔13日表示，欧盟领导人当天同意组成欧洲代表团，参与乌克兰和平谈判。"
    "空管通信出故障 全美航班停飞超4小时美国联邦航空管理局13日发布全国范围的航班暂停起飞指令。\n"
)


@pytest.fixture()
def cfg() -> dict:
    return load_config()


def test_split_blocks_finds_headings_in_programme_order(cfg):
    blocks = extractor.split_blocks(BODY, cfg)
    headings = [b.heading for b in blocks]
    assert headings == [
        "【建设亚太共同体 促进共同繁荣】创新亚太 携手同行",
        "持之以恒推进全面从严治党 以高质量党建引领企业高质量发展",
        "国内联播快讯",
        "奋力开创粤港澳大湾区高质量发展新局面",
        "央视快评：奋力开创粤港澳大湾区高质量发展新局面",
        "国际联播快讯",
    ]


def test_programme_name_line_is_not_a_story(cfg):
    report = extractor.extract_candidates(BODY, "2026年11月14日", cfg)[1]
    assert [b["reason"] for b in report["skipped_blocks"]] == ["programme_name_or_empty"]
    assert all("新闻联播" != b.heading for b in extractor.split_blocks(BODY, cfg))


def test_aggregate_sections_are_flagged(cfg):
    blocks = extractor.split_blocks(BODY, cfg)
    aggregate = [b.heading for b in blocks if b.is_aggregate]
    assert aggregate == ["国内联播快讯", "国际联播快讯"]


def test_block_offsets_match_the_source(cfg):
    for block in extractor.split_blocks(BODY, cfg):
        assert BODY[block.start:block.end] == block.text
        assert block.heading in block.text


def test_candidate_spans_are_exact_and_contiguous(cfg):
    candidates, _ = extractor.extract_candidates(BODY, "2026年11月14日", cfg)
    for candidate in candidates:
        assert "".join(BODY[s.start:s.end] for s in candidate.source_spans) == candidate.source_text
        assert candidate.source_text in BODY


def test_candidates_are_sequential_unique_and_unverified(cfg):
    candidates, _ = extractor.extract_candidates(BODY, "2026年11月14日", cfg)
    ids = [c.story_id for c in candidates]
    assert ids == [f"story_{i:03d}" for i in range(1, len(candidates) + 1)]
    assert len(set(ids)) == len(ids)
    assert {c.source_status for c in candidates} == {"unverified"}
    assert all(c.split_status == "exact" for c in candidates if c.section == "")


def test_extraction_is_deterministic(cfg):
    first, _ = extractor.extract_candidates(BODY, "t", cfg)
    second, _ = extractor.extract_candidates(BODY, "t", cfg)
    assert [c.to_dict() for c in first] == [c.to_dict() for c in second]


def test_commentary_on_the_same_event_is_clustered(cfg):
    candidates, report = extractor.extract_candidates(BODY, "2026年11月16日", cfg)
    by_headline = {c.headline: c for c in candidates}
    main = by_headline["奋力开创粤港澳大湾区高质量发展新局面"]
    note = by_headline["央视快评：奋力开创粤港澳大湾区高质量发展新局面"]
    assert note.duplicate_of == main.story_id
    assert note.cluster_id == main.cluster_id
    assert main.duplicate_of is None
    assert report["duplicate_clusters"][main.cluster_id] == [main.story_id, note.story_id]


def test_identical_headlines_cluster(cfg):
    body = "同一事件标题\n第一段正文内容。\n\n同一事件标题\n第二段正文内容略有不同。\n"
    candidates, _ = extractor.extract_candidates(body, "t", cfg)
    assert candidates[1].duplicate_of == candidates[0].story_id


def test_multi_paragraph_story_stays_one_candidate(cfg):
    body = "长新闻标题\n第一段内容结束。\n\n第二段继续讲同一件事。\n"
    candidates, report = extractor.extract_candidates(body, "t", cfg)
    assert len(candidates) == 1
    assert "第二段继续讲同一件事" in candidates[0].source_text
    assert report["continuation_blocks"] == 1


def test_aggregate_blocks_without_llm_keep_all_characters(cfg):
    candidates, report = extractor.extract_candidates(BODY, "t", cfg)
    aggregate = [c for c in candidates if c.section]
    assert {c.section for c in aggregate} == {"国内联播快讯", "国际联播快讯"}
    for candidate in aggregate:
        assert candidate.split_status in {"uncertain", "llm_verified", "exact"}
        assert BODY[candidate.source_spans[0].start:candidate.source_spans[-1].end] in BODY
    assert report["aggregate_blocks"] == 2


def test_aggregate_containers_are_never_clustered_together(cfg):
    """国内联播快讯 and 国际联播快讯 share a phrase but hold different stories."""
    candidates, report = extractor.extract_candidates(BODY, "t", cfg)
    containers = [c for c in candidates if c.section and c.headline == c.section]
    assert [c.section for c in containers] == ["国内联播快讯", "国际联播快讯"]
    assert all(c.duplicate_of is None for c in containers)
    assert containers[0].cluster_id != containers[1].cluster_id
    assert not any(set(v) >= {containers[0].story_id, containers[1].story_id}
                   for v in report["duplicate_clusters"].values())


def test_every_non_whitespace_character_is_claimed_or_reported(cfg):
    """No silent truncation: each source character is in a candidate or a skip record."""
    candidates, report = extractor.extract_candidates(BODY, "t", cfg)
    claimed = [(s.start, s.end) for c in candidates for s in c.source_spans]
    claimed += [(b["start"], b["end"]) for b in report["skipped_blocks"]]
    orphans = [i for i, ch in enumerate(BODY)
               if not ch.isspace() and not any(s <= i < e for s, e in claimed)]
    assert orphans == [], f"characters lost at offsets {orphans[:5]}"


def test_empty_and_heading_only_input_fail_closed(cfg):
    with pytest.raises(ValueError, match="no news"):
        extractor.extract_candidates("新闻联播\n", "t", cfg)


def test_short_line_without_body_is_reported_not_silently_dropped(cfg):
    body = "只有标题没有正文的栏目\n\n真实新闻标题\n真实新闻正文内容。\n"
    candidates, report = extractor.extract_candidates(body, "t", cfg)
    assert [c.headline for c in candidates] == ["真实新闻标题"]
    assert any(b["reason"] == "heading_without_body" for b in report["skipped_blocks"])
