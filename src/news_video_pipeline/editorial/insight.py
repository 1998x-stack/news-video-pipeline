"""Independent analysis of the selected stories.

One bounded call per selected story, then every claim is verified before it can
reach the script. The brief must actually contain an angle and at least one
mechanism — a brief that merely restates the headline is not analysis — and no
number anywhere in it may come from outside that story's own source text.
"""
from __future__ import annotations

import re

from .evidence import claim_from_llm, validate_claims
from .models import AnalysisBrief, Claim, StoryCandidate

NUMERIC = re.compile(r"\d+(?:[.,]\d+)*")
FREE_TEXT_FIELDS = ("angle", "mechanisms", "second_order", "counterpoints", "watch_indicators", "uncertainty")


def _text_list(value, field: str, story_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise ValueError(f"{story_id}: {field} must be an array of strings")
    if not isinstance(value, list):
        raise ValueError(f"{story_id}: {field} must be an array of strings")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{story_id}: {field} contains an empty entry")
        out.append(item.strip())
    return tuple(out)


def _check_numbers(brief_text: dict, candidate: StoryCandidate) -> None:
    allowed = set(NUMERIC.findall(candidate.source_text))
    for field in FREE_TEXT_FIELDS:
        value = brief_text.get(field)
        pieces = [value] if isinstance(value, str) else list(value or [])
        for piece in pieces:
            invented = sorted(set(NUMERIC.findall(str(piece))) - allowed)
            if invented:
                raise ValueError(
                    f"{candidate.story_id}: {field} states number(s) {invented} that are not in the story source; "
                    "refusing to publish an unsourced figure"
                )


def build_brief(raw: dict, candidate: StoryCandidate, cfg: dict) -> AnalysisBrief:
    """Turn one model answer into a validated AnalysisBrief."""
    story_id = candidate.story_id
    angle = str(raw.get("angle") or "").strip()
    if not angle:
        raise ValueError(f"{story_id}: the brief has no angle; a restatement of the headline is not analysis")
    mechanisms = _text_list(raw.get("mechanisms"), "mechanisms", story_id)
    if not mechanisms:
        raise ValueError(f"{story_id}: the brief explains no mechanism; analytical_depth would be zero")
    fields = {
        "angle": angle,
        "mechanisms": mechanisms,
        "second_order": _text_list(raw.get("second_order"), "second_order", story_id),
        "counterpoints": _text_list(raw.get("counterpoints"), "counterpoints", story_id),
        "watch_indicators": _text_list(raw.get("watch_indicators"), "watch_indicators", story_id),
        "uncertainty": _text_list(raw.get("uncertainty"), "uncertainty", story_id),
    }
    _check_numbers(fields, candidate)

    raw_claims = raw.get("claims")
    if raw_claims is None:
        raw_claims = []
    if not isinstance(raw_claims, list):
        raise ValueError(f"{story_id}: claims must be an array")
    names: dict[str, str] = {}
    entries: list[tuple[str, dict]] = []
    for position, entry in enumerate(raw_claims, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"{story_id}: every claim must be a JSON object")
        local = str(entry.get("claim_id") or f"claim_{position:02d}").strip()
        if local in names:
            raise ValueError(f"{story_id}: claim_id {local!r} is used twice")
        names[local] = f"{story_id}_claim_{position:02d}"
        entries.append((names[local], entry))
    built: dict[str, Claim] = {}
    for name, entry in entries:
        if str(entry.get("kind", "")).strip().upper() != "FACT":
            continue
        built[name] = claim_from_llm({**entry, "depends_on": []}, story_id, candidate, name, built)
    for name, entry in entries:
        if str(entry.get("kind", "")).strip().upper() == "FACT":
            continue
        dependencies = entry.get("depends_on") or []
        if not isinstance(dependencies, list):
            raise ValueError(f"{story_id}: depends_on must be an array")
        built[name] = claim_from_llm(
            {**entry, "depends_on": [names.get(str(d), str(d)) for d in dependencies]},
            story_id, candidate, name, built,
        )
    claims = [built[name] for name, _ in entries]
    report = validate_claims(claims, candidate, cfg)
    if report["counts"]["FACT"] == 0:
        raise ValueError(
            f"{story_id}: the brief contains no FACT claim; every analysis must show what the source actually says"
        )
    return AnalysisBrief(
        story_id=story_id,
        headline=candidate.headline,
        angle=fields["angle"],
        mechanisms=fields["mechanisms"],
        second_order=fields["second_order"],
        counterpoints=fields["counterpoints"],
        watch_indicators=fields["watch_indicators"],
        claims=tuple(claims),
        uncertainty=fields["uncertainty"],
        topic=candidate.topic,
    )


def build_briefs(selected: list[str], candidates: list[StoryCandidate], cfg: dict, llm) -> list[AnalysisBrief]:
    """One brief per selected story, in selection order."""
    by_id = {item.story_id: item for item in candidates}
    unknown = [story_id for story_id in selected if story_id not in by_id]
    if unknown:
        raise ValueError(f"build_briefs: unknown story id(s) {unknown}")
    briefs: list[AnalysisBrief] = []
    for story_id in selected:
        candidate = by_id[story_id]
        answer = llm("brief", {
            "story_id": story_id,
            "headline": candidate.headline,
            "section": candidate.section,
            "text": candidate.source_text,
        })
        raw = answer.get("brief")
        if not isinstance(raw, dict):
            raise ValueError(f"{story_id}: the brief answer must contain a JSON object under 'brief'")
        briefs.append(build_brief(raw, candidate, cfg))
    return briefs


def all_claims(briefs: list[AnalysisBrief]) -> list[Claim]:
    return [claim for brief in briefs for claim in brief.claims]


def claim_report(briefs: list[AnalysisBrief]) -> dict:
    """Counts per kind across every brief, for claims.json."""
    counts = {kind: 0 for kind in ("FACT", "INFERENCE", "OPINION", "UNKNOWN")}
    for claim in all_claims(briefs):
        counts[claim.kind] += 1
    return {"claims": len(all_claims(briefs)), "counts": counts}
