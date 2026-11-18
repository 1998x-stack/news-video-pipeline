"""The editorial critic: a bounded, specific quality gate.

The critic does not invent opinions. It scores the script against the rubric and
must name concrete problems. Revision is bounded by ``editorial.max_revisions``
and then fails, so the pipeline can never spin: repeated model calls are not
evidence of quality, and a script that never clears the gate is reported as a
failure rather than published.
"""
from __future__ import annotations

from dataclasses import replace

from .models import CRITIQUE_DIMENSIONS, AnalysisBrief, EditorialScript, EditorialSelection
from .scripting import (_script_from_answer, assert_selection_grounded, build_script, check_length,
                        narration_budget, validate_rubric)


def script_view(script: EditorialScript) -> dict:
    return {
        "title": script.title,
        "opening_hook": script.opening_hook,
        "sections": [
            {"story_id": section.story_id, "kind": section.kind, "heading": section.heading,
             "narration": section.narration}
            for section in script.sections
        ],
        "closing_synthesis": script.closing_synthesis,
    }


def brief_view(briefs: list[AnalysisBrief]) -> list[dict]:
    return [
        {
            "story_id": brief.story_id,
            "headline": brief.headline,
            "angle": brief.angle,
            "mechanisms": list(brief.mechanisms),
            "counterpoints": list(brief.counterpoints),
            "uncertainty": list(brief.uncertainty),
            "fact_quotes": [claim.text for claim in brief.claims if claim.kind == "FACT"],
        }
        for brief in briefs
    ]


def critique(script: EditorialScript, briefs: list[AnalysisBrief], cfg: dict, llm) -> dict:
    """Score the script and collect specific, checkable problems."""
    return llm("critique", {"script": script_view(script), "stories": brief_view(briefs)},
               check=lambda answer: _parse_critique(answer, script, cfg))


def _parse_critique(answer: dict, script: EditorialScript, cfg: dict) -> dict:
    scores = validate_rubric(answer.get("scores"), "critique")
    raw_problems = answer.get("problems") or []
    if not isinstance(raw_problems, list) or any(not isinstance(item, str) or not item.strip() for item in raw_problems):
        raise ValueError("critique: 'problems' must be an array of non-empty strings")
    thresholds = cfg["editorial"]["critique_min"]
    below = [dimension for dimension in CRITIQUE_DIMENSIONS if scores[dimension] < int(thresholds[dimension])]
    length = check_length(script, cfg)
    if length["over"]:
        raw_problems.append(
            f"稿件超出时长预算：{length['chars']} 字 > 上限 {length['hard_max_chars']} 字，请压缩表达而不是删除事实"
        )
    return {
        "scores": scores,
        "problems": [item.strip() for item in raw_problems],
        "length": length,
        "failed": below,
        "thresholds": {dimension: int(thresholds[dimension]) for dimension in CRITIQUE_DIMENSIONS},
    }


def critique_gate(report: dict, cfg: dict) -> None:
    """Raise with the failing dimensions instead of publishing a weak script."""
    if report.get("length", {}).get("over"):
        length = report["length"]
        raise ValueError(
            f"Editorial script is {length['chars']} characters, above the hard ceiling "
            f"{length['hard_max_chars']} for target_duration_ms={length['target_duration_ms']}; "
            "refusing to publish an over-long video (narration is never truncated)"
        )
    if report["failed"]:
        detail = "; ".join(f"{dimension} {report['scores'][dimension]}<{report['thresholds'][dimension]}"
                           for dimension in report["failed"])
        problems = "; ".join(report["problems"][:5]) or "no specific problem was given"
        raise ValueError(f"Editorial critique below threshold ({detail}); problems: {problems}")


def revise_script(script: EditorialScript, briefs: list[AnalysisBrief], selection: EditorialSelection,
                  report: dict, cfg: dict, llm) -> EditorialScript:
    """One bounded revision driven by the critic's named problems."""
    return llm("script", {
        "revision": True,
        "attempt": 1,
        "previous": script_view(script),
        "failed_dimensions": report["failed"],
        "problems": report["problems"],
        "narration_char_budget": narration_budget(cfg),
        "stories": brief_view(briefs),
        "selected": list(selection.selected),
        "target_duration_ms": list(cfg["editorial"]["target_duration_ms"]),
    }, check=lambda answer: _script_from_answer(answer, briefs, selection, cfg, report))


def build_script_with_critique(briefs: list[AnalysisBrief], selection: EditorialSelection, cfg: dict, llm,
                               candidates: list) -> tuple[EditorialScript, dict]:
    """Write, critique, revise (bounded), and re-verify grounding after every change."""
    if not briefs:
        raise ValueError("build_script_with_critique: no briefs to script")
    limit = int(cfg["editorial"]["max_revisions"])
    script = build_script(briefs, selection, cfg, llm)
    assert_selection_grounded(script, candidates, selection, cfg)
    last: dict = {}
    for attempt in range(limit + 1):
        last = critique(script, briefs, cfg, llm)
        script = replace(script, critique=last)
        if not last["failed"] and not last["length"]["over"]:
            return script, last
        if attempt < limit:
            original = script
            script = revise_script(script, briefs, selection, last, cfg, llm)
            try:
                assert_selection_grounded(script, candidates, selection, cfg)
            except ValueError:
                script = original  # a revision that breaks grounding is discarded
                break
    raise ValueError(
        f"Editorial critique still below threshold after {limit} revision(s): "
        f"dimensions={last.get('failed')} length={last.get('length', {}).get('chars')}; "
        f"problems: {last.get('problems')}"
    )
