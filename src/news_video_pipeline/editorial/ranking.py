"""Explainable ranking: the model scores, Python does the arithmetic.

The model never decides the final order and never decides who wins. It returns
0-10 integers per dimension plus a reason for each; this module validates every
value, computes the weighted total from the configured rubric and sorts the
result deterministically. A malformed score fails the run instead of being
silently coerced, so a lazy or truncated answer can never look like a judgement.
"""
from __future__ import annotations

import re

from .models import DIMENSIONS, StoryCandidate, StoryRating

NUMERIC = re.compile(r"\d+(?:[.,]\d+)*")
ORG_MARKERS = re.compile(r"[《【]([^》】]{2,40})[》】]")
QUOTES = re.compile(r"[“”\"][^“”\"]{4,}[“”\"]")
DATE_MARKERS = re.compile(r"(\d{4}年|\d{1,2}月\d{1,2}日|今天|昨天|近日|日前|去年|今年)")
THIN_CONTENT_CHARS = 80


def validate_scores(scores: dict, stage: str) -> dict[str, int]:
    """Return the scores unchanged, or fail closed on anything malformed."""
    if not isinstance(scores, dict):
        raise ValueError(f"{stage}: scores must be a JSON object")
    missing = [d for d in DIMENSIONS if d not in scores]
    if missing:
        raise ValueError(f"{stage}: missing dimension(s) {missing}; every dimension must be judged")
    unknown = [key for key in scores if key not in DIMENSIONS]
    if unknown:
        raise ValueError(f"{stage}: unknown dimension(s) {unknown}")
    for dimension, value in scores.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{stage}: {dimension} must be an integer score, got {value!r}")
        if not 0 <= value <= 10:
            raise ValueError(f"{stage}: {dimension} must be within 0..10, got {value}")
    return dict(scores)


def validate_confidence(value, stage: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{stage}: confidence must be a number, got {value!r}")
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{stage}: confidence must be within 0..1, got {value}")
    return float(value)


def weighted_total(scores: dict[str, int], weights: dict[str, int]) -> float:
    """Rubric arithmetic, in Python, so it is reproducible and testable."""
    validate_scores(scores, "weighted_total")
    if set(weights) != set(DIMENSIONS):
        raise ValueError("weights must define exactly the rubric dimensions")
    return round(sum(scores[d] / 10 * weights[d] for d in DIMENSIONS), 4)


def features(candidate: StoryCandidate) -> dict:
    """Deterministic lexical features: cheap evidence, never the judgement."""
    text = candidate.source_text
    flags: list[str] = []
    if len(text) < THIN_CONTENT_CHARS and not NUMERIC.search(text):
        flags.append("thin_content")
    if candidate.duplicate_of:
        flags.append("duplicate")
    if candidate.split_status == "uncertain":
        flags.append("uncertain_split")
    return {
        "char_len": len(text),
        "sentences": len([x for x in re.split(r"[。！？；]", text) if x.strip()]),
        "numeric_tokens": len(NUMERIC.findall(text)),
        "org_markers": len(ORG_MARKERS.findall(text)),
        "quotes": len(QUOTES.findall(text)),
        "date_markers": len(DATE_MARKERS.findall(text)),
        "flags": tuple(flags),
    }


def _batch(items: list[StoryCandidate], size: int) -> list[list[StoryCandidate]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _payload(items: list[StoryCandidate]) -> dict:
    return {
        "stories": [
            {
                "story_id": item.story_id,
                "headline": item.headline,
                "section": item.section,
                "text": item.source_text,
            }
            for item in items
        ]
    }


def rate_candidates(candidates: list[StoryCandidate], cfg: dict, llm) -> list[StoryRating]:
    """One modelling pass over every candidate, then Python-owned arithmetic."""
    options = cfg["editorial"]
    weights = options["weights"]
    ordered = sorted(candidates, key=lambda item: item.block_index)
    size = int(options["batch_size"])
    ratings: list[StoryRating] = []
    for group in _batch(ordered, size):
        answer = llm("rank", _payload(group))
        entries = answer.get("ratings")
        if not isinstance(entries, list):
            raise ValueError("rank: 'ratings' must be a JSON array")
        seen: set[str] = set()
        expected = {item.story_id for item in group}
        for raw in entries:
            if not isinstance(raw, dict):
                raise ValueError("rank: every rating must be a JSON object")
            story_id = str(raw.get("story_id", ""))
            if story_id not in expected:
                raise ValueError(f"rank: answer mentions unknown story_id {story_id!r}")
            if story_id in seen:
                raise ValueError(f"rank: {story_id} was scored twice in one answer")
            seen.add(story_id)
            scores = validate_scores(raw.get("scores"), "rank")
            reasons = raw.get("reasons")
            if not isinstance(reasons, dict) or set(reasons) != set(DIMENSIONS):
                raise ValueError(f"rank: {story_id} must give a reason for every dimension")
            flags = list(features(next(item for item in group if item.story_id == story_id))["flags"])
            new_information = raw.get("new_information") or []
            if isinstance(new_information, list) and not new_information:
                flags.append("no_new_information")
            source = next(item for item in group if item.story_id == story_id)
            ratings.append(StoryRating(
                story_id=story_id,
                scores=scores,
                reasons={d: str(reasons[d]) for d in DIMENSIONS},
                weighted_total=weighted_total(scores, weights),
                topic=str(raw.get("topic") or "").strip(),
                confidence=validate_confidence(raw.get("confidence", 0.0), "rank"),
                flags=tuple(dict.fromkeys(flags)),
                duplicate_of=source.duplicate_of,
            ))
        missing = sorted(expected - seen)
        if missing:
            raise ValueError(f"rank: no rating returned for {missing}")
    order = {item.story_id: item.block_index for item in candidates}
    return sorted(ratings, key=lambda rating: (-rating.weighted_total, order.get(rating.story_id, 0)))


def ranked_table(ratings: list[StoryRating], candidates: list[StoryCandidate] | None = None) -> list[dict]:
    """The audit table written to ``editorial_ranking.json``."""
    headlines = {item.story_id: item.headline for item in (candidates or [])}
    sections = {item.story_id: item.section for item in (candidates or [])}
    table = []
    for position, rating in enumerate(ratings, 1):
        table.append({
            "rank": position,
            "story_id": rating.story_id,
            "headline": headlines.get(rating.story_id, ""),
            "section": sections.get(rating.story_id, ""),
            "topic": rating.topic,
            "weighted_total": rating.weighted_total,
            "adjusted_total": rating.adjusted_total,
            "effective_total": rating.effective_total,
            "confidence": rating.confidence,
            "flags": list(rating.flags),
            "duplicate_of": rating.duplicate_of,
            "scores": dict(rating.scores),
            "reasons": dict(rating.reasons),
            "comparison_note": rating.comparison_note,
        })
    return table
