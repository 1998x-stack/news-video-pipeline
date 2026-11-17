from __future__ import annotations

import json
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

from .models import Scene


PUNCTUATION = re.compile(r"(?<=[。！？!?；;])\s*|(?<=\.)\s+(?=[A-Z])")
CLAUSE = re.compile(r"(?<=[，,、；;：:])")
NUMERIC = re.compile(r"\d+(?:[.,]\d+)*")
KEEP = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
# The slide layout wraps the heading over two lines and the body over seven; these
# limits are the shared contract for both planner providers.
TITLE_LIMIT = 40


def normalize_text(text: str) -> str:
    """Case/whitespace/punctuation-insensitive form used for grounding checks."""
    return KEEP.sub("", text.lower())


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


def title_from(text: str) -> str:
    """Derive a slide heading that always fits the two-line heading box."""
    text = text.strip()
    return text[:TITLE_LIMIT] + ("…" if len(text) > TITLE_LIMIT else "")


def split_oversized(sentence: str, limit: int) -> list[str]:
    """Split one narration sentence so no piece exceeds the scene budget.

    Whole text is preserved: pieces are cut at Chinese clause punctuation first,
    and only a single over-long clause is hard-split.
    """
    if len(sentence) <= limit:
        return [sentence]
    pieces: list[str] = []
    buffer = ""
    for clause in [x for x in CLAUSE.split(sentence) if x]:
        if len(clause) > limit:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            pieces.extend(clause[i:i + limit] for i in range(0, len(clause), limit))
        elif len(buffer) + len(clause) > limit:
            pieces.append(buffer)
            buffer = clause
        else:
            buffer += clause
    if buffer:
        pieces.append(buffer)
    return pieces


def pack_narration(narration: list[str], limit: int) -> list[list[str]]:
    """Greedily group sentences into scenes that satisfy the slide length contract.

    Nothing is dropped and nothing is reworded; only grouping changes.
    """
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for sentence in narration:
        for piece in split_oversized(sentence, limit):
            if current and size + len(piece) > limit:
                groups.append(current)
                current, size = [], 0
            current.append(piece)
            size += len(piece)
    if current:
        groups.append(current)
    return groups


def heuristic_plan(title: str, body: str, max_chars: int, max_scenes: int) -> list[Scene]:
    if not body.strip():
        raise ValueError("Input text is empty")
    # Group sentences into readable scenes without losing or silently truncating information.
    paragraphs = [p.strip().lstrip("-• ") for p in re.split(r"\n\s*\n", body) if p.strip()]
    parts: list[list[str]] = []
    for para in paragraphs:
        if para.startswith("#"):
            continue
        parts.extend(pack_narration(sentences(re.sub(r"\[(.*?)\]\(.*?\)", r"\1", para)), max_chars))
    if not parts:
        raise ValueError("Input contains no narration-worthy paragraphs")
    if len(parts) > max_scenes:
        raise ValueError(f"Input requires {len(parts)} scenes; planner.max_scenes={max_scenes}; raise planner.max_scenes rather than truncate the manuscript")
    return [
        Scene(id=f"scene_{idx:03d}", title=title_from(pieces[0]), body="".join(pieces), sentences=tuple(pieces))
        for idx, pieces in enumerate(parts, 1)
    ]


def _openai_client(config: dict):
    """Indirection so tests can substitute a fake OpenAI-compatible client."""
    from openai import OpenAI

    planner = config["planner"]
    return OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=planner["base_url"] or None,
        timeout=float(planner["timeout_s"]),
        max_retries=int(planner["max_retries"]),
    )


def collect_stream(stream, max_total_s: float | None = None, clock=time.monotonic) -> str:
    """Join assistant content from a streaming Chat Completions response.

    Streaming matters for thinking gateways: the socket keeps producing reasoning
    chunks, so a slow manuscript trips a per-read timeout instead of a hard
    total-request timeout. Streaming alone would allow an unbounded stall, so the
    loop also enforces its own wall-clock deadline.
    """
    deadline = None if max_total_s is None else clock() + max_total_s
    pieces: list[str] = []
    for chunk in stream:
        if deadline is not None and clock() > deadline:
            raise TimeoutError(
                f"LLM call exceeded planner.max_total_s={max_total_s:g}s; "
                "raise it only after lowering the manuscript size or max_scenes"
            )
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        content = getattr(choices[0].delta, "content", None)
        if content:
            pieces.append(content)
    return "".join(pieces)


def grounding_report(source: str, scenes: list[Scene]) -> dict:
    """Deterministic, offline check that LLM narration stays inside the source."""
    narration = "".join(sentence for scene in scenes for sentence in scene.sentences)
    source_tokens = set(NUMERIC.findall(source))
    invented = sorted(token for token in set(NUMERIC.findall(narration)) if token not in source_tokens)
    normalized_source = normalize_text(source)
    normalized_output = normalize_text(narration)
    if not normalized_output:
        return {"coverage": 0.0, "invented_tokens": invented}
    matcher = SequenceMatcher(None, normalized_source, normalized_output, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return {"coverage": matched / len(normalized_output), "invented_tokens": invented}


def assert_grounded(source: str, scenes: list[Scene], min_coverage: float) -> dict:
    """Fail closed: never render narration that the source text cannot support."""
    report = grounding_report(source, scenes)
    if report["invented_tokens"]:
        raise ValueError(
            "LLM narration contains numbers/dates absent from the source: "
            f"{report['invented_tokens']}; refusing to render unverified output"
        )
    if report["coverage"] < min_coverage:
        raise ValueError(
            f"LLM narration only matches {report['coverage']:.2f} of the source text "
            f"(planner.min_source_coverage={min_coverage}); refusing to render unverified output"
        )
    return report


def llm_plan(title: str, body: str, config: dict) -> list[Scene]:
    """Optional LLM copy edit. No invented citations; human verification is still required."""
    try:
        import openai  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("pip install '.[llm]' to enable openai-compatible planner") from exc

    planner = config["planner"]
    model = planner["model"]
    if not model or not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY and planner.model (or OPENAI_MODEL) are required")
    max_chars = int(planner["max_chars_per_scene"])
    instruction = (
        "仅根据用户所给原文整理中文信息视频分镜。不得增添新数字、政策、引语、日期、出处或结论。"
        "输出纯 JSON 对象：{\"scenes\":[{\"title\":\"...\",\"body\":\"...\",\"sentences\":[\"...\"]}]}。"
        "每个 sentences 项应为适合逐句 TTS 的完整短句；把原稿信息保留完整。"
        f"每个场景的 body 不得超过 {max_chars} 个字，每句不得超过 {max_chars} 个字，标题不得超过 {TITLE_LIMIT} 个字。"
        "信息较多时必须拆成更多场景，不得省略或压缩原文内容。"
        "严禁添加 Markdown 围栏。"
    )
    request = {
        "model": model,
        "messages": [{"role": "system", "content": instruction},
                     {"role": "user", "content": f"标题：{title}\n原文：\n{body}"}],
        "temperature": float(planner.get("temperature", 0)),
        "max_tokens": int(planner["max_tokens"]),
        "stream": True,
    }
    effort = str(planner.get("reasoning_effort") or "").strip()
    if effort:
        request["reasoning_effort"] = effort
    answer = collect_stream(
        _openai_client(config).chat.completions.create(**request),
        max_total_s=float(planner["max_total_s"]),
    )
    if not answer.strip():
        raise ValueError(
            "LLM returned no content; a thinking model may have spent the whole "
            "planner.max_tokens budget on hidden reasoning. Raise planner.max_tokens "
            "or set planner.reasoning_effort (for example 'none')."
        )
    try:
        content = json.loads(answer)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM did not return valid JSON; refusing to render unverified output") from exc
    raw = content.get("scenes", []) if isinstance(content, dict) else []
    max_scenes = int(planner["max_scenes"])
    if not isinstance(raw, list) or not raw:
        raise ValueError("LLM returned no scenes; refusing to render unverified output")
    normalized: list[Scene] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Invalid scene")
        chunks = entry.get("sentences")
        if not isinstance(chunks, list) or not chunks or any(not isinstance(x, str) or not x.strip() for x in chunks):
            raise ValueError("Invalid narration sentences")
        # The model does not control layout: re-group its sentences so every scene
        # honours the shared slide contract. Nothing is dropped or reworded.
        heading = title_from(str(entry.get("title") or ""))
        for group in pack_narration([x.strip() for x in chunks], max_chars):
            normalized.append(Scene(id=f"scene_{len(normalized) + 1:03d}", title=heading or title_from(group[0]),
                                    body="".join(group), sentences=tuple(group)))
            heading = ""
    if len(normalized) > max_scenes:
        raise ValueError(
            f"LLM narration needs {len(normalized)} scenes; planner.max_scenes={max_scenes}; "
            "raise planner.max_scenes rather than truncate"
        )
    assert_grounded(body, normalized, float(planner["min_source_coverage"]))
    return normalized


def plan(title: str, body: str, cfg: dict) -> list[Scene]:
    pc = cfg["planner"]
    if pc["provider"] == "openai-compatible":
        return llm_plan(title, body, cfg)
    return heuristic_plan(title, body, int(pc["max_chars_per_scene"]), int(pc["max_scenes"]))
