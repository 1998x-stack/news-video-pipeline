#!/usr/bin/env python3
"""Read-only audit of editorial_selection.json: what was kept and what was dropped.

This tool judges nothing about news value. It proves the selection record is
structurally complete — top_k respected, each candidate listed once, and every
dropped story carrying a reason a human reviewer can read.
"""
import argparse
import json
import sys
from pathlib import Path

FLAG_KEYS = ("duplicate", "low_novelty", "weak_evidence")
# Machine-readable drop codes from editorial/selection.py, glossed for readability.
REASON_GLOSS = {
    "duplicate": "与已选条目讲同一件事（同事件重复）",
    "weak_evidence": "短名单比较发现无法解决的事实缺口",
    "repeat_without_progress": "重复报道但没有新进展",
    "below_min_score": "加权总分低于 min_total_score",
    "low_confidence": "置信度低于 min_confidence",
    "topic_share": "单题材占比达上限（软约束）",
    "below_top_k_cut": "已达标但排在 top_k 之外",
}


def _reason(record: dict) -> str:
    code = str(record["reason"]).strip()
    gloss = REASON_GLOSS.get(code)
    return f"{code}（{gloss}）" if gloss else code


def load(path) -> dict:
    """Parse and check the selection record, or fail closed with one clear message."""
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"selection file not found: {target}") from error
    except IsADirectoryError as error:
        raise ValueError(f"selection path is a directory, expected a JSON file: {target}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"selection file is not valid JSON ({error.msg} at position {error.pos})") from error
    if not isinstance(data, dict):
        raise ValueError("editorial_selection.json must be a JSON object")
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported schema_version {data.get('schema_version')!r}, expected 1")
    top_k = data.get("top_k")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError(f"top_k must be a positive integer, got {top_k!r}")
    selected = data.get("selected")
    if not isinstance(selected, list) or not all(isinstance(x, str) and x.strip() for x in selected):
        raise ValueError("selected must be a list of non-empty story_id strings")
    if len(selected) > top_k:
        raise ValueError(f"selected holds {len(selected)} stories but top_k={top_k}")
    repeated = sorted({story_id for story_id in selected if selected.count(story_id) > 1})
    if repeated:
        raise ValueError(f"selected lists the same story twice: {repeated}")
    rejected = data.get("rejected")
    if not isinstance(rejected, list):
        raise ValueError("rejected must be a list of records")
    listed = set(selected)
    for position, record in enumerate(rejected, 1):
        if not isinstance(record, dict):
            raise ValueError(f"rejected[{position}] must be a JSON object")
        story_id = record.get("story_id")
        if not isinstance(story_id, str) or not story_id.strip():
            raise ValueError(f"rejected[{position}] has no story_id")
        if story_id in listed:
            raise ValueError(f"{story_id} appears more than once across selected/rejected")
        listed.add(story_id)
        reason = str(record.get("reason") or "").strip()
        if not reason:
            raise ValueError(f"{story_id} was dropped without a reason; every drop must be explained")
        total = record.get("total")
        if total is not None and (isinstance(total, bool) or not isinstance(total, (int, float))):
            raise ValueError(f"{story_id}: total must be a number, got {total!r}")
        for flag in FLAG_KEYS:
            value = record.get(flag, False)
            if not isinstance(value, bool):
                raise ValueError(f"{story_id}: {flag} must be true/false, got {value!r}")
    if data.get("selection_config") is not None and not isinstance(data["selection_config"], dict):
        raise ValueError("selection_config must be a JSON object")
    if data.get("notes") is not None and not isinstance(data["notes"], list):
        raise ValueError("notes must be a JSON array of strings")
    if not isinstance(data.get("insufficient", False), bool):
        raise ValueError("insufficient must be true/false")
    return data


def _flags(record: dict) -> str:
    raised = [flag for flag in FLAG_KEYS if record.get(flag)]
    return ",".join(raised) if raised else "-"


def report(data: dict) -> str:
    """A human-readable audit of the kept and the dropped stories."""
    selected, rejected = data["selected"], data["rejected"]
    lines = [
        "选题审计｜editorial_selection.json",
        f"top_k={data['top_k']}  入选={len(selected)}  落选={len(rejected)}  insufficient={bool(data.get('insufficient'))}",
    ]
    config = data.get("selection_config") or {}
    if config:
        lines.append("选区配置: " + "  ".join(f"{key}={config[key]}" for key in sorted(config)))
    lines.append("")
    lines.append(f"入选（{len(selected)}）")
    if selected:
        for position, story_id in enumerate(selected, 1):
            lines.append(f"  {position}. {story_id}")
    else:
        lines.append("  （无）")
    lines.append("")
    lines.append(f"落选（{len(rejected)}）")
    if rejected:
        for position, record in enumerate(rejected, 1):
            total = record.get("total")
            score = f"总分 {total}" if isinstance(total, (int, float)) and not isinstance(total, bool) else "总分 -"
            lines.append(f"  {position}. {record['story_id']}  {score}  标记: {_flags(record)}")
            lines.append(f"     理由: {_reason(record)}")
    else:
        lines.append("  （无）")
    notes = data.get("notes") or []
    if notes:
        lines.append("")
        lines.append("备注")
        for note in notes:
            lines.append(f"  - {note}")
    lines.append("")
    if data.get("insufficient"):
        lines.append("不足：达标条目少于配置的 min_candidates，本次只输出达标条目；补齐名单或放宽阈值都属于伪造选题。")
    lines.append("注意：每条落选都有理由只代表记录完整；未入选条目不得出现在最终旁白，选区配置与权重应随运行记入 Manifest，仍需人工复核。")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="审计 editorial_selection.json（只读，不修改任何文件）")
    parser.add_argument("selection", type=Path, help="Path to editorial_selection.json")
    arguments = parser.parse_args()
    try:
        print(report(load(arguments.selection)))
    except (ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
