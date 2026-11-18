"""Curated-analysis integration: artifacts, QA gate and no regression (task 9)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from news_video_pipeline import pipeline
from news_video_pipeline.config import load_config
from news_video_pipeline.pipeline import EDITORIAL_ARTIFACTS, run, validate_existing

BRIEF_TWO = "2026年版国家基本医保药品目录发布 新增107种药品"
BODY = (
    "新闻联播\n\n"
    "国内联播快讯\n"
    "国家防总办公室安排部署凌汛期防凌工作会议要求严格落实责任制，确保防凌安全。"
    f"{BRIEF_TWO}目录于明年1月1日起正式实施，药品总数达到3331个。\n\n"
    "政策发力显效 多项先行指标持续改善\n"
    "全国工程机械开工率同比提高，投资指标持续回暖。新型基础设施项目中标金额明显增长。\n\n"
    "中共中央印发《中国共产党地方委员会工作条例》\n"
    "中共中央印发《中国共产党地方委员会工作条例》，对地方党委工作进行规范。\n"
)


class FakeEditorialModel:
    """A deterministic stand-in for the gateway model, driven by the payloads."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, stage: str, payload: dict) -> dict:
        self.calls.append(stage)
        if stage == "aggregate_split":
            text = payload["text"]
            index = text.index(BRIEF_TWO)
            return {"items": [text[:index], text[index:]]}
        if stage == "rank":
            return {"ratings": [self._rating(story) for story in payload["stories"]]}
        if stage == "compare":
            return {"comparisons": [
                {"story_id": story["story_id"], "same_event_as": None, "repeat_without_progress": False,
                 "adjustment": 0, "note": "与原文一致", "evidence_gap": False}
                for story in payload["candidates"]
            ]}
        if stage == "brief":
            text = payload["text"]
            quote = text.split("。")[0] + "。"
            return {"brief": {
                "angle": "这条新闻的价值在于政策落地与需求回升之间的传导关系。",
                "mechanisms": ["政策工具先行，投资与开工数据随后改善，形成可观察的传导链条。"],
                "second_order": ["如果传导延续，下一个观察点是就业与居民收入。"],
                "counterpoints": ["单月改善可能受季节因素影响，一个数据点不足以确认趋势。"],
                "watch_indicators": ["下月的开工率与投资中标金额。"],
                "uncertainty": ["节目稿未给出分省数据，无法判断改善是否普遍。"],
                "claims": [
                    {"claim_id": "c1", "kind": "FACT", "text": quote, "quote": quote,
                     "reasoning": "节目稿原文。", "limitation": "全国口径。"},
                    {"claim_id": "c2", "kind": "INFERENCE", "text": "这意味着传导链条正在形成。",
                     "quote": quote, "depends_on": ["c1"], "reasoning": "由原文数据推出。"},
                ],
            }}
        if stage == "script":
            sections = []
            for index, story in enumerate(payload["stories"]):
                quote = (story.get("fact_quotes") or [story.get("headline", "")])[0]
                sections.append({
                    "story_id": story["story_id"],
                    "kind": "top" if index == 0 else "supporting",
                    "heading": story["headline"][:20],
                    "narration": f"{story['angle']}{quote}",
                })
            return {
                "opening_hook": "今天最值得关注的信号来自政策落地与需求回升之间的传导。",
                "sections": sections,
                "closing_synthesis": "几条新闻的共同线索是政策节奏正在向实际需求转化，值得继续观察。",
            }
        if stage == "critique":
            return {"scores": {dimension: 9 for dimension in
                               ("factual_grounding", "analytical_depth", "original_insight", "clarity",
                                "audience_utility", "uncertainty_handling", "narrative_coherence")},
                    "problems": []}
        raise AssertionError(f"unexpected stage {stage}")

    @staticmethod
    def _rating(story: dict) -> dict:
        dimensions = ("public_impact", "structural_importance", "information_novelty", "analytical_depth",
                      "timeliness", "evidence_quality", "audience_utility")
        score = 9 if story["story_id"] in {"story_001", "story_004"} else 6
        return {
            "story_id": story["story_id"],
            "scores": {dimension: score for dimension in dimensions},
            "reasons": {dimension: "依据原文中的具体数据与机构表述。" for dimension in dimensions},
            "topic": "economy" if story["story_id"] in {"story_001", "story_004"} else "politics",
            "confidence": 0.9,
            "new_information": ["给出了新的月度或政策信息。"],
            "uncertainties": [],
        }

    def summary(self) -> dict:
        return {"calls": len(self.calls), "stages": [], "requests": len(self.calls), "cache_hits": 0,
                "failures": 0, "latency_s": 0.0}


def curated_config() -> dict:
    cfg = load_config()
    cfg["voice"]["provider"] = "synthetic"
    cfg["render"]["width"] = 640
    cfg["render"]["height"] = 360
    cfg["planner"]["max_scenes"] = 14
    cfg["editorial"].update({"top_k": 2, "min_candidates": 1, "shortlist": 6, "min_total_score": 50,
                             "batch_size": 6, "max_revisions": 1})
    return cfg


def install_fake(monkeypatch, model: FakeEditorialModel) -> None:
    monkeypatch.setattr(pipeline, "_editorial_llm", lambda cfg, root: model)


def needs_ffmpeg() -> bool:
    return not (shutil.which("ffmpeg") and shutil.which("ffprobe"))


@pytest.mark.skipif(needs_ffmpeg(), reason="ffmpeg not installed")
def test_curated_run_writes_every_editorial_artifact(tmp_path: Path, monkeypatch):
    install_fake(monkeypatch, FakeEditorialModel())
    source = tmp_path / "programme.md"
    source.write_text(BODY, encoding="utf-8")
    target = run(source, tmp_path / "results", curated_config(), editorial="curated-analysis", top_k=2)
    for name in EDITORIAL_ARTIFACTS:
        assert (target / name).is_file(), name
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    for name in EDITORIAL_ARTIFACTS:
        assert name in manifest["sha256"]
    assert manifest["editorial"]["mode"] == "curated-analysis"
    assert len(manifest["editorial"]["selected"]) == 2
    assert manifest["status"] == "qa_passed"


@pytest.mark.skipif(needs_ffmpeg(), reason="ffmpeg not installed")
def test_curated_run_splits_the_aggregate_block(tmp_path: Path, monkeypatch):
    install_fake(monkeypatch, FakeEditorialModel())
    source = tmp_path / "programme.md"
    source.write_text(BODY, encoding="utf-8")
    target = run(source, tmp_path / "results", curated_config(), editorial="curated-analysis", top_k=2)
    items = json.loads((target / "news_items.json").read_text(encoding="utf-8"))
    sections = [item for item in items["items"] if item["section"] == "国内联播快讯"]
    assert len(sections) == 2
    assert all(item["split_status"] == "llm_verified" for item in sections)
    assert items["report"]["split_briefs"] == 2


@pytest.mark.skipif(needs_ffmpeg(), reason="ffmpeg not installed")
def test_curated_run_respects_top_k_and_reports_rejections(tmp_path: Path, monkeypatch):
    install_fake(monkeypatch, FakeEditorialModel())
    source = tmp_path / "programme.md"
    source.write_text(BODY, encoding="utf-8")
    target = run(source, tmp_path / "results", curated_config(), editorial="curated-analysis", top_k=2)
    selection = json.loads((target / "editorial_selection.json").read_text(encoding="utf-8"))
    assert len(selection["selected"]) <= 2
    assert selection["rejected"], "every dropped candidate must be recorded"
    assert all("reason" in row for row in selection["rejected"])
    scenes = json.loads((target / "scenes.json").read_text(encoding="utf-8"))
    narrated = {scene["source_id"] for scene in scenes} - {"opening", "closing"}
    assert narrated <= set(selection["selected"])


@pytest.mark.skipif(needs_ffmpeg(), reason="ffmpeg not installed")
def test_validate_existing_reports_the_editorial_trail(tmp_path: Path, monkeypatch):
    install_fake(monkeypatch, FakeEditorialModel())
    source = tmp_path / "programme.md"
    source.write_text(BODY, encoding="utf-8")
    cfg = curated_config()
    target = run(source, tmp_path / "results", cfg, editorial="curated-analysis", top_k=2)
    report = validate_existing(target, cfg)
    assert report["status"] == "passed"
    assert report["editorial"]["mode"] == "curated-analysis"
    assert report["editorial"]["insufficient"] is False
    assert report["public_release_approved"] is False
    assert "news facts" in report["human_review_required"]


@pytest.mark.skipif(needs_ffmpeg(), reason="ffmpeg not installed")
def test_curated_run_fails_qa_when_an_artifact_is_missing(tmp_path: Path, monkeypatch):
    install_fake(monkeypatch, FakeEditorialModel())
    source = tmp_path / "programme.md"
    source.write_text(BODY, encoding="utf-8")
    target = run(source, tmp_path / "results", curated_config(), editorial="curated-analysis", top_k=2)
    (target / "analysis_briefs.json").unlink()
    with pytest.raises(ValueError, match="hash|missing manifest asset|missing editorial artifact"):
        validate_existing(target, curated_config())


@pytest.mark.skipif(needs_ffmpeg(), reason="ffmpeg not installed")
def test_whole_manuscript_mode_writes_no_editorial_artifacts(tmp_path: Path, monkeypatch):
    model = FakeEditorialModel()
    install_fake(monkeypatch, model)
    source = tmp_path / "article.md"
    source.write_text("# 示例标题\n\n第一句话。第二句话。\n", encoding="utf-8")
    target = run(source, tmp_path / "results", curated_config())
    for name in EDITORIAL_ARTIFACTS:
        assert not (target / name).exists(), name
    assert model.calls == [], "whole-manuscript mode must not call the editorial model"
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["editorial"] == {"mode": "none"}


def test_unknown_editorial_mode_is_rejected(tmp_path: Path):
    source = tmp_path / "a.md"
    source.write_text("# 标题\n\n正文。\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported editorial mode"):
        run(source, tmp_path / "results", curated_config(), editorial="curated")


def test_curated_mode_fails_when_nothing_clears_the_threshold(tmp_path: Path, monkeypatch):
    install_fake(monkeypatch, FakeEditorialModel())
    source = tmp_path / "programme.md"
    source.write_text(BODY, encoding="utf-8")
    cfg = curated_config()
    cfg["editorial"]["min_total_score"] = 99
    with pytest.raises(ValueError, match="refusing to pad the selection"):
        run(source, tmp_path / "results", cfg, editorial="curated-analysis", top_k=2)


@pytest.mark.skipif(needs_ffmpeg(), reason="ffmpeg not installed")
def test_curated_report_records_cost_and_grounding(tmp_path: Path, monkeypatch):
    install_fake(monkeypatch, FakeEditorialModel())
    source = tmp_path / "programme.md"
    source.write_text(BODY, encoding="utf-8")
    target = run(source, tmp_path / "results", curated_config(), editorial="curated-analysis", top_k=2)
    report = json.loads((target / "editorial_report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "curated-analysis"
    assert report["llm"]["calls"] > 0
    assert report["grounding"]["invented_numbers"] == []
    assert report["grounding"]["leaked_unselected_stories"] == []
    assert report["critic"]["failed"] == []
    assert report["claims"]["FACT"] >= 1
