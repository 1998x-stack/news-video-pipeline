"""Two-stage editorial selection.

Stage A scores every candidate (``ranking``). Stage B compares only the shortlist.
This module owns the decision itself, in Python:

* never more than ``editorial.top_k`` stories;
* never a duplicate event, however highly the model scored it;
* never a story below ``min_total_score`` or ``min_confidence``;
* never a story the comparison pass flagged as a repeat without progress or as
  having an unresolvable evidence gap;
* topic diversity is a soft constraint — it decides the *order* in which equally
  available candidates are taken, and is allowed to break when nothing else
  qualifies, with a note explaining that it broke;
* fewer than ``min_candidates`` qualifying stories is reported as
  ``insufficient`` — the list is never padded to reach ``top_k``;
* every candidate ends up exactly once in ``selected`` or ``rejected``, with a
  machine-readable reason.
"""
from __future__ import annotations

from .models import EditorialSelection, StoryCandidate, StoryRating

REASONS = (
    "duplicate",
    "weak_evidence",
    "repeat_without_progress",
    "below_min_score",
    "low_confidence",
    "topic_share",
    "below_top_k_cut",
)
ADJUSTMENT_LIMIT = 15


def shortlist(ratings: list[StoryRating], size: int) -> list[StoryRating]:
    ordered = sorted(ratings, key=lambda rating: -rating.effective_total)
    return ordered[:max(0, size)]


def _flag(raw: dict, key: str, story_id: str) -> bool:
    value = raw.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"compare: {story_id} field {key} must be a boolean, got {value!r}")
    return value


def compare(shortlisted: list[StoryRating], candidates: list[StoryCandidate], cfg: dict, llm) -> dict[str, dict]:
    """The second, comparative pass over the shortlist only."""
    if not shortlisted:
        return {}
    by_id = {item.story_id: item for item in candidates}
    known = set(by_id)
    payload = {
        "candidates": [
            {
                "story_id": rating.story_id,
                "headline": by_id[rating.story_id].headline if rating.story_id in by_id else "",
                "topic": rating.topic,
                "weighted_total": rating.weighted_total,
                "text": by_id[rating.story_id].source_text if rating.story_id in by_id else "",
            }
            for rating in shortlisted
        ]
    }
    answer = llm("compare", payload)
    entries = answer.get("comparisons")
    if not isinstance(entries, list):
        raise ValueError("compare: 'comparisons' must be a JSON array")
    expected = {rating.story_id for rating in shortlisted}
    totals = {rating.story_id: rating.weighted_total for rating in shortlisted}
    resolved: dict[str, dict] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("compare: every comparison must be a JSON object")
        story_id = str(raw.get("story_id", ""))
        if story_id not in expected:
            raise ValueError(f"compare: answer mentions unknown story_id {story_id!r}")
        if story_id in resolved:
            raise ValueError(f"compare: {story_id} was compared twice")
        adjustment = raw.get("adjustment", 0)
        if isinstance(adjustment, bool) or not isinstance(adjustment, int) or abs(adjustment) > ADJUSTMENT_LIMIT:
            raise ValueError(
                f"compare: {story_id} adjustment must be an integer within -{ADJUSTMENT_LIMIT}..{ADJUSTMENT_LIMIT}, got {adjustment!r}"
            )
        same_event = raw.get("same_event_as")
        if same_event is not None:
            same_event = str(same_event)
            if same_event not in known:
                raise ValueError(f"compare: {story_id} points at unknown story_id {same_event!r}")
            if same_event == story_id:
                raise ValueError(f"compare: {story_id} cannot be a duplicate of itself")
        resolved[story_id] = {
            "adjusted_total": max(0.0, min(100.0, totals[story_id] + adjustment)),
            "adjustment": adjustment,
            "comparison_note": str(raw.get("note") or ""),
            "same_event_as": same_event,
            "repeat_without_progress": _flag(raw, "repeat_without_progress", story_id),
            "evidence_gap": _flag(raw, "evidence_gap", story_id),
        }
    missing = sorted(expected - set(resolved))
    if missing:
        raise ValueError(f"compare: no comparison returned for {missing}")
    return resolved


def select(candidates: list[StoryCandidate], ratings: list[StoryRating], cfg: dict, llm) -> EditorialSelection:
    """Rank, compare the shortlist, then choose — with a full audit of the drops."""
    options = cfg["editorial"]
    top_k = int(options["top_k"])
    minimum = int(options["min_candidates"])
    selection_config = {
        "top_k": top_k,
        "min_candidates": minimum,
        "shortlist": int(options["shortlist"]),
        "min_total_score": float(options["min_total_score"]),
        "min_confidence": float(options["min_confidence"]),
        "max_topic_share": float(options["max_topic_share"]),
        "weights": dict(options["weights"]),
    }
    if not ratings:
        return EditorialSelection(
            top_k=top_k, selected=(), rejected=(), insufficient=True, selection_config=selection_config,
            notes=("insufficient: no candidate stories were extracted from this programme",),
        )
    notes: list[str] = []
    by_id = {item.story_id: item for item in candidates}
    shortlisted = shortlist(ratings, int(options["shortlist"]))
    comparison = compare(shortlisted, candidates, cfg, llm)

    def effective(rating: StoryRating) -> float:
        entry = comparison.get(rating.story_id)
        return rating.weighted_total if entry is None else entry["adjusted_total"]

    order = {rating.story_id: by_id[rating.story_id].block_index if rating.story_id in by_id else 0
             for rating in ratings}

    def rank_key(rating: StoryRating) -> tuple:
        return (-effective(rating), order[rating.story_id])

    # A duplicate pair is demoted on the weaker side only, so the stronger story survives.
    demoted: set[str] = set()
    ranking_by_id = {rating.story_id: rating for rating in ratings}
    for story_id, entry in comparison.items():
        other = entry["same_event_as"]
        if other is None or other not in ranking_by_id:
            continue
        if rank_key(ranking_by_id[story_id]) > rank_key(ranking_by_id[other]):
            demoted.add(story_id)

    eligible: list[StoryRating] = []
    rejected: list[dict] = []
    for rating in ratings:
        entry = comparison.get(rating.story_id, {})
        source = by_id.get(rating.story_id)
        # The candidate is the source of truth for clustering, so a rating that was
        # re-serialised without duplicate_of can never smuggle a duplicate through.
        flags = {
            "duplicate": bool(rating.duplicate_of is not None
                              or (source is not None and source.duplicate_of is not None)
                              or rating.story_id in demoted),
            "low_novelty": bool(entry.get("repeat_without_progress", False)),
            "weak_evidence": bool(entry.get("evidence_gap", False)),
        }
        total = effective(rating)
        reason = None
        if flags["duplicate"]:
            reason = "duplicate"
        elif flags["weak_evidence"]:
            reason = "weak_evidence"
        elif flags["low_novelty"]:
            reason = "repeat_without_progress"
        elif total < float(options["min_total_score"]):
            reason = "below_min_score"
        elif rating.confidence < float(options["min_confidence"]):
            reason = "low_confidence"
        record = {
            "story_id": rating.story_id,
            "headline": by_id[rating.story_id].headline if rating.story_id in by_id else "",
            "topic": rating.topic,
            "total": round(total, 4),
            "weighted_total": rating.weighted_total,
            "confidence": rating.confidence,
            **flags,
        }
        if reason:
            record["reason"] = reason
            rejected.append(record)
        else:
            eligible.append(rating)

    eligible.sort(key=rank_key)
    cap = max(1, round(float(options["max_topic_share"]) * top_k))
    selected: list[str] = []
    taken: dict[str, int] = {}
    deferred: list[StoryRating] = []
    for rating in eligible:
        if len(selected) >= top_k:
            break
        topic = rating.topic or "unlabelled"
        if taken.get(topic, 0) >= cap:
            deferred.append(rating)
            continue
        selected.append(rating.story_id)
        taken[topic] = taken.get(topic, 0) + 1
    if len(selected) < top_k and deferred:
        # Diversity is a soft constraint: fill the remaining slots rather than
        # ship a shorter video, and say plainly that the cap was exceeded.
        for rating in deferred:
            if len(selected) >= top_k:
                break
            selected.append(rating.story_id)
            taken[rating.topic or "unlabelled"] = taken.get(rating.topic or "unlabelled", 0) + 1
        notes.append(
            "topic_concentration: filled the remaining slots from one topic because no other "
            f"candidate cleared the threshold (cap={cap} for top_k={top_k})"
        )
    placed = set(selected)
    for rating in eligible:
        if rating.story_id in placed:
            continue
        rejected.append({
            "story_id": rating.story_id,
            "headline": by_id[rating.story_id].headline if rating.story_id in by_id else "",
            "topic": rating.topic,
            "total": round(effective(rating), 4),
            "weighted_total": rating.weighted_total,
            "confidence": rating.confidence,
            "duplicate": False,
            "low_novelty": False,
            "weak_evidence": False,
            "reason": "below_top_k_cut",
        })
    insufficient = len(selected) < minimum
    if insufficient:
        notes.append(
            f"insufficient: only {len(selected)} of the requested {minimum} minimum candidates cleared "
            f"min_total_score={options['min_total_score']} and min_confidence={options['min_confidence']}; "
            "the selection was not padded"
        )
    rejected.sort(key=lambda row: -row["total"])
    return EditorialSelection(
        top_k=top_k,
        selected=tuple(selected),
        rejected=tuple(rejected),
        insufficient=insufficient,
        selection_config=selection_config,
        notes=tuple(notes),
    )
