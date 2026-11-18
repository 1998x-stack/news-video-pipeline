#!/usr/bin/env python3
"""Read-only audit of analysis_briefs.json: claim kinds, source spans and dependencies.

The gate is structural only. It proves that FACT / INFERENCE / OPINION / UNKNOWN
are kept apart, that every FACT points at a character range of the source and
that every inference names the claim it rests on. It never proves a claim is
true — that stays a human judgement.
"""
import argparse
import json
import sys
from pathlib import Path

KINDS = ("FACT", "INFERENCE", "OPINION", "UNKNOWN")


def _require_text(value, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)
    return value


def _check_spans(story_id: str, claim_id: str, spans) -> int:
    """A FACT must carry at least one valid character range into the source."""
    if not isinstance(spans, list) or not spans:
        raise ValueError(
            f"{story_id}/{claim_id}: FACT must declare a non-empty source_spans "
            "(逐字来自原文的字符区间)；转述或常识不算证据"
        )
    for span in spans:
        if not isinstance(span, dict):
            raise ValueError(f"{story_id}/{claim_id}: every source span must be an object with start/end")
        start, end = span.get("start"), span.get("end")
        for label, offset in (("start", start), ("end", end)):
            if isinstance(offset, bool) or not isinstance(offset, int):
                raise ValueError(f"{story_id}/{claim_id}: source span {label} must be an integer")
        if start < 0 or end <= start:
            raise ValueError(f"{story_id}/{claim_id}: invalid source span {start}..{end}")
    return len(spans)


def _check_claim(story_id: str, claim, position: int, seen_ids: set) -> str:
    """Validate one claim and return its id."""
    if not isinstance(claim, dict):
        raise ValueError(f"{story_id}: claims[{position}] must be a JSON object")
    claim_id = claim.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id.strip():
        raise ValueError(f"{story_id}: claims[{position}] has no claim_id")
    if claim_id in seen_ids:
        raise ValueError(f"{story_id}: duplicate claim_id {claim_id}; ids must be unique")
    seen_ids.add(claim_id)
    kind = claim.get("kind")
    if kind not in KINDS:
        raise ValueError(f"{story_id}/{claim_id}: unknown claim kind {kind!r}; expected one of {list(KINDS)}")
    _require_text(claim.get("text"), f"{story_id}/{claim_id}: claim text must not be empty")
    if kind == "FACT":
        _check_spans(story_id, claim_id, claim.get("source_spans"))
    elif claim.get("source_spans"):
        _check_spans(story_id, claim_id, claim.get("source_spans"))
    if kind == "INFERENCE":
        depends_on = claim.get("depends_on")
        if not isinstance(depends_on, list) or not depends_on or any(
                not isinstance(x, str) or not x.strip() for x in depends_on):
            raise ValueError(
                f"{story_id}/{claim_id}: INFERENCE must declare a non-empty depends_on of claim ids"
            )
        if claim_id in depends_on:
            raise ValueError(f"{story_id}/{claim_id}: INFERENCE cannot depend on itself")
    return claim_id


def _check_dependencies(story_id: str, claims: list[dict]) -> None:
    """Every inference must rest on a FACT that exists in the same brief."""
    kinds = {claim["claim_id"]: claim["kind"] for claim in claims}
    for claim in claims:
        if claim["kind"] != "INFERENCE":
            continue
        for dependency in claim["depends_on"]:
            if dependency not in kinds:
                raise ValueError(
                    f"{story_id}/{claim['claim_id']}: depends_on points at unknown claim id {dependency!r}; "
                    "推理必须引用本 brief 内已有的 claim"
                )
            if kinds[dependency] != "FACT":
                raise ValueError(
                    f"{story_id}/{claim['claim_id']}: an INFERENCE must depend on FACT claims; "
                    f"{dependency} is {kinds[dependency]}"
                )


def load(path) -> dict:
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"analysis file not found: {target}") from error
    except IsADirectoryError as error:
        raise ValueError(f"analysis path is a directory, expected a JSON file: {target}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"analysis file is not valid JSON ({error.msg} at position {error.pos})") from error
    if not isinstance(data, dict):
        raise ValueError("analysis_briefs.json must be a JSON object")
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported schema_version {data.get('schema_version')!r}, expected 1")
    briefs = data.get("briefs")
    if not isinstance(briefs, list) or not briefs:
        raise ValueError("briefs must be a non-empty array of AnalysisBrief objects")
    return data


def audit(data: dict) -> str:
    """Validate every brief, then print a per-brief claim-kind census."""
    seen_ids: set = set()
    story_ids: set = set()
    lines = ["解读审计｜analysis_briefs.json"]
    for position, brief in enumerate(data["briefs"], 1):
        if not isinstance(brief, dict):
            raise ValueError(f"briefs[{position}] must be a JSON object")
        story_id = brief.get("story_id")
        if not isinstance(story_id, str) or not story_id.strip():
            raise ValueError(f"briefs[{position}] has no story_id")
        if story_id in story_ids:
            raise ValueError(f"duplicate brief for {story_id}; one brief per selected story")
        story_ids.add(story_id)
        _require_text(brief.get("headline"), f"{story_id}: headline must not be empty")
        _require_text(brief.get("angle"), f"{story_id}: angle must not be empty; a brief without a judgement says nothing")
        claims = brief.get("claims")
        if not isinstance(claims, list):
            raise ValueError(f"{story_id}: claims must be an array")
        for index, claim in enumerate(claims, 1):
            _check_claim(story_id, claim, index, seen_ids)
        _check_dependencies(story_id, claims)
        counts = {kind: sum(1 for claim in claims if claim["kind"] == kind) for kind in KINDS}
        line = "  ".join(f"{kind}={counts[kind]}" for kind in KINDS)
        lines.append(f"{story_id}  断言 {len(claims)} 条  {line}")
    lines.append(f"合计：{len(story_ids)} 个 brief，{len(seen_ids)} 条断言")
    lines.append("结构合法不等于内容为真：FACT 的引语是否逐字、推论是否成立、观察信号是否可检验，仍需人工复核。")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="审计 analysis_briefs.json（只读，不修改任何文件）")
    parser.add_argument("briefs", type=Path, help="Path to analysis_briefs.json")
    arguments = parser.parse_args()
    try:
        print(audit(load(arguments.briefs)))
    except (ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
