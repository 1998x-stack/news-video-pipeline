"""Data contracts for the editorial layer.

Every structure here is plain data with an explicit ``to_dict``/``from_dict`` so it
can be written into the run directory, hashed into the manifest and re-read by an
audit tool without importing the pipeline. Bump ``SCHEMA_VERSION`` and update the
tests whenever a field changes meaning.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

SCHEMA_VERSION = 1

# Rubric dimensions (weights are configuration, never constants in code).
DIMENSIONS = (
    "public_impact",
    "structural_importance",
    "information_novelty",
    "analytical_depth",
    "timeliness",
    "evidence_quality",
    "audience_utility",
)

# Editorial critic rubric, scored 0..10 per selected story.
CRITIQUE_DIMENSIONS = (
    "factual_grounding",
    "analytical_depth",
    "original_insight",
    "clarity",
    "audience_utility",
    "uncertainty_handling",
    "narrative_coherence",
)

CLAIM_KINDS = ("FACT", "INFERENCE", "OPINION", "UNKNOWN")
SPLIT_STATUSES = ("exact", "llm_verified", "uncertain")


def _tuple_of(value, coerce=None) -> tuple:
    """Normalise a sequence field to a tuple, leaving existing instances alone."""
    if value is None:
        return ()
    if isinstance(value, str):
        raise ValueError("expected a sequence, not a string")
    items = tuple(value)
    if coerce is None:
        return items
    return tuple(x if isinstance(x, coerce) else coerce(x) for x in items)


@dataclass(frozen=True)
class SourceSpan:
    """Character offsets into the verbatim programme text (Layer 1 source)."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if not isinstance(self.start, int) or not isinstance(self.end, int):
            raise ValueError("SourceSpan offsets must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValueError(f"Invalid SourceSpan: {self.start}..{self.end}")

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, raw: dict) -> "SourceSpan":
        return cls(int(raw["start"]), int(raw["end"]))


@dataclass(frozen=True)
class StoryCandidate:
    """One independent news story extracted from the programme."""

    story_id: str
    headline: str
    source_id: str
    source_spans: tuple[SourceSpan, ...]
    source_text: str
    block_index: int
    section: str = ""
    entities: tuple[str, ...] = ()
    topic: str = ""
    event_time: str | None = None
    core_facts: tuple[str, ...] = ()
    new_information: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    source_status: str = "unverified"
    split_status: str = "exact"
    cluster_id: str = ""
    duplicate_of: str | None = None

    def __post_init__(self) -> None:
        if self.split_status not in SPLIT_STATUSES:
            raise ValueError(f"Unknown split_status: {self.split_status!r}")
        if not self.source_spans:
            raise ValueError(f"{self.story_id} has no source span; every story must be traceable")
        object.__setattr__(self, "source_spans", _tuple_of(self.source_spans, SourceSpan))
        object.__setattr__(self, "entities", _tuple_of(self.entities, str))
        object.__setattr__(self, "core_facts", _tuple_of(self.core_facts, str))
        object.__setattr__(self, "new_information", _tuple_of(self.new_information, str))
        object.__setattr__(self, "uncertainties", _tuple_of(self.uncertainties, str))

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of is not None

    def to_dict(self) -> dict:
        out = asdict(self)
        out["source_spans"] = [span.to_dict() for span in self.source_spans]
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "StoryCandidate":
        payload = dict(raw)
        payload["source_spans"] = tuple(SourceSpan.from_dict(x) for x in payload.get("source_spans", ()))
        for key in ("entities", "core_facts", "new_information", "uncertainties"):
            payload[key] = _tuple_of(payload.get(key))
        return cls(**payload)


@dataclass(frozen=True)
class ScoreSet:
    """Per-dimension scores and reasons for one story.

    Every dimension must be present: a silent default would hide a model that
    simply forgot to judge something.
    """

    scores: dict[str, int]
    reasons: dict[str, str]

    def __post_init__(self) -> None:
        for label, values in (("scores", self.scores), ("reasons", self.reasons)):
            missing = [d for d in DIMENSIONS if d not in values]
            if missing:
                raise ValueError(f"{label} missing dimensions: {missing}")
            unknown = [k for k in values if k not in DIMENSIONS]
            if unknown:
                raise ValueError(f"{label} has unknown dimensions: {unknown}")

    def to_dict(self) -> dict:
        return {"scores": dict(self.scores), "reasons": dict(self.reasons)}

    @classmethod
    def from_dict(cls, raw: dict) -> "ScoreSet":
        return cls(scores=dict(raw["scores"]), reasons=dict(raw["reasons"]))


@dataclass(frozen=True)
class StoryRating:
    """Weighted, explainable ranking record for one candidate."""

    story_id: str
    scores: dict[str, int]
    reasons: dict[str, str]
    weighted_total: float
    topic: str = ""
    confidence: float = 0.0
    flags: tuple[str, ...] = ()
    duplicate_of: str | None = None
    adjusted_total: float | None = None
    comparison_note: str = ""

    @property
    def effective_total(self) -> float:
        return self.weighted_total if self.adjusted_total is None else self.adjusted_total

    def to_dict(self) -> dict:
        out = asdict(self)
        out["flags"] = list(self.flags)
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "StoryRating":
        payload = dict(raw)
        payload["flags"] = _tuple_of(payload.get("flags"))
        return cls(**payload)


@dataclass(frozen=True)
class Claim:
    """A single statement with its epistemic status and source anchoring."""

    claim_id: str
    story_id: str
    kind: str
    text: str
    source_spans: tuple[SourceSpan, ...] = ()
    depends_on: tuple[str, ...] = ()
    reasoning: str = ""
    limitation: str = ""

    def __post_init__(self) -> None:
        if self.kind not in CLAIM_KINDS:
            raise ValueError(f"Unknown claim kind: {self.kind!r}")
        if not self.text.strip():
            raise ValueError(f"{self.claim_id} has empty text")
        object.__setattr__(self, "source_spans", _tuple_of(self.source_spans, SourceSpan))
        object.__setattr__(self, "depends_on", _tuple_of(self.depends_on, str))

    def to_dict(self) -> dict:
        out = asdict(self)
        out["source_spans"] = [span.to_dict() for span in self.source_spans]
        out["depends_on"] = list(self.depends_on)
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "Claim":
        payload = dict(raw)
        payload["source_spans"] = tuple(SourceSpan.from_dict(x) for x in payload.get("source_spans", ()))
        payload["depends_on"] = _tuple_of(payload.get("depends_on"))
        return cls(**payload)


@dataclass(frozen=True)
class AnalysisBrief:
    """Independent analysis of one selected story."""

    story_id: str
    headline: str
    angle: str
    mechanisms: tuple[str, ...] = ()
    second_order: tuple[str, ...] = ()
    counterpoints: tuple[str, ...] = ()
    watch_indicators: tuple[str, ...] = ()
    claims: tuple[Claim, ...] = ()
    uncertainty: tuple[str, ...] = ()
    topic: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "mechanisms", _tuple_of(self.mechanisms, str))
        object.__setattr__(self, "second_order", _tuple_of(self.second_order, str))
        object.__setattr__(self, "counterpoints", _tuple_of(self.counterpoints, str))
        object.__setattr__(self, "watch_indicators", _tuple_of(self.watch_indicators, str))
        object.__setattr__(self, "uncertainty", _tuple_of(self.uncertainty, str))
        object.__setattr__(self, "claims", _tuple_of(self.claims, Claim))

    def to_dict(self) -> dict:
        out = asdict(self)
        out["claims"] = [claim.to_dict() for claim in self.claims]
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "AnalysisBrief":
        payload = dict(raw)
        payload["claims"] = tuple(Claim.from_dict(x) for x in payload.get("claims", ()))
        return cls(**payload)


@dataclass(frozen=True)
class EditorialSection:
    """One spoken section of the script, tied to the story it explains."""

    story_id: str
    heading: str
    narration: str
    kind: str = "supporting"

    def __post_init__(self) -> None:
        if self.kind not in {"opening", "top", "supporting", "closing"}:
            raise ValueError(f"Unknown section kind: {self.kind!r}")
        if not self.narration.strip():
            raise ValueError(f"Empty narration for {self.kind} section {self.story_id}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "EditorialSection":
        return cls(**raw)


@dataclass(frozen=True)
class EditorialScript:
    """The reviewed narration script that scenes are derived from."""

    title: str
    opening_hook: str
    sections: tuple[EditorialSection, ...]
    closing_synthesis: str
    body: str
    story_ids: tuple[str, ...] = ()
    critique: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", _tuple_of(self.sections, EditorialSection))
        object.__setattr__(self, "story_ids", _tuple_of(self.story_ids, str))

    def to_dict(self) -> dict:
        out = asdict(self)
        out["sections"] = [section.to_dict() for section in self.sections]
        out["story_ids"] = list(self.story_ids)
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "EditorialScript":
        payload = dict(raw)
        payload["sections"] = tuple(EditorialSection.from_dict(x) for x in payload.get("sections", ()))
        payload["story_ids"] = _tuple_of(payload.get("story_ids"))
        return cls(**payload)

    def markdown(self) -> str:
        lines = [f"# {self.title}", "", self.opening_hook, ""]
        for section in self.sections:
            lines += [f"## {section.heading}", "", section.narration, ""]
        lines += ["## 结语", "", self.closing_synthesis, ""]
        return "\n".join(lines)


@dataclass(frozen=True)
class EditorialSelection:
    """Final pick plus a complete audit of everything that was dropped."""

    top_k: int
    selected: tuple[str, ...]
    rejected: tuple[dict, ...] = ()
    insufficient: bool = False
    selection_config: dict = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.selected) > self.top_k:
            raise ValueError(f"selected {len(self.selected)} stories but top_k={self.top_k}")
        object.__setattr__(self, "selected", _tuple_of(self.selected, str))
        object.__setattr__(self, "rejected", _tuple_of(self.rejected, dict))
        object.__setattr__(self, "notes", _tuple_of(self.notes, str))

    def to_dict(self) -> dict:
        return {
            "top_k": self.top_k,
            "selected": list(self.selected),
            "rejected": [dict(x) for x in self.rejected],
            "insufficient": self.insufficient,
            "selection_config": dict(self.selection_config),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "EditorialSelection":
        return cls(
            top_k=int(raw["top_k"]),
            selected=_tuple_of(raw.get("selected")),
            rejected=_tuple_of(raw.get("rejected")),
            insufficient=bool(raw.get("insufficient", False)),
            selection_config=dict(raw.get("selection_config") or {}),
            notes=_tuple_of(raw.get("notes")),
        )


def with_split_status(candidate: StoryCandidate, status: str) -> StoryCandidate:
    """Return a copy carrying a different split verdict (never mutates in place)."""
    return replace(candidate, split_status=status)
