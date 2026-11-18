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
# A brief repeats its headline just after it, possibly behind a connective.
MIN_REPEAT_PREFIX = 10


@dataclass(frozen=True)
class Block:
    """One programme section: its heading plus the text that follows it."""

    heading: str
    text: str
    start: int
    end: int
    section: str = ""
    is_aggregate: bool = False
    split_status: str = "exact"


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
            split_status="uncertain" if text in aggregates else "exact",
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


def verify_verbatim(block_text: str, pieces: list[str]) -> list[tuple[int, int]]:
    """Locate each proposed item inside the block, or refuse the whole split.

    The only tolerated difference is surrounding whitespace. If a model
    paraphrases, drops, reorders or invents text, the split is rejected so the
    container is kept intact rather than silently losing a story.
    """
    spans: list[tuple[int, int]] = []
    cursor = 0
    for piece in pieces:
        if not isinstance(piece, str) or not piece.strip():
            raise ValueError("aggregate split contains an empty item; expected verbatim text")
        trimmed = piece.strip()
        index = block_text.find(trimmed, cursor)
        if index < 0 or block_text[cursor:index].strip():
            raise ValueError(
                "LLM aggregate split is not verbatim; refusing to lose source text or invent a story"
            )
        spans.append((index, index + len(trimmed)))
        cursor = index + len(trimmed)
    if block_text[cursor:].strip():
        raise ValueError(
            "LLM aggregate split is not verbatim; refusing to lose source text or invent a story"
        )
    return spans


def _block_body(block: Block) -> tuple[str, int]:
    """The block's text without its heading line, plus that body's absolute offset."""
    heading_len = len(block.text.split("\n", 1)[0])
    body = block.text[heading_len:]
    left = len(body) - len(body.lstrip())
    return body.strip(), block.start + heading_len + left


def derived_headline(text: str, limit: int = 40) -> str:
    """Recover a brief's own headline from a glued `headline + body` string.

    A brief repeats its headline at the start of its own body, sometimes after a
    short connective (近日，/今天/记者从…获悉，), so the longest prefix that occurs
    again later in the item is the headline. When nothing repeats, fall back to the
    first clause, which is honest about the uncertainty rather than inventing one.
    """
    head = text[:limit]
    for size in range(len(head), MIN_REPEAT_PREFIX - 1, -1):
        if text.find(text[:size], size) != -1:
            return text[:size]
    marker = re.search(r"(近日|今天|昨天|日前|\d+月\d+日|[，；])", text)
    if marker and 6 <= marker.start() <= limit:
        return text[:marker.start()]
    return head + ("…" if len(text) > limit else "")


def split_aggregate(block: Block, cfg: dict, llm, diagnostics: list | None = None) -> list[Block]:
    """Split one aggregate 联播快讯 block into its items, or keep it whole.

    The model proposes each item's text (and optionally its headline);
    ``verify_verbatim`` proves the texts rebuild the container byte-for-byte, and a
    proposed headline is accepted only when it also occurs verbatim in that item.
    Any failure keeps the container as one candidate marked ``uncertain`` so a human
    can split it, and never drops content.
    """
    if not block.is_aggregate:
        return [block]
    body_text, offset = _block_body(block)
    failure = "aggregate split returned fewer than two items"
    try:
        answer = llm("aggregate_split", {
            "heading": block.heading,
            "text": body_text,
            "max_items": int(cfg["editorial"].get("max_split_items", 12)),
        })
        items = answer.get("items") if isinstance(answer, dict) else None
        if not isinstance(items, list) or len(items) < 2:
            raise ValueError(failure)
        if len(items) > int(cfg["editorial"].get("max_split_items", 12)):
            raise ValueError("aggregate split returned more items than editorial.max_split_items")
        texts: list[str] = []
        proposed: list[str] = []
        for entry in items:
            if isinstance(entry, dict):
                texts.append(str(entry.get("text") or ""))
                proposed.append(str(entry.get("headline") or "").strip())
            else:
                texts.append(str(entry))
                proposed.append("")
        spans = verify_verbatim(body_text, texts)
    except Exception as error:  # noqa: BLE001 - any failure keeps the source intact
        if diagnostics is not None:
            diagnostics.append({
                "heading": block.heading,
                "start": block.start,
                "error": f"{type(error).__name__}: {error}",
            })
        return [replace(block, split_status="uncertain")]
    pieces: list[Block] = []
    for index, (start, end) in enumerate(spans):
        text = body_text[start:end]
        headline = proposed[index]
        # A headline is only trusted when it is itself verbatim in the item.
        if not headline or headline not in text:
            headline = derived_headline(text)
        pieces.append(Block(
            heading=headline,
            text=text,
            start=offset + start,
            end=offset + end,
            section=block.heading,
            is_aggregate=False,
            split_status="llm_verified",
        ))
    if diagnostics is not None:
        diagnostics.append({"heading": block.heading, "start": block.start, "items": len(pieces)})
    return pieces


def extract_candidates(body: str, source_title: str, cfg: dict, source_id: str = "",
                       llm=None) -> tuple[list[StoryCandidate], dict]:
    """Return every independent story in the programme plus an extraction report."""
    if not body.strip():
        raise ValueError("Programme text is empty; nothing to extract")
    blocks, skipped, stats = segment(body, cfg)
    if not blocks:
        raise ValueError("Programme contains no news blocks; refusing to fabricate stories")
    source = source_id or f"input_{normalize_text(source_title)[:16] or 'programme'}"
    diagnostics: list[dict] = []
    expanded: list[Block] = []
    for block in blocks:
        if not (llm and block.is_aggregate):
            expanded.append(block)
            continue
        parts = split_aggregate(block, cfg, llm, diagnostics)
        if len(parts) > 1:
            # The section label itself is not news content; record it so that the
            # "no character is unaccounted for" invariant still holds.
            _, body_offset = _block_body(block)
            skipped.append({"start": block.start, "end": body_offset,
                            "heading": block.heading, "reason": "aggregate_heading"})
        expanded.extend(parts)
    candidates = [
        StoryCandidate(
            story_id=f"story_{index:03d}",
            headline=block.heading,
            source_id=source,
            source_spans=(SourceSpan(block.start, block.end),),
            source_text=block.text,
            block_index=index,
            section=block.section,
            split_status=block.split_status,
        )
        for index, block in enumerate(expanded, 1)
    ]
    candidates, clusters = dedupe(candidates)
    report = {
        "schema_version": 1,
        "source_id": source,
        "blocks": len(blocks),
        "candidates": len(candidates),
        "aggregate_blocks": sum(1 for b in blocks if b.is_aggregate),
        "split_briefs": sum(1 for b in expanded if not b.is_aggregate and b.section),
        "uncertain_blocks": sum(1 for c in candidates if c.split_status == "uncertain"),
        "duplicate_clusters": {k: v for k, v in clusters.items() if len(v) > 1},
        "skipped_blocks": skipped,
        "aggregate_failures": [d for d in diagnostics if "error" in d],
        "candidate_ids": [c.story_id for c in candidates],
        **stats,
    }
    return candidates, report
