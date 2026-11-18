"""The editorial script, the scene contract and Layer-3 grounding.

The script is the reviewed narration. Scenes are derived from *it*, never from the
raw programme again, so an unselected story cannot reappear downstream.

Layer-3 grounding (``assert_selection_grounded``) is what replaces the old global
retention ratio in curated mode:

* every number spoken must exist in the source of a selected story — an invented
  figure is a hard failure;
* an *unselected* story's distinctive wording may not appear, so a dropped story
  cannot leak into the video;
* a story dropped only because it duplicates a selected one is not treated as an
  unselected story, because it is the same event;
* every FACT claim was already anchored by ``evidence.validate_claims``.

Layer 2 (deliberate deselection) is recorded in ``editorial_selection.json``, and
Layer 1 (verbatim source retention) is untouched: ``source.txt`` keeps the whole
programme with its SHA-256.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import (CRITIQUE_DIMENSIONS, AnalysisBrief, EditorialScript, EditorialSection,
                     EditorialSelection, StoryCandidate)
from ..models import Scene
from ..planner import TITLE_LIMIT, normalize_text, pack_narration, sentences, title_from

NUMERIC = re.compile(r"\d+(?:[.,]\d+)*")
SECTION_KINDS = {"top", "supporting"}
MIN_DISTINCTIVE_CHARS = 8
LEAK_SUBSTRING = 12


def validate_rubric(scores: dict, stage: str) -> dict[str, int]:
    """Same fail-closed checks as the ranking rubric, for the critic's dimensions."""
    if not isinstance(scores, dict):
        raise ValueError(f"{stage}: scores must be a JSON object")
    missing = [d for d in CRITIQUE_DIMENSIONS if d not in scores]
    if missing:
        raise ValueError(f"{stage}: missing dimension(s) {missing}; every dimension must be judged")
    unknown = [key for key in scores if key not in CRITIQUE_DIMENSIONS]
    if unknown:
        raise ValueError(f"{stage}: unknown dimension(s) {unknown}")
    for dimension, value in scores.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{stage}: {dimension} must be an integer score, got {value!r}")
        if not 0 <= value <= 10:
            raise ValueError(f"{stage}: {dimension} must be within 0..10, got {value}")
    return dict(scores)


def narration_budget(cfg: dict) -> dict:
    """Convert the 6-10 minute target into a spoken-character budget.

    The clock stays the TTS sample count; this budget is how the *writer* is asked to
    fit it. It is never enforced by cutting narration afterwards.
    """
    options = cfg["editorial"]
    low_ms, high_ms = [int(x) for x in options["target_duration_ms"]]
    rate = float(options["speech_chars_per_second"])
    tolerance = float(options["length_tolerance"])
    minimum = int(low_ms / 1000 * rate)
    maximum = int(high_ms / 1000 * rate)
    return {
        "min_chars": minimum,
        "max_chars": maximum,
        "hard_max_chars": int(maximum * tolerance),
        "speech_chars_per_second": rate,
        "target_duration_ms": [low_ms, high_ms],
    }


def narration_chars(script: EditorialScript) -> int:
    return len(narration_text(script))


def check_length(script: EditorialScript, cfg: dict) -> dict:
    """Deterministic length verdict: under, in-window, or over the hard ceiling."""
    budget = narration_budget(cfg)
    chars = narration_chars(script)
    return {
        "chars": chars,
        **budget,
        "over": chars > budget["hard_max_chars"],
        "under": chars < budget["min_chars"],
        "note": (
            "Length is measured in spoken characters and never fixed by truncation; "
            "an out-of-budget script is sent back for a bounded revision and then fails."
        ),
    }


def script_payload(briefs: list[AnalysisBrief], selection: EditorialSelection, cfg: dict) -> dict:
    """What the script writer sees: validated briefs, not the raw programme."""
    return {
        "top_k": selection.top_k,
        "target_duration_ms": list(cfg["editorial"]["target_duration_ms"]),
        "narration_char_budget": narration_budget(cfg),
        "selected": list(selection.selected),
        "stories": [
            {
                "story_id": brief.story_id,
                "headline": brief.headline,
                "angle": brief.angle,
                "mechanisms": list(brief.mechanisms),
                "second_order": list(brief.second_order),
                "watch_indicators": list(brief.watch_indicators),
                "uncertainty": list(brief.uncertainty),
                "fact_quotes": [claim.text for claim in brief.claims if claim.kind == "FACT"],
            }
            for brief in briefs
        ],
    }


def parse_sections(raw_sections, story_ids: list[str], selected: list[str]) -> tuple[EditorialSection, ...]:
    """Validate the section list: every selected story once, no invented story."""
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("script: 'sections' must be a non-empty JSON array")
    known = set(story_ids)
    seen: list[str] = []
    sections: list[EditorialSection] = []
    for raw in raw_sections:
        if not isinstance(raw, dict):
            raise ValueError("script: every section must be a JSON object")
        story_id = str(raw.get("story_id", ""))
        if story_id not in known:
            raise ValueError(f"script: section refers to unknown story_id {story_id!r}")
        if story_id in seen:
            raise ValueError(f"script: {story_id} appears in more than one section")
        seen.append(story_id)
        kind = str(raw.get("kind") or "supporting").strip()
        if kind not in SECTION_KINDS:
            raise ValueError(f"script: unknown section kind {kind!r}; expected one of {sorted(SECTION_KINDS)}")
        narration = str(raw.get("narration") or "").strip()
        if not narration:
            raise ValueError(f"script: section {story_id} has empty narration")
        sections.append(EditorialSection(
            story_id=story_id,
            heading=title_from(str(raw.get("heading") or "") or narration),
            narration=narration,
            kind=kind,
        ))
    missing = [story_id for story_id in selected if story_id not in seen]
    if missing:
        raise ValueError(f"script: no section was written for {missing}")
    return tuple(sections)


def build_script(briefs: list[AnalysisBrief], selection: EditorialSelection, cfg: dict, llm) -> EditorialScript:
    """One bounded call that writes the narration from the validated briefs."""
    if not briefs:
        raise ValueError("build_script: no analysis briefs; refusing to write a script from nothing")
    ids = [brief.story_id for brief in briefs]
    return llm("script", script_payload(briefs, selection, cfg),
               check=lambda answer: _script_from_answer(answer, briefs, selection, cfg))


def _script_from_answer(answer: dict, briefs: list[AnalysisBrief], selection: EditorialSelection,
                        cfg: dict, critique_report: dict | None = None) -> EditorialScript:
    """Build the script from one model answer, or fail closed (runs inside the call)."""
    ids = [brief.story_id for brief in briefs]
    opening = str(answer.get("opening_hook") or "").strip()
    closing = str(answer.get("closing_synthesis") or "").strip()
    if not opening:
        raise ValueError("script: the opening hook is empty; the video would start with filler")
    if not closing:
        raise ValueError("script: the closing synthesis is empty")
    sections = parse_sections(answer.get("sections"), ids, list(selection.selected))
    top = next((s for s in sections if s.kind == "top"), sections[0])
    headline = next((brief.headline for brief in briefs if brief.story_id == top.story_id), "")
    title = f"{cfg['project']['title_prefix']}｜{headline[:TITLE_LIMIT]}" if headline else cfg["project"]["title_prefix"]
    body = "\n".join([opening, *[section.narration for section in sections], closing])
    return EditorialScript(
        title=title,
        opening_hook=opening,
        sections=sections,
        closing_synthesis=closing,
        body=body,
        story_ids=tuple(ids),
        critique=critique_report or {},
    )


def narration_text(script: EditorialScript) -> str:
    return "\n".join([script.opening_hook, *[s.narration for s in script.sections], script.closing_synthesis])


def _longest_common_substring(a: str, b: str) -> int:
    if not a or not b:
        return 0
    return max((block.size for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()), default=0)


def assert_selection_grounded(script: EditorialScript, candidates: list[StoryCandidate],
                              selection: EditorialSelection, cfg: dict) -> dict:
    """Refuse to render narration the selected stories cannot support."""
    narration = narration_text(script)
    normalized = normalize_text(narration)
    by_id = {item.story_id: item for item in candidates}
    selected_clusters = {by_id[story_id].cluster_id for story_id in selection.selected if story_id in by_id}
    allowed = set()
    for story_id in selection.selected:
        candidate = by_id.get(story_id)
        if candidate is None:
            raise ValueError(f"assert_selection_grounded: selected story {story_id} is not among the candidates")
        allowed |= set(NUMERIC.findall(candidate.source_text))
    invented = sorted(set(NUMERIC.findall(narration)) - allowed)
    if invented:
        raise ValueError(
            f"Script states number(s) {invented} that no selected story contains; refusing to render unverified output"
        )
    leaked: list[str] = []
    for candidate in candidates:
        if candidate.story_id in selection.selected:
            continue
        if candidate.cluster_id and candidate.cluster_id in selected_clusters:
            continue  # same event as a selected story, not a separate dropped story
        headline = normalize_text(candidate.headline)
        if len(headline) < MIN_DISTINCTIVE_CHARS:
            continue
        if headline in normalized or _longest_common_substring(headline, normalized) >= LEAK_SUBSTRING:
            leaked.append(candidate.story_id)
    if leaked:
        raise ValueError(
            f"Script appears to narrate unselected stor(ies) {leaked}; curated mode must not cover them"
        )
    return {
        "numerics": len(set(NUMERIC.findall(narration))),
        "invented_numbers": invented,
        "leaked_unselected_stories": leaked,
        "selected": list(selection.selected),
        "stories_in_script": list(script.story_ids),
    }


def script_to_scenes(script: EditorialScript, cfg: dict) -> list:
    """Derive scenes from the reviewed script; the slide contract still applies."""
    limit = int(cfg["planner"]["max_chars_per_scene"])
    plan: list[tuple[str, str, list[str]]] = []
    plan.extend(("opening", title_from(script.opening_hook), group)
                for group in pack_narration(sentences(script.opening_hook), limit))
    for section in script.sections:
        for group in pack_narration(sentences(section.narration), limit):
            plan.append((section.story_id, section.heading, group))
    plan.extend(("closing", "结语", group)
                for group in pack_narration(sentences(script.closing_synthesis), limit))
    if len(plan) > int(cfg["planner"]["max_scenes"]):
        raise ValueError(
            f"Editorial script needs {len(plan)} scenes; planner.max_scenes={cfg['planner']['max_scenes']}; "
            "raise the limit rather than truncate the script"
        )
    scenes = []
    for index, (source_id, heading, group) in enumerate(plan, 1):
        scenes.append(Scene(
            id=f"scene_{index:03d}",
            title=heading or title_from(group[0]),
            body="".join(group),
            sentences=tuple(group),
            source_id=source_id,
        ))
    return scenes
