"""Editorial script, Layer-3 grounding and the bounded critic (task 8)."""
from __future__ import annotations

import json

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.editorial import critique as critique_module
from news_video_pipeline.editorial import scripting
from news_video_pipeline.editorial.models import (CRITIQUE_DIMENSIONS, AnalysisBrief, Claim, EditorialSelection,
                                                  SourceSpan, StoryCandidate)

SOURCE_A = "国家统计局今天发布数据，前三季度国内生产总值同比增长5.2%。"
SOURCE_B = "海关总署发布数据，出口同比增长6.1%。"
SOURCE_C = "某地建成新的地铁线路，全长30公里。"


def candidate(story_id: str, headline: str, text: str, block_index: int, cluster: str = "", **overrides) -> StoryCandidate:
    payload = dict(
        story_id=story_id,
        headline=headline,
        source_id="input_x",
        source_spans=(SourceSpan(0, len(text)),),
        source_text=text,
        block_index=block_index,
        cluster_id=cluster,
    )
    payload.update(overrides)
    return StoryCandidate(**payload)


def fact(story_id: str, text: str) -> Claim:
    return Claim(claim_id=f"{story_id}_claim_01", story_id=story_id, kind="FACT", text=text,
                 source_spans=(SourceSpan(0, len(text)),), reasoning="节目稿原文")


def brief(story_id: str, headline: str, quote: str, angle: str = "结构比总量更值得看") -> AnalysisBrief:
    return AnalysisBrief(
        story_id=story_id, headline=headline, angle=angle,
        mechanisms=("政策落地转化为需求。",), second_order=("就业可能滞后改善。",),
        counterpoints=("单月数据可能受季节影响。",), watch_indicators=("下月数据。",),
        claims=(fact(story_id, quote),), uncertainty=("缺少分省数据。",), topic="economy",
    )


@pytest.fixture()
def cfg() -> dict:
    return load_config()


@pytest.fixture()
def selection() -> EditorialSelection:
    return EditorialSelection(top_k=2, selected=("story_001", "story_002"), selection_config={})


@pytest.fixture()
def briefs() -> list[AnalysisBrief]:
    return [brief("story_001", "经济数据发布", SOURCE_A), brief("story_002", "出口数据发布", SOURCE_B)]


def script_answer(narration_a: str = "前三季度国内生产总值同比增长5.2%。", narration_b: str = "出口同比增长6.1%。",
                  opening: str = "今天最重要的信号来自两组数据。", closing: str = "值得继续观察下一组数据。") -> dict:
    return {
        "opening_hook": opening,
        "sections": [
            {"story_id": "story_001", "kind": "top", "heading": "经济数据", "narration": narration_a},
            {"story_id": "story_002", "kind": "supporting", "heading": "出口数据", "narration": narration_b},
        ],
        "closing_synthesis": closing,
    }


def scores(value: int = 9, **overrides) -> dict:
    payload = {dimension: value for dimension in CRITIQUE_DIMENSIONS}
    payload.update(overrides)
    return payload


class FakeLLM:
    """Stage-keyed answer queue, so a test can script a whole critique loop."""

    def __init__(self, answers: dict):
        self.answers = {stage: list(items) for stage, items in answers.items()}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, stage, payload, check=None):
        """Mirror EditorialLLM: validate the answer here so `check` is exercised."""
        return check(self._answer(stage, payload)) if check is not None else self._answer(stage, payload)

    def _answer(self, stage, payload):
        self.calls.append((stage, payload))
        queue = self.answers.get(stage)
        if not queue:
            raise AssertionError(f"unexpected call to stage {stage!r}")
        return queue.pop(0)

    def count(self, stage: str) -> int:
        return sum(1 for name, _ in self.calls if name == stage)


def test_build_script_produces_sections_in_order(cfg, briefs, selection):
    llm = FakeLLM({"script": [script_answer()]})
    script = scripting.build_script(briefs, selection, cfg, llm)
    assert [section.story_id for section in script.sections] == ["story_001", "story_002"]
    assert script.sections[0].kind == "top"
    assert script.title.endswith("经济数据发布")
    assert script.opening_hook in script.body
    assert llm.count("script") == 1
    json.dumps(script.to_dict(), ensure_ascii=False)


def test_build_script_sends_only_validated_briefs(cfg, briefs, selection):
    llm = FakeLLM({"script": [script_answer()]})
    scripting.build_script(briefs, selection, cfg, llm)
    payload = llm.calls[0][1]
    assert [story["story_id"] for story in payload["stories"]] == ["story_001", "story_002"]
    assert payload["stories"][0]["fact_quotes"] == [SOURCE_A]
    assert SOURCE_C not in json.dumps(payload, ensure_ascii=False)


def test_build_script_rejects_an_unknown_story_section(cfg, briefs, selection):
    answer = script_answer()
    answer["sections"][1]["story_id"] = "story_404"
    with pytest.raises(ValueError, match="story_404"):
        scripting.build_script(briefs, selection, cfg, FakeLLM({"script": [answer]}))


def test_build_script_requires_every_selected_story(cfg, briefs, selection):
    answer = script_answer()
    answer["sections"] = answer["sections"][:1]
    with pytest.raises(ValueError, match="no section was written for"):
        scripting.build_script(briefs, selection, cfg, FakeLLM({"script": [answer]}))


def test_build_script_rejects_an_empty_opening_hook(cfg, briefs, selection):
    with pytest.raises(ValueError, match="opening hook is empty"):
        scripting.build_script(briefs, selection, cfg, FakeLLM({"script": [script_answer(opening="  ")]}))


def test_build_script_rejects_empty_narration(cfg, briefs, selection):
    with pytest.raises(ValueError, match="empty narration"):
        scripting.build_script(briefs, selection, cfg, FakeLLM({"script": [script_answer(narration_a=" ")]}))


def grounded_report(cfg, selection, **kwargs):
    candidates = [
        candidate("story_001", "经济数据发布", SOURCE_A, 1, "cluster_001"),
        candidate("story_002", "出口数据发布", SOURCE_B, 2, "cluster_002"),
        candidate("story_003", "某地建成新的地铁线路", SOURCE_C, 3, "cluster_003"),
    ]
    llm = FakeLLM({"script": [script_answer(**kwargs)]})
    script = scripting.build_script([brief("story_001", "经济数据发布", SOURCE_A),
                                     brief("story_002", "出口数据发布", SOURCE_B)], selection, cfg, llm)
    return scripting.assert_selection_grounded(script, candidates, selection, cfg)


def test_layer3_allows_narration_inside_the_selected_sources(cfg, selection):
    report = grounded_report(cfg, selection)
    assert report["invented_numbers"] == []
    assert report["leaked_unselected_stories"] == []
    assert report["numerics"] == 2


def test_layer3_rejects_an_invented_number(cfg, selection):
    with pytest.raises(ValueError, match="no selected story contains"):
        grounded_report(cfg, selection, narration_a="前三季度国内生产总值同比增长7.9%。")


def test_layer3_rejects_an_unselected_story_leaking_in(cfg, selection):
    with pytest.raises(ValueError, match="unselected stor"):
        grounded_report(cfg, selection, narration_b="另外，某地建成新的地铁线路也已经通车。")


def test_layer3_ignores_a_duplicate_of_a_selected_story(cfg, selection):
    candidates = [
        candidate("story_001", "经济数据发布", SOURCE_A, 1, "cluster_001"),
        candidate("story_002", "出口数据发布", SOURCE_B, 2, "cluster_002"),
        candidate("story_004", "央视快评：经济数据发布", SOURCE_A, 4, "cluster_001", duplicate_of="story_001"),
    ]
    llm = FakeLLM({"script": [script_answer()]})
    script = scripting.build_script([brief("story_001", "经济数据发布", SOURCE_A),
                                     brief("story_002", "出口数据发布", SOURCE_B)], selection, cfg, llm)
    report = scripting.assert_selection_grounded(script, candidates, selection, cfg)
    assert report["leaked_unselected_stories"] == []


def test_layer3_requires_every_selected_story_to_exist(cfg, briefs, selection):
    script = make_script(cfg, briefs, selection)
    broken = EditorialSelection(top_k=2, selected=("story_001", "story_404"), selection_config={})
    with pytest.raises(ValueError, match="story_404 is not among the candidates"):
        scripting.assert_selection_grounded(
            script,
            [candidate("story_001", "经济数据发布", SOURCE_A, 1, "c1"),
             candidate("story_002", "出口数据发布", SOURCE_B, 2, "c2")],
            broken, cfg,
        )


def make_script(cfg, briefs, selection, **kwargs):
    llm = FakeLLM({"script": [script_answer(**kwargs)]})
    return scripting.build_script(briefs, selection, cfg, llm)


def test_script_to_scenes_honours_the_slide_contract(cfg, briefs, selection):
    script = make_script(cfg, briefs, selection)
    scenes = scripting.script_to_scenes(script, cfg)
    limit = int(cfg["planner"]["max_chars_per_scene"])
    assert [scene.id for scene in scenes] == [f"scene_{i:03d}" for i in range(1, len(scenes) + 1)]
    assert all(len(scene.body) <= limit for scene in scenes)
    assert all(scene.sentences for scene in scenes)
    assert [scene.source_id for scene in scenes][0] == "opening"
    assert scenes[-1].source_id == "closing"
    assert {scene.source_id for scene in scenes} >= {"opening", "story_001", "story_002", "closing"}


def test_script_to_scenes_refuses_to_truncate(cfg, briefs, selection):
    cfg["planner"]["max_scenes"] = 2
    script = make_script(cfg, briefs, selection)
    with pytest.raises(ValueError, match="raise the limit rather than truncate"):
        scripting.script_to_scenes(script, cfg)


def test_narration_budget_converts_the_duration_window(cfg):
    budget = scripting.narration_budget(cfg)
    assert budget["target_duration_ms"] == [360000, 600000]
    assert budget["min_chars"] == int(360 * 3.28)
    assert budget["max_chars"] == int(600 * 3.28)
    assert budget["hard_max_chars"] == int(budget["max_chars"] * 1.15)


def test_check_length_flags_an_over_long_script(cfg, briefs, selection):
    script = make_script(cfg, briefs, selection)
    short = scripting.check_length(script, cfg)
    assert short["over"] is False
    cfg["editorial"]["speech_chars_per_second"] = 0.01
    over = scripting.check_length(script, cfg)
    assert over["over"] is True and over["chars"] == short["chars"]


def test_critique_gate_refuses_an_over_long_script(cfg, briefs, selection):
    script = make_script(cfg, briefs, selection)
    cfg["editorial"]["speech_chars_per_second"] = 0.01
    report = critique_module.critique(script, briefs, cfg, FakeLLM(
        {"critique": [{"scores": scores(9), "problems": []}]}))
    assert report["length"]["over"] is True
    assert any("超出时长预算" in problem for problem in report["problems"])
    with pytest.raises(ValueError, match="above the hard ceiling"):
        critique_module.critique_gate(report, cfg)


def test_validate_rubric_rejects_malformed_scores():
    with pytest.raises(ValueError, match="missing dimension"):
        scripting.validate_rubric({d: 5 for d in CRITIQUE_DIMENSIONS[:-1]}, "critique")
    with pytest.raises(ValueError, match="unknown dimension"):
        scripting.validate_rubric({**{d: 5 for d in CRITIQUE_DIMENSIONS}, "vibes": 1}, "critique")
    with pytest.raises(ValueError, match="integer"):
        scripting.validate_rubric({d: "8" for d in CRITIQUE_DIMENSIONS}, "critique")
    with pytest.raises(ValueError, match="0..10"):
        scripting.validate_rubric({**{d: 8 for d in CRITIQUE_DIMENSIONS}, "clarity": 11}, "critique")


def test_critique_reports_failing_dimensions(cfg, briefs, selection):
    script = make_script(cfg, briefs, selection)
    llm = FakeLLM({"critique": [{"scores": scores(clarity=3), "problems": ["开场缺少明确问题。"]}]})
    report = critique_module.critique(script, briefs, cfg, llm)
    assert report["failed"] == ["clarity"]
    with pytest.raises(ValueError, match="clarity 3<7"):
        critique_module.critique_gate(report, cfg)


def test_critique_gate_passes_a_good_script(cfg, briefs, selection):
    script = make_script(cfg, briefs, selection)
    llm = FakeLLM({"critique": [{"scores": scores(9), "problems": []}]})
    report = critique_module.critique(script, briefs, cfg, llm)
    critique_module.critique_gate(report, cfg)
    assert report["failed"] == []


def test_critique_rejects_a_problem_that_is_not_a_string(cfg, briefs, selection):
    script = make_script(cfg, briefs, selection)
    llm = FakeLLM({"critique": [{"scores": scores(), "problems": [{"text": "问题"}]}]})
    with pytest.raises(ValueError, match="problems"):
        critique_module.critique(script, briefs, cfg, llm)


def test_build_script_with_critique_returns_on_a_passing_review(cfg, briefs, selection):
    candidates = [candidate("story_001", "经济数据发布", SOURCE_A, 1, "c1"),
                  candidate("story_002", "出口数据发布", SOURCE_B, 2, "c2")]
    llm = FakeLLM({"script": [script_answer()], "critique": [{"scores": scores(9), "problems": []}]})
    script, report = critique_module.build_script_with_critique(briefs, selection, cfg, llm, candidates)
    assert report["failed"] == []
    assert script.critique["scores"]["clarity"] == 9
    assert llm.count("script") == 1


def test_an_over_long_script_is_sent_back_for_revision(cfg, briefs, selection):
    cfg["editorial"]["max_revisions"] = 1
    cfg["editorial"]["speech_chars_per_second"] = 0.05
    candidates = [candidate("story_001", "经济数据发布", SOURCE_A, 1, "c1"),
                  candidate("story_002", "出口数据发布", SOURCE_B, 2, "c2")]
    llm = FakeLLM({
        "script": [script_answer(), script_answer()],
        "critique": [{"scores": scores(9), "problems": []}, {"scores": scores(9), "problems": []}],
    })
    with pytest.raises(ValueError, match="still below threshold after 1 revision"):
        critique_module.build_script_with_critique(briefs, selection, cfg, llm, candidates)
    assert llm.count("script") == 2, "the over-long script must be revised, not published"


def test_build_script_with_critique_revises_then_gives_up(cfg, briefs, selection):
    cfg["editorial"]["max_revisions"] = 2
    candidates = [candidate("story_001", "经济数据发布", SOURCE_A, 1, "c1"),
                  candidate("story_002", "出口数据发布", SOURCE_B, 2, "c2")]
    bad = {"scores": scores(analytical_depth=1), "problems": ["只是复述了数据。"]}
    llm = FakeLLM({
        "script": [script_answer(), script_answer(), script_answer()],
        "critique": [bad, bad, bad],
    })
    with pytest.raises(ValueError, match="still below threshold after 2 revision"):
        critique_module.build_script_with_critique(briefs, selection, cfg, llm, candidates)
    assert llm.count("critique") == 3
    assert llm.count("script") == 3


def test_build_script_with_critique_stops_when_a_revision_returns_a_good_script(cfg, briefs, selection):
    cfg["editorial"]["max_revisions"] = 2
    candidates = [candidate("story_001", "经济数据发布", SOURCE_A, 1, "c1"),
                  candidate("story_002", "出口数据发布", SOURCE_B, 2, "c2")]
    llm = FakeLLM({
        "script": [script_answer(), script_answer(narration_a="前三季度国内生产总值同比增长5.2%。这是一个结构性信号。")],
        "critique": [{"scores": scores(clarity=2), "problems": ["开场太快。"]},
                     {"scores": scores(9), "problems": []}],
    })
    script, report = critique_module.build_script_with_critique(briefs, selection, cfg, llm, candidates)
    assert report["failed"] == []
    assert llm.count("script") == 2
    assert llm.count("critique") == 2
    assert "结构性信号" in script.body


def test_build_script_with_critique_discards_a_revision_that_breaks_grounding(cfg, briefs, selection):
    cfg["editorial"]["max_revisions"] = 1
    candidates = [candidate("story_001", "经济数据发布", SOURCE_A, 1, "c1"),
                  candidate("story_002", "出口数据发布", SOURCE_B, 2, "c2")]
    llm = FakeLLM({
        "script": [script_answer(), script_answer(narration_a="增长7.9%。")],
        "critique": [{"scores": scores(clarity=2), "problems": ["太平淡。"]}],
    })
    with pytest.raises(ValueError, match="still below threshold"):
        critique_module.build_script_with_critique(briefs, selection, cfg, llm, candidates)
