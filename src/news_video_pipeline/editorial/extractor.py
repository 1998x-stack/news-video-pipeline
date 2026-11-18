"""Deterministic story extraction: programme text → traceable StoryCandidates.

This module never calls a model. Story boundaries, character offsets and
duplicate clusters are decided here, so every later stage can be audited against
the verbatim programme text and the offline test suite can prove extraction
quality without network access.

Known hard case in real 新闻联播 pages: a ``国内联播快讯`` / ``国际联播快讯``
section glues several independent briefs into one paragraph, each brief's
headline repeated inside its own body. Those blocks are flagged as aggregates and
handed to ``split_aggregate`` (an LLM proposes verbatim spans, Python verifies
they reconstruct the block exactly). Until then the block stays whole and is
marked ``uncertain`` — never dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from .models import SourceSpan, StoryCandidate
from ..planner import normalize_text

SEPARATOR = re.compile(r"\n[ \t]*\n")
LINE = re.compile(r"[^\n]+")
PROGRAMME_NAMES = {"新闻联播", "新闻直播间", "焦点访谈", "朝闻天下"}
TERMINAL = ("。", "！", "？", "；", ".", "!", "?", ";")
MARKDOWN_FURNITURE = ("#", "---", "<!--", ">", "|")
# A commentary restates another story by construction and carries no new facts.
COMMENTARY_PREFIXES = ("央视快评", "本台评论", "本台短评", "国际锐评", "短评", "记者手记", "快评")
HEADING_MAX = 100
CLUSTER_SIMILARITY = 0.72
SUBSTRING_MIN = 10
COMMON_PHRASE_MIN = 12


@dataclass(frozen=True)
class Block:
    """One programme section: its heading plus the text that follows it."""

    heading: str
    text: str
    start: int
    end: int
    section: str = ""
    is_aggregate: bool = False


def _paragraph_spans(body: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in LINE.finditer(body) if m.group().strip()]


def _trim(body: str, start: int, end: int) -> tuple[int, int]:
    fragment = body[start:end]
    return start + (len(fragment) - len(fragment.lstrip())), end - (len(fragment) - len(fragment.rstrip()))


def looks_like_heading(text: str) -> bool:
    """A heading is a short complete line that does not end a sentence.

    ``read_input`` joins every source line with a blank line, so headings and
    bodies arrive as sibling lines; a body always ends with 。！？ and is long.
    """
    line = text.strip()
    if not line or "\n" in line:
        return False
    if line.endswith(TERMINAL):
        return False
    if line.startswith(MARKDOWN_FURNITURE):
        return False
    return len(line) <= HEADING_MAX


def _strip_furniture(headline: str) -> str:
    return re.sub(r"^【[^】]*】", "", headline.strip())


def segment(body: str, cfg: dict) -> tuple[list[Block], list[dict], dict]:
    """Segment the programme into blocks, recording what was skipped and why.

    A heading claims every following line until the next heading, so a
    multi-paragraph story stays one candidate instead of being torn in two.
    Nothing is dropped silently: any line that ends up in no block appears in
    ``skipped`` with a reason.
    """
    aggregates = {h.strip() for h in cfg["editorial"]["aggregate_headings"]}
    lines = [(_trim(body, s, e), body[s:e].strip()) for s, e in _paragraph_spans(body)]
    blocks: list[Block] = []
    skipped: list[dict] = []
    continuations = 0
    index = 0
    while index < len(lines):
        (start, end), text = lines[index]
        if text in PROGRAMME_NAMES:
            skipped.append({"start": start, "end": end, "heading": text, "reason": "programme_name_or_empty"})
            index += 1
            continue
        if not looks_like_heading(text):
            reason = "markdown_furniture" if text.startswith(MARKDOWN_FURNITURE) else "orphan_text"
            skipped.append({"start": start, "end": end, "heading": text[:40], "reason": reason})
            index += 1
            continue
        cursor, block_end, body_lines = index + 1, end, 0
        while cursor < len(lines) and not looks_like_heading(lines[cursor][1]) and lines[cursor][1] not in PROGRAMME_NAMES:
            block_end = lines[cursor][0][1]
            body_lines += 1
            cursor += 1
        if body_lines == 0:
            skipped.append({"start": start, "end": end, "heading": text, "reason": "heading_without_body"})
            index += 1
            continue
        continuations += body_lines - 1
        blocks.append(Block(
            heading=text,
            text=body[start:block_end],
            start=start,
            end=block_end,
            section=text if text in aggregates else "",
            is_aggregate=text in aggregates,
        ))
        index = cursor
    stats = {"continuation_blocks": continuations, "skipped_lines": len(skipped)}
    return blocks, skipped, stats


def split_blocks(body: str, cfg: dict) -> list[Block]:
    """Public helper: the blocks of a programme, in broadcast order."""
    return segment(body, cfg)[0]


def cluster_key(headline: str) -> str:
    """Normalised headline used for equality-based clustering."""
    text = _strip_furniture(headline)
    for prefix in COMMENTARY_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return normalize_text(text.lstrip("：: -—"))


def _longest_common_substring(a: str, b: str) -> int:
    if not a or not b:
        return 0
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    return max((block.size for block in matcher.get_matching_blocks()), default=0)


def _is_commentary(headline: str) -> bool:
    return _strip_furniture(headline).startswith(COMMENTARY_PREFIXES)


def similar_headlines(a: str, b: str) -> bool:
    """True when two headlines describe the same event."""
    left, right = cluster_key(a), cluster_key(b)
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) >= SUBSTRING_MIN and len(right) >= SUBSTRING_MIN and (left in right or right in left):
        return True
    if SequenceMatcher(None, left, right, autojunk=False).ratio() >= CLUSTER_SIMILARITY:
        return True
    # A commentary glued to its parent story shares one distinctive phrase.
    return _longest_common_substring(left, right) >= COMMON_PHRASE_MIN and (_is_commentary(a) or _is_commentary(b))


def _is_container(candidate: StoryCandidate) -> bool:
    """An aggregate section that has not been split into its briefs yet."""
    return bool(candidate.section) and candidate.headline == candidate.section


def dedupe(candidates: list[StoryCandidate]) -> tuple[list[StoryCandidate], dict[str, list[str]]]:
    """Group equal/near-equal stories; the earliest occurrence is canonical.

    A duplicate keeps its own id, spans and text for audit, and points at the
    canonical story through ``duplicate_of`` so selection can never take both.
    Two unsplit aggregate containers are never merged: ``国内联播快讯`` and
    ``国际联播快讯`` share the phrase 联播快讯 but hold different stories.
    """
    resolved: list[StoryCandidate] = []
    canonical: list[StoryCandidate] = []
    clusters: dict[str, list[str]] = {}
    for candidate in candidates:
        match = next((c for c in canonical
                      if not (_is_container(c) and _is_container(candidate))
                      and similar_headlines(c.headline, candidate.headline)), None)
        if match is None:
            merged = replace(candidate, cluster_id=f"cluster_{len(canonical) + 1:03d}")
            canonical.append(merged)
            clusters[merged.cluster_id] = [merged.story_id]
        else:
            merged = replace(candidate, cluster_id=match.cluster_id, duplicate_of=match.story_id)
            clusters[match.cluster_id].append(merged.story_id)
        resolved.append(merged)
    return resolved, clusters


def extract_candidates(body: str, source_title: str, cfg: dict, source_id: str = "") -> tuple[list[StoryCandidate], dict]:
    """Return every independent story in the programme plus an extraction report."""
    if not body.strip():
        raise ValueError("Programme text is empty; nothing to extract")
    blocks, skipped, stats = segment(body, cfg)
    if not blocks:
        raise ValueError("Programme contains no news blocks; refusing to fabricate stories")
    source = source_id or f"input_{normalize_text(source_title)[:16] or 'programme'}"
    candidates = [
        StoryCandidate(
            story_id=f"story_{index:03d}",
            headline=block.heading,
            source_id=source,
            source_spans=(SourceSpan(block.start, block.end),),
            source_text=block.text,
            block_index=index,
            section=block.section,
            split_status="uncertain" if block.is_aggregate else "exact",
        )
        for index, block in enumerate(blocks, 1)
    ]
    candidates, clusters = dedupe(candidates)
    report = {
        "schema_version": 1,
        "source_id": source,
        "blocks": len(blocks),
        "candidates": len(candidates),
        "aggregate_blocks": sum(1 for b in blocks if b.is_aggregate),
        "uncertain_blocks": sum(1 for c in candidates if c.split_status == "uncertain"),
        "duplicate_clusters": {k: v for k, v in clusters.items() if len(v) > 1},
        "skipped_blocks": skipped,
        "candidate_ids": [c.story_id for c in candidates],
        **stats,
    }
    return candidates, report
