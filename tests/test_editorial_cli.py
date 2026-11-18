"""CLI surface for the editorial stages (task 10)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from news_video_pipeline import cli, pipeline

BRIEF_TWO = "2026年版国家基本医保药品目录发布 新增107种药品"
BODY = (
    "新闻联播\n\n"
    "国内联播快讯\n"
    "国家防总办公室安排部署凌汛期防凌工作会议要求严格落实责任制，确保防凌安全。"
    f"{BRIEF_TWO}目录于明年1月1日起正式实施，药品总数达到3331个。\n\n"
    "政策发力显效 多项先行指标持续改善\n"
    "全国工程机械开工率同比提高，投资指标持续回暖。新型基础设施项目中标金额明显增长。\n\n"
    "中共中央印发《中国共产党地方委员会工作条例》\n"
    "中共中央印发《中国共产党地方委员会工作条例》，对地方党委工作进行规范。\n\n"
    "2026年APEC领导人会议周活动逐步升温\n"
    "2026年APEC高官会在深圳举行，会议为期两天。\n"
)


class FakeEditorialModel:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, stage, payload, check=None):
        """Mirror EditorialLLM: validate the answer here so `check` is exercised."""
        result = self._answer(stage, payload)
        return check(result) if check is not None else result

    def _answer(self, stage: str, payload: dict) -> dict:
        self.calls.append(stage)
        if stage == "aggregate_split":
            text = payload["text"]
            index = text.index(BRIEF_TWO)
            return {"items": [text[:index], text[index:]]}
        if stage == "rank":
            dimensions = ("public_impact", "structural_importance", "information_novelty", "analytical_depth",
                          "timeliness", "evidence_quality", "audience_utility")
            return {"ratings": [
                {"story_id": story["story_id"],
                 "scores": {d: (9 if story["story_id"] in {"story_001", "story_003"} else 6) for d in dimensions},
                 "reasons": {d: "依据原文具体数据。" for d in dimensions},
                 "topic": "economy" if story["story_id"] == "story_001" else "politics",
                 "confidence": 0.9, "new_information": ["新增信息。"], "uncertainties": []}
                for story in payload["stories"]
            ]}
        if stage == "compare":
            return {"comparisons": [
                {"story_id": story["story_id"], "same_event_as": None, "repeat_without_progress": False,
                 "adjustment": 0, "note": "与原文一致", "evidence_gap": False}
                for story in payload["candidates"]
            ]}
        if stage == "brief":
            quote = payload["text"].split("。")[0] + "。"
            return {"brief": {
                "angle": "这条新闻的价值在于政策落地与需求之间的传导关系。",
                "mechanisms": ["政策工具先行，随后投资与开工数据改善，形成可观察的传导链条。"],
                "second_order": ["如果传导延续，下一个观察点是就业。"],
                "counterpoints": ["单月数据可能受季节因素影响。"],
                "watch_indicators": ["下月开工率。"],
                "uncertainty": ["缺少分省数据。"],
                "claims": [
                    {"claim_id": "c1", "kind": "FACT", "text": quote, "quote": quote, "reasoning": "原文"},
                    {"claim_id": "c2", "kind": "INFERENCE", "text": "这意味着传导链条正在形成。",
                     "quote": quote, "depends_on": ["c1"], "reasoning": "由事实推出"},
                ],
            }}
        if stage == "script":
            sections = [
                {"story_id": story["story_id"], "kind": "top" if index == 0 else "supporting",
                 "heading": story["headline"][:20],
                 "narration": f"{story['angle']}{(story.get('fact_quotes') or [story['headline']])[0]}"}
                for index, story in enumerate(payload["stories"])
            ]
            return {"opening_hook": "今天最值得关注的信号来自政策与需求之间的传导。",
                    "sections": sections,
                    "closing_synthesis": "共同线索是政策节奏正在向实际需求转化，值得继续观察。"}
        if stage == "critique":
            return {"scores": {d: 9 for d in ("factual_grounding", "analytical_depth", "original_insight",
                                              "clarity", "audience_utility", "uncertainty_handling",
                                              "narrative_coherence")}, "problems": []}
        raise AssertionError(f"unexpected stage {stage}")

    def summary(self) -> dict:
        return {"calls": len(self.calls), "requests": len(self.calls), "cache_hits": 0, "failures": 0,
                "latency_s": 0.0, "stages": []}


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    path = tmp_path / "programme.md"
    path.write_text(BODY, encoding="utf-8")
    return path


@pytest.fixture()
def fake(monkeypatch) -> FakeEditorialModel:
    model = FakeEditorialModel()
    monkeypatch.setattr(pipeline, "_editorial_llm", lambda cfg, root: model)
    return model


def test_extract_writes_news_items_and_reports_counts(tmp_path: Path, source: Path, fake, capsys):
    code = cli.main(["editorial", "extract", "--input", str(source), "--out", str(tmp_path / "e")])
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0
    assert payload["stage"] == "extract"
    assert payload["candidates"] == 5
    assert payload["aggregate_blocks"] == 1
    assert payload["split_briefs"] == 2
    written = json.loads((tmp_path / "e" / "news_items.json").read_text(encoding="utf-8"))
    assert written["report"]["candidates"] == 5


def test_extract_works_without_a_model(tmp_path: Path, source: Path, monkeypatch, capsys):
    """Splitting is attempted, but a missing model degrades to `uncertain`, not to data loss."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    code = cli.main(["editorial", "extract", "--input", str(source), "--out", str(tmp_path / "e")])
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0
    assert payload["candidates"] == 4
    assert payload["uncertain_blocks"] == 1


def test_rank_prints_a_bounded_table(tmp_path: Path, source: Path, fake, capsys):
    out = tmp_path / "e"
    assert cli.main(["editorial", "extract", "--input", str(source), "--out", str(out)]) == 0
    capsys.readouterr()
    code = cli.main(["editorial", "rank", "--input", str(source), "--out", str(out), "--show", "3"])
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0
    assert len(payload["top"]) == 3
    assert payload["ranked"] == 5
    assert payload["top"][0]["rank"] == 1
    rows = json.loads((out / "editorial_ranking.json").read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 5


def test_select_never_exceeds_top_k(tmp_path: Path, source: Path, fake, capsys):
    out = tmp_path / "e"
    cli.main(["editorial", "extract", "--input", str(source), "--out", str(out)])
    cli.main(["editorial", "rank", "--input", str(source), "--out", str(out)])
    capsys.readouterr()
    code = cli.main(["editorial", "select", "--input", str(source), "--out", str(out), "--top-k", "3"])
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0
    assert payload["top_k"] == 3
    assert len(payload["selected"]) <= 3
    assert payload["rejected"], "drops must be reported"


def test_script_stage_writes_the_narration_and_scenes(tmp_path: Path, source: Path, fake, capsys):
    out = tmp_path / "e"
    cli.main(["editorial", "extract", "--input", str(source), "--out", str(out)])
    cli.main(["editorial", "rank", "--input", str(source), "--out", str(out)])
    cli.main(["editorial", "select", "--input", str(source), "--out", str(out), "--top-k", "2"])
    capsys.readouterr()
    code = cli.main(["editorial", "script", "--input", str(source), "--out", str(out), "--top-k", "2"])
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0
    assert payload["stage"] == "script"
    assert payload["critique_failed"] == []
    assert (out / "editorial_script.md").is_file()
    assert (out / "analysis_briefs.json").is_file()
    assert (out / "claims.json").is_file()
    assert (out / "scenes.json").is_file()
    scenes = json.loads((out / "scenes.json").read_text(encoding="utf-8"))
    assert {scene["source_id"] for scene in scenes} >= {"opening", "closing"}


def test_stages_reuse_earlier_artifacts_without_recalling_the_model(tmp_path: Path, source: Path, fake, capsys):
    out = tmp_path / "e"
    cli.main(["editorial", "extract", "--input", str(source), "--out", str(out)])
    cap_calls = list(fake.calls)
    capsys.readouterr()
    cli.main(["editorial", "rank", "--input", str(source), "--out", str(out)])
    assert fake.calls.count("aggregate_split") == cap_calls.count("aggregate_split") == 1
    assert fake.calls.count("rank") == 1


def test_refresh_reextracts(tmp_path: Path, source: Path, fake, capsys):
    out = tmp_path / "e"
    cli.main(["editorial", "extract", "--input", str(source), "--out", str(out)])
    cli.main(["editorial", "extract", "--input", str(source), "--out", str(out), "--refresh"])
    capsys.readouterr()
    assert fake.calls.count("aggregate_split") == 2


def test_unknown_editorial_stage_is_a_usage_error(source: Path, capsys):
    with pytest.raises(SystemExit):
        cli.main(["editorial", "summarise", "--input", str(source)])


def test_unknown_mode_is_rejected_before_any_work(source: Path):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["plan", "--input", str(source), "--editorial", "curated"])
    assert exit_info.value.code == 2  # argparse rejects the choice before any work starts


def test_invalid_mode_in_a_config_file_exits_one_with_a_message(tmp_path: Path, source: Path, capsys):
    broken = tmp_path / "broken.yaml"
    broken.write_text("editorial:\n  mode: curated\n", encoding="utf-8")
    code = cli.main(["plan", "--input", str(source), "--config", str(broken)])
    assert code == 1
    assert "editorial.mode" in capsys.readouterr().err


def test_run_reports_a_pipeline_error_as_exit_code_one(tmp_path: Path, source: Path, capsys):
    code = cli.main(["run", "--input", str(source), "--editorial", "curated-analysis",
                     "--out", str(tmp_path / "results"), "--tts", "synthetic"])
    assert code == 1
    assert "ERROR" in capsys.readouterr().err


def test_validate_reports_editorial_metadata(tmp_path: Path, source: Path, fake, capsys):
    out = tmp_path / "results"
    # This tiny synthetic fixture deliberately targets a short clip. The CLI
    # validator must recover the actual render config from the manifest rather
    # than wrongly validating with the default 6-10 minute production window.
    config_file = tmp_path / "tiny-fixture.yaml"
    config_file.write_text("editorial:\\n  target_duration_ms: [1, 600000]\\n".replace("\\n", "\n"), encoding="utf-8")
    assert cli.main(["run", "--input", str(source), "--out", str(out), "--tts", "synthetic",
                     "--editorial", "curated-analysis", "--top-k", "2", "--config", str(config_file)]) == 0
    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert result["result"] == "qa_passed"
    directory = Path(result["directory"])
    capsys.readouterr()
    assert cli.main(["validate", str(directory)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["editorial"]["mode"] == "curated-analysis"
    assert report["assets_verified"] > 0
    assert report["public_release_approved"] is False


def test_plan_keeps_the_whole_manuscript_path(source: Path, capsys):
    assert cli.main(["plan", "--input", str(source)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "editorial" not in payload
    assert payload["scenes"]
