"""Optional model-assisted semantic risk triage, NOT factual certification.

The model checks each selected story's claims against its source text. Each
statement receives supported/contradicted/insufficient and exact-source evidence
(if any). This is a review queue, never a grant of publication approval.

No model inference happens unless editorial.semantic_review_mode is report/strict.
"""
from __future__ import annotations

from .models import AnalysisBrief, StoryCandidate

VERDICTS = {"supported", "contradicted", "insufficient"}
RISK_FLAGS = {"polarity", "entity", "number", "time", "causality", "scope", "unclear"}


def payload_for(brief: AnalysisBrief, candidate: StoryCandidate) -> dict:
    if brief.story_id != candidate.story_id:
        raise ValueError("Semantic review: story_id does not match source")
    return {
        "story_id": candidate.story_id,
        "source_text": candidate.source_text,
        "claims": [
            {"claim_id": claim.claim_id, "kind": claim.kind, "text": claim.text,
             "depends_on": list(claim.depends_on),
             "reasoning": claim.reasoning,
             "limitation": claim.limitation}
            for claim in brief.claims
        ],
        "analysis": {
            "angle": brief.angle,
            "mechanisms": list(brief.mechanisms),
            "second_order": list(brief.second_order),
            "counterpoints": list(brief.counterpoints),
        },
    }


def parse_verdicts(answer: dict, brief: AnalysisBrief, candidate: StoryCandidate) -> list[dict]:
    """Reject incomplete or hallucinated source citations instead of 'repairing'."""
    rows = answer.get("reviews")
    if not isinstance(rows, list):
        raise ValueError("semantic_review: reviews must be a JSON array")
    expected = {claim.claim_id: claim for claim in brief.claims}
    result: list[dict] = []
    seen = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("semantic_review: every review must be an object")
        cid = raw.get("claim_id")
        if cid not in expected or cid in seen:
            raise ValueError(f"semantic_review: unknown or duplicate claim_id {cid!r}")
        seen.add(cid)
        verdict = raw.get("verdict")
        if verdict not in VERDICTS:
            raise ValueError(f"semantic_review: {cid} verdict must be in {sorted(VERDICTS)}")
        excerpt = raw.get("evidence_quote") or ""
        if not isinstance(excerpt, str) or (excerpt and excerpt not in candidate.source_text):
            raise ValueError(f"semantic_review: {cid} evidence_quote not in its story source")
        if verdict == "supported" and not excerpt:
            raise ValueError(f"semantic_review: {cid} supported verdict requires a verbatim source quote")
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"semantic_review: {cid} must provide a specific reason")
        flags = raw.get("flags", [])
        if not isinstance(flags, list) or any(f not in RISK_FLAGS for f in flags):
            raise ValueError(f"semantic_review: {cid} flags must be from {sorted(RISK_FLAGS)}")
        result.append({
            "story_id": candidate.story_id, "claim_id": cid, "claim_kind": expected[cid].kind,
            "verdict": verdict, "evidence_quote": excerpt,
            "reason": reason.strip(), "flags": sorted(set(flags)),
            "review_source": "llm_self_review_unverified",
        })
    if seen != set(expected):
        raise ValueError(f"semantic_review: missing claim IDs {sorted(set(expected) - seen)}")
    return result


def semantic_review(briefs: list[AnalysisBrief], candidates: list[StoryCandidate],
                    cfg: dict, llm) -> dict:
    mode = cfg["editorial"].get("semantic_review_mode", "off")
    if mode not in {"off", "report", "strict"}:
        raise ValueError("semantic_review_mode must be off, report or strict")
    if mode == "off":
        return {"mode": "off", "reviews": [], "human_review_required": True}
    by_id = {c.story_id: c for c in candidates}
    rows: list[dict] = []
    for brief in briefs:
        if brief.story_id not in by_id:
            raise ValueError(f"Semantic review: unknown selected story {brief.story_id}")
        candidate = by_id[brief.story_id]
        result = llm("semantic_review", payload_for(brief, candidate),
                     check=lambda answer, b=brief, c=candidate: parse_verdicts(answer, b, c))
        rows.extend(result)
    uncertain = [r["claim_id"] for r in rows if r["verdict"] == "insufficient"]
    contradictions = [r["claim_id"] for r in rows if r["verdict"] == "contradicted"]
    outcome = {
        "schema_version": 1, "mode": mode, "reviews": rows,
        "contradiction_claim_ids": contradictions, "insufficient_claim_ids": uncertain,
        "human_review_required": True, "independently_fact_verified": False,
        "note": "A model inspecting the same transcript is NOT independent corroboration;"
                " reviewers must check sources, semantics, and publication rights.",
    }
    if mode == "strict":
        # Strict mode deliberately blocks unresolved factual/inferential claims.
        blocked = [
            r["claim_id"] for r in rows
            if r["claim_kind"] in {"FACT", "INFERENCE"} and r["verdict"] != "supported"
        ]
        if blocked:
            raise ValueError(f"Semantic review strict gate found unresolved claims {blocked}; manual review required")
    return outcome
