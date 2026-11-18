"""Fact checking for the editorial layer: keep FACT, INFERENCE, OPINION, UNKNOWN apart.

This is Layer 3 of the three grounding layers (see the design doc). It applies to
*selected* stories only. It deliberately does not reuse the whole-manuscript
retention gate: in curated mode, not covering a story is the product.

What Python checks, deterministically:

* every claim carries at least one span inside the story it belongs to;
* a ``FACT`` must quote the source verbatim, and every number it states must occur
  in the span it cites — an invented figure is a hard failure;
* a ``FACT`` must be lexically anchored in its cited span, so a paraphrase cannot
  be dressed up as a quotation;
* an ``INFERENCE`` must declare ``depends_on`` referring to existing ``FACT``
  claim ids, so the reasoning chain is auditable and cannot float free;
* ``UNKNOWN`` keeps its uncertainty but may not smuggle a number that the source
  never contained;
* any claim may only cite spans inside the story it belongs to.

What Python cannot check is stated plainly instead of being faked: this is a
lexical and numeric guard, not semantic entailment. A human still has to judge
whether a claim is true.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import CLAIM_KINDS, Claim, SourceSpan, StoryCandidate
from ..planner import normalize_text

NUMERIC = re.compile(r"\d+(?:[.,]\d+)*")


def _span_text(candidate: StoryCandidate, span: SourceSpan) -> str:
    """Text of a claim span, mapped through the candidate's own span layout.

    ``source_text`` is the concatenation of the candidate's spans, so the same
    walk works for a single-span story and for a story assembled from several
    source spans.
    """
    offset = 0
    for candidate_span in candidate.source_spans:
        length = candidate_span.end - candidate_span.start
        piece = candidate.source_text[offset:offset + length]
        if candidate_span.start <= span.start and span.end <= candidate_span.end:
            local = span.start - candidate_span.start
            return piece[local:local + (span.end - span.start)]
        offset += length
    raise ValueError(
        f"Claim span {span.start}..{span.end} is outside {candidate.story_id}"
    )


def locate(candidate: StoryCandidate, needle: str) -> SourceSpan:
    """Absolute span of a verbatim quote inside a candidate, or fail closed."""
    if not needle or not needle.strip():
        raise ValueError("A FACT claim must quote the source; the quote was empty")
    text = candidate.source_text
    index = text.find(needle)
    if index < 0:
        raise ValueError(
            "A FACT claim quote is not verbatim in the source; refusing to treat a "
            "paraphrase as a quotation"
        )
    offset = 0
    for span in candidate.source_spans:
        length = span.end - span.start
        if index < offset + length:
            local = index - offset
            return SourceSpan(span.start + local, span.start + local + len(needle))
        offset += length
    raise ValueError("Quote located outside the candidate's source spans")


def overlap_ratio(text: str, reference: str) -> float:
    left, right = normalize_text(text), normalize_text(reference)
    if not left:
        return 0.0
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(left)


def claim_from_llm(raw: dict, story_id: str, candidate: StoryCandidate, claim_id: str,
                   existing: dict[str, Claim] | None = None) -> Claim:
    """Build a validated Claim from one model answer entry."""
    if not isinstance(raw, dict):
        raise ValueError(f"{claim_id}: every claim must be a JSON object")
    kind = str(raw.get("kind", "")).strip().upper()
    if kind not in CLAIM_KINDS:
        raise ValueError(f"{claim_id}: unknown claim kind {kind!r}; expected one of {list(CLAIM_KINDS)}")
    text = str(raw.get("text") or "").strip()
    if not text:
        raise ValueError(f"{claim_id}: claim text is empty")
    spans: tuple[SourceSpan, ...] = ()
    if kind == "FACT":
        spans = (locate(candidate, str(raw.get("quote") or "").strip()),)
    else:
        quote = str(raw.get("quote") or "").strip()
        if quote:
            spans = (locate(candidate, quote),)
        else:
            for span in candidate.source_spans:
                spans = (SourceSpan(span.start, span.end),)
                break
    depends_on = raw.get("depends_on") or []
    if not isinstance(depends_on, list):
        raise ValueError(f"{claim_id}: depends_on must be a JSON array")
    lookup = dict(existing or {})
    for dependency in depends_on:
        name = str(dependency)
        if name not in lookup:
            raise ValueError(
                f"{claim_id}: depends_on refers to unknown claim {name!r}; an inference "
                "must depend on claims that exist in the same brief"
            )
        if lookup[name].kind != "FACT":
            raise ValueError(
                f"{claim_id}: an INFERENCE must depend on FACT claims; {name} is {lookup[name].kind}"
            )
    return Claim(
        claim_id=claim_id,
        story_id=story_id,
        kind=kind,
        text=text,
        source_spans=spans,
        depends_on=tuple(str(x) for x in depends_on),
        reasoning=str(raw.get("reasoning") or "").strip(),
        limitation=str(raw.get("limitation") or "").strip(),
    )


def validate_claims(claims: list[Claim], candidate: StoryCandidate, cfg: dict) -> dict:
    """Fail closed on any unsupported claim; return an audit summary.

    ``anchored_ratio`` is the share of FACT claims whose wording is lexically
    anchored in the span they cite (1.0 when there is no FACT claim). It is a
    quotation-integrity measure, not a truth measure.
    """
    # fact_anchor_min is retained as a legacy config field for compatibility;
    # FACT is now equality-gated rather than threshold-gated.
    counts = {kind: 0 for kind in CLAIM_KINDS}
    source_numbers = set(NUMERIC.findall(candidate.source_text))
    facts = 0
    anchored = 0
    exact_excerpts = 0
    for claim in claims:
        counts[claim.kind] += 1
        if claim.story_id != candidate.story_id:
            raise ValueError(f"{claim.claim_id}: belongs to {claim.story_id}, not {candidate.story_id}")
        if not claim.source_spans:
            raise ValueError(f"{claim.claim_id}: no cited source span; every claim must be traceable")
        cited = "".join(_span_text(candidate, span) for span in claim.source_spans)
        claim_numbers = set(NUMERIC.findall(claim.text))
        if claim.kind == "FACT":
            facts += 1
            invented = sorted(claim_numbers - set(NUMERIC.findall(cited)))
            if invented:
                raise ValueError(
                    f"{claim.claim_id}: number(s) {invented} are not present in its cited source span"
                )
            # A citation is not proof that a DIFFERENT assertion is true.
            # Even a 99% matching sentence can flip 增长 into 下降. The FACT
            # text must equal the exact, contiguous, source-backed quote
            # (ignoring spacing and punctuation only).
            if len(claim.source_spans) != 1:
                raise ValueError(
                    f"{claim.claim_id}: FACT must have one contiguous source anchor"
                )
            if normalize_text(claim.text) != normalize_text(cited):
                ratio = overlap_ratio(claim.text, cited)
                raise ValueError(
                    f"{claim.claim_id}: FACT must be an exact source quotation "
                    f"(anchor overlap {ratio:.2f}); place a paraphrase under "
                    "INFERENCE with explicit source dependencies instead"
                )
            exact_excerpts += 1
            anchored += 1
        else:
            invented = sorted(claim_numbers - source_numbers)
            if invented:
                raise ValueError(
                    f"{claim.claim_id}: {claim.kind} claim states number(s) {invented} "
                    "not present in the story source"
                )
        if claim.kind == "INFERENCE" and not claim.depends_on:
            raise ValueError(
                f"{claim.claim_id}: an INFERENCE must declare depends_on so the reasoning chain is auditable"
            )
    by_id = {claim.claim_id: claim for claim in claims}
    for claim in claims:
        for dependency in claim.depends_on:
            if dependency not in by_id:
                raise ValueError(f"{claim.claim_id}: depends_on refers to unknown claim {dependency!r}")
            if by_id[dependency].kind != "FACT":
                raise ValueError(
                    f"{claim.claim_id}: an INFERENCE must depend on FACT claims; "
                    f"{dependency} is {by_id[dependency].kind}"
                )
    return {
        "claims": len(claims),
        "counts": counts,
        "anchored_ratio": 1.0 if facts == 0 else round(anchored / facts, 4),
        "exact_excerpts": exact_excerpts,
        "facts": facts,
        "note": "Lexical and numeric guards only; semantic entailment still needs a human.",
    }


def assert_claims_supported(claims: list[Claim], candidate: StoryCandidate, cfg: dict) -> dict:
    """``validate_claims`` with the failure described in the raised message."""
    report = validate_claims(claims, candidate, cfg)
    report["story_id"] = candidate.story_id
    return report
