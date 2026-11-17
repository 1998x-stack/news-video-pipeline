from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Scene


PUNCTUATION = re.compile(r"(?<=[。！？!?；;])\s*|(?<=\.)\s+(?=[A-Z])")


def sentences(text: str) -> list[str]:
    """Keep punctuation and avoid splitting numbers such as 31.2%."""
    text = re.sub(r"\s+", " ", text).strip()
    return [piece.strip() for piece in PUNCTUATION.split(text) if piece.strip()]


def read_input(path: Path) -> tuple[str, str]:
    if path.suffix.lower() not in {".txt", ".md", ".json"}:
        raise ValueError("Input must be .txt, .md or .json")
    if not path.is_file() or path.stat().st_size > 3_000_000:
        raise ValueError("Input does not exist or is larger than 3 MB")
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        item = json.loads(raw)
        if not isinstance(item, dict) or not isinstance(item.get("body"), str):
            raise ValueError("JSON input must have a body string")
        return str(item.get("title") or path.stem), item["body"].strip()
    lines = [x.strip() for x in raw.splitlines() if x.strip()]
    if not lines:
        raise ValueError("Input is empty")
    heading = lines[0].lstrip("# ").strip() if lines[0].startswith("#") else path.stem.replace("_", " ")
    body_lines = lines[1:] if lines[0].startswith("#") else lines
    body = "\n\n".join(x for x in body_lines if not x.startswith("<!--"))
    return heading[:100], body


def heuristic_plan(title: str, body: str, max_chars: int, max_scenes: int) -> list[Scene]:
    if not body.strip():
        raise ValueError("Input text is empty")
    # Group sentences into readable scenes without losing or silently truncating information.
    paragraphs = [p.strip().lstrip("-• ") for p in re.split(r"\n\s*\n", body) if p.strip()]
    parts: list[str] = []
    for para in paragraphs:
        if para.startswith("#"):
            continue
        group = ""
        for item in sentences(re.sub(r"\[(.*?)\]\(.*?\)", r"\1", para)):
            if group and len(group) + len(item) > max_chars:
                parts.append(group)
                group = item
            else:
                group += item
        if group:
            parts.append(group)
    if not parts:
        raise ValueError("Input contains no narration-worthy paragraphs")
    if len(parts) > max_scenes:
        raise ValueError(f"Input requires {len(parts)} scenes; max_scenes={max_scenes}; increase config rather than truncate")
    out = []
    for idx, part in enumerate(parts, 1):
        segment_sentences = sentences(part)
        # Long sentences are kept intact; scene count remains deterministic.
        heading = (segment_sentences[0][:26] + ("…" if len(segment_sentences[0]) > 26 else ""))
        out.append(Scene(id=f"scene_{idx:03d}", title=heading, body=part, sentences=tuple(segment_sentences)))
    return out


def llm_plan(title: str, body: str, config: dict) -> list[Scene]:
    """Optional LLM copy edit. No invented citations; human verification is still required."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("pip install '.[llm]' to enable openai-compatible planner") from exc
    import os

    model = config["planner"]["model"]
    if not model or not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY and planner.model (or OPENAI_MODEL) are required")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=config["planner"]["base_url"] or None, timeout=90, max_retries=2)
    instruction = (
        "仅根据用户所给原文整理中文信息视频分镜。不得增添新数字、政策、引语、日期、出处或结论。"
        "输出纯 JSON 对象：{\"scenes\":[{\"title\":\"...\",\"body\":\"...\",\"sentences\":[\"...\"]}]}。"
        "每个 sentences 项应为适合逐句 TTS 的完整短句；把原稿信息保留完整。"
        "严禁添加 Markdown 围栏。"
    )
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": instruction}, {"role": "user", "content": f"标题：{title}\n原文：\n{body}"}],
        temperature=float(config["planner"].get("temperature", 0)),
    )
    answer = completion.choices[0].message.content or ""
    try:
        content = json.loads(answer)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM did not return valid JSON; refusing to render unverified output") from exc
    raw = content.get("scenes", [])
    if not isinstance(raw, list) or not 1 <= len(raw) <= int(config["planner"]["max_scenes"]):
        raise ValueError("Invalid scenes array")
    result = []
    for index, entry in enumerate(raw, 1):
        if not isinstance(entry, dict):
            raise ValueError("Invalid scene")
        chunks = entry.get("sentences")
        if not isinstance(chunks, list) or not chunks or any(not isinstance(x, str) or not x.strip() for x in chunks):
            raise ValueError("Invalid narration sentences")
        result.append(Scene(id=f"scene_{index:03d}", title=str(entry.get("title", ""))[:100], body=str(entry.get("body", ""))[:2500], sentences=tuple(chunks)))
    return result


def plan(title: str, body: str, cfg: dict) -> list[Scene]:
    pc = cfg["planner"]
    if pc["provider"] == "openai-compatible":
        return llm_plan(title, body, cfg)
    return heuristic_plan(title, body, int(pc["max_chars_per_scene"]), int(pc["max_scenes"]))
