"""Bounded LLM stages for the editorial layer (task 4).

Every editorial stage goes through :class:`EditorialLLM`, which enforces the same
discipline the planner already uses for long manuscripts:

* streamed requests, so a thinking gateway does not trip a per-read timeout;
* a hard wall-clock ceiling (``planner.max_total_s``) including blocked reads;
* a JSON answer plus a per-stage required-key check, so a malformed reply never
  reaches the selectors as partial data;
* a bounded number of retries, and every attempt recorded;
* an optional on-disk cache keyed by stage+payload so a re-run never re-pays.

The cache is opt-in: without ``cache_dir`` every call goes to the model.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from ..planner import _openai_client, collect_stream, hard_deadline

FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")

# Keys each stage must return. A missing key means the model did not answer the
# question, which is a failure, not an empty result.
STAGE_KEYS: dict[str, tuple[str, ...]] = {
    "aggregate_split": ("items",),
    "understand": ("stories",),
    "rank": ("ratings",),
    "compare": ("comparisons",),
    "brief": ("brief",),
    "script": ("opening_hook", "sections", "closing_synthesis"),
    "critique": ("scores",),
}

SYSTEM_PROMPTS: dict[str, str] = {
    "aggregate_split": (
        "你是新闻节目拆条编辑。用户给出一段中文新闻联播「联播快讯」正文，其中若干条独立简讯被直接连排在一起。"
        "请你只做切分，不做改写。要求："
        "1) 返回 items 数组，每项是该条简讯的原文片段（逐一复制原字符，一个字都不能增删改），按原文顺序排列；"
        "2) 所有 items 首尾相接必须完整等于用户给出的整段正文，不允许遗漏、重复或调换顺序；"
        "3) 不要把一条简讯拆成两条，也不要把两条合并；"
        "4) 只输出 JSON 对象 {\"items\":[\"...\"]}，不要 Markdown 围栏，不要解释。"
    ),
    "rank": (
        "你是具有编辑判断力的中文新闻主编。用户给出候选新闻（含标题和原文片段），"
        "请只依据给定的原文进行评分，不得引入原文之外的事实。"
        "对每条新闻按七个维度打 0-10 的整数分：public_impact（公共影响力）、structural_importance（长期结构性重要性）、"
        "information_novelty（新信息价值）、analytical_depth（解读价值）、timeliness（时效性）、evidence_quality（可核实性）、"
        "audience_utility（受众理解与注意力价值）。"
        "维度分必须互相独立，不要因为题材适合做视频就整体拉高。"
        "同时给出 topic（如 economy/politics/diplomacy/technology/society/energy/education/health/safety/culture）、"
        "confidence（0-1 的浮点数，表示你对本次判断的把握）、"
        "new_information（该条相对一般认知真正新增的信息，没有就给空数组）、"
        "uncertainties（无法从原文确认的内容）。"
        "reasons 必须为每个维度给出一句基于原文的具体理由，不要写「意义重大」这类空话。"
        "只输出 JSON：{\"ratings\":[{\"story_id\":\"...\",\"scores\":{...},\"reasons\":{...},\"topic\":\"...\","
        "\"confidence\":0.0,\"new_information\":[],\"uncertainties\":[]}]}。不要 Markdown 围栏。"
    ),
    "compare": (
        "你是新闻主编，正在复核第一轮排名靠前的候选新闻。请做比较，而不是重新独立打分。"
        "对每条候选回答：它是否与另一条讲的是同一件事（same_event_as，填对方 story_id 或 null）；"
        "是否为没有新进展的重复报道（repeat_without_progress，true/false）；"
        "第一轮分数是否被高估或低估（adjustment，-15 到 +15 的整数）；"
        "理由（note，必须引用原文中的具体信息）；是否存在不可解决的事实缺口（evidence_gap，true/false）。"
        "只输出 JSON：{\"comparisons\":[{\"story_id\":\"...\",\"same_event_as\":null,\"repeat_without_progress\":false,"
        "\"adjustment\":0,\"note\":\"...\",\"evidence_gap\":false}]}。不要 Markdown 围栏。"
    ),
    "brief": (
        "你是中文新闻分析员。用户给出**一条**已入选新闻的原文与标题。请给出独立解读，严格区分事实、推论、观点和未知。"
        "要求："
        "1) angle：这条新闻最值得讲的核心判断（一句话）；"
        "2) mechanisms：2-3 条机制解释，说明为什么会发生、由什么推动；"
        "3) second_order：二阶影响，必须明确是推论；"
        "4) counterpoints：至少一条替代解释或反例，以及主要判断成立的条件；"
        "5) watch_indicators：后续可检验该判断的具体观察信号；"
        "6) uncertainty：无法从原文确认的部分；"
        "7) claims：数组，每项 {kind, text, quote, depends_on, reasoning, limitation}。"
        "kind 必须是 FACT / INFERENCE / OPINION / UNKNOWN 之一。"
        "FACT 的 quote 必须是原文中逐字出现的片段；INFERENCE 的 depends_on 必须引用同一批 claims 中已有 FACT 的 claim_id；"
        "OPINION 必须写出你的判断标准；UNKNOWN 必须保留不确定，不要编造答案。"
        "禁止新增原文中没有的数字、日期、机构、人物或引语。"
        "只输出 JSON：{\"brief\":{...}}。不要 Markdown 围栏。"
    ),
    "script": (
        "你是分析型中文新闻评论员，为普通观众写一段 6-10 分钟的视频解说稿。"
        "用户给出已入选新闻的分析要点与原文。要求："
        "1) opening_hook：10-20 秒开场，直接讲今天最重要的新信号或最值得思考的问题，不要自我介绍；"
        "2) sections：数组，每项 {story_id, kind, heading, narration}，kind 为 top（最重要的一条）或 supporting；"
        "narration 必须是可直接朗读的完整句子，逐句成篇，事实—解释—论证—转场—结论各有功能，删掉没有信息量的句子；"
        "3) closing_synthesis：15-30 秒结尾，只在几条新闻之间确实存在联系时点明，没有可靠联系就不要强行制造大趋势；"
        "4) 只讲入选新闻，绝对不要提到未入选的新闻；"
        "5) 不得出现原文之外的数字、日期、机构或引语；推论必须写成推论（例如「这意味着」「一种可能是」），不得说成已证实的事实。"
        "只输出 JSON：{\"opening_hook\":\"...\",\"sections\":[...],\"closing_synthesis\":\"...\"}。不要 Markdown 围栏。"
    ),
    "critique": (
        "你是新闻内容质量审核员。请针对用户给出的解说稿与分析要点打分并提出**具体可验证**的问题，不要提出新的观点。"
        "按七个维度给 0-10 整数分：factual_grounding（是否有原文之外的事实）、analytical_depth（是否解释了机制而非复述）、"
        "original_insight（观点是否有依据且非空话）、clarity（普通观众能否听懂）、audience_utility（看完是否获得可复用认知）、"
        "uncertainty_handling（是否把推论当事实）、narrative_coherence（是否形成连贯叙事而非新闻列表）。"
        "另给出 problems 数组，每项必须指出具体句子或具体位置。"
        "只输出 JSON：{\"scores\":{...},\"problems\":[...]}。不要 Markdown 围栏。"
    ),
}


def json_object(answer: str) -> dict:
    """Parse a model answer as a JSON object, tolerating a Markdown fence."""
    text = FENCE.sub("", answer.strip())
    if not text:
        raise ValueError("LLM returned an empty answer")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM did not return valid JSON: {exc.msg} at position {exc.pos}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM returned {type(parsed).__name__}, expected a JSON object")
    return parsed


def require_keys(obj: dict, keys: tuple[str, ...], stage: str) -> dict:
    """Fail closed when a stage answer is structurally incomplete."""
    if not isinstance(obj, dict):
        raise ValueError(f"{stage}: expected a JSON object")
    missing = [key for key in keys if key not in obj]
    if missing:
        raise ValueError(f"{stage}: response is missing required key(s) {missing}")
    return obj


class EditorialLLM:
    """One bounded, logged, optionally cached call per editorial stage."""

    def __init__(self, cfg: dict, cache_dir: Path | None = None, client_factory=None, clock=time.monotonic):
        self.cfg = cfg
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._factory = client_factory or _openai_client
        self._clock = clock
        self.stage_log: list[dict] = []
        self.call_count = 0

    # -- cache -----------------------------------------------------------------
    def _cache_path(self, stage: str, payload: dict, model: str) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256()
        digest.update(stage.encode("utf-8"))
        digest.update(model.encode("utf-8"))
        digest.update(SYSTEM_PROMPTS[stage].encode("utf-8"))
        digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        return self.cache_dir / f"{digest.hexdigest()[:32]}.json"

    # -- call ------------------------------------------------------------------
    def __call__(self, stage: str, payload: dict) -> dict:
        if stage not in STAGE_KEYS:
            raise ValueError(f"Unknown editorial stage: {stage!r}")
        planner = self.cfg["planner"]
        model = planner["model"]
        if not model:
            raise ValueError("planner.model (or OPENAI_MODEL) is required for editorial analysis")
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required for editorial analysis")
        cache_file = self._cache_path(stage, payload, model)
        if cache_file is not None and cache_file.is_file():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            self.stage_log.append({
                "stage": stage, "model": cached.get("model", model), "request_count": 0, "latency_s": 0.0,
                "error": None, "retries": 0, "content_sha256": cached["content_sha256"], "cache_hit": True,
                "usage": cached.get("usage"),
            })
            return require_keys(json_object(cached["content"]), STAGE_KEYS[stage], stage)
        request = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPTS[stage]},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "temperature": float(planner.get("temperature", 0)),
            "max_tokens": int(planner["max_tokens"]),
            "stream": True,
        }
        effort = str(planner.get("reasoning_effort") or "").strip()
        if effort:
            request["reasoning_effort"] = effort
        attempts = int(planner["max_retries"]) + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            started = self._clock()
            try:
                self.call_count += 1
                answer, usage = self._invoke(request)
                latency = self._clock() - started
                self.stage_log.append({
                    "stage": stage, "model": model, "request_count": 1, "latency_s": round(latency, 3),
                    "error": None, "retries": attempt, "cache_hit": False,
                    "content_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(), "usage": usage,
                })
                parsed = require_keys(json_object(answer), STAGE_KEYS[stage], stage)
                if cache_file is not None:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps({
                        "stage": stage, "model": model, "content": answer, "usage": usage,
                        "content_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
                    }, ensure_ascii=False), encoding="utf-8")
                return parsed
            except Exception as error:  # noqa: BLE001 - every failure is recorded and retried or raised
                last_error = error
                self.stage_log.append({
                    "stage": stage, "model": model, "request_count": 1,
                    "latency_s": round(self._clock() - started, 3), "error": f"{type(error).__name__}: {error}",
                    "retries": attempt, "cache_hit": False, "content_sha256": None, "usage": None,
                })
        raise ValueError(f"{stage}: editorial LLM call failed after {attempts} attempt(s): {last_error}")

    def _invoke(self, request: dict) -> tuple[str, dict | None]:
        """Stream one answer, capturing provider-reported usage when present."""
        planner = self.cfg["planner"]
        seen: dict = {}

        def tee(stream):
            for chunk in stream:
                seen["last"] = chunk
                yield chunk

        with hard_deadline(float(planner["max_total_s"])):
            stream = self._factory(self.cfg).chat.completions.create(**request)
            try:
                answer = collect_stream(tee(stream), max_total_s=float(planner["max_total_s"]), clock=self._clock)
            finally:
                if callable(getattr(stream, "close", None)):
                    stream.close()
        usage = None
        raw_usage = getattr(seen.get("last"), "usage", None)
        if raw_usage is not None:
            usage = raw_usage if isinstance(raw_usage, dict) else {
                key: getattr(raw_usage, key, None)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
        return answer, usage

    def summary(self) -> dict:
        """Cost/observability report for the run directory."""
        return {
            "calls": self.call_count,
            "cache_hits": sum(1 for entry in self.stage_log if entry["cache_hit"]),
            "requests": sum(entry["request_count"] for entry in self.stage_log),
            "failures": sum(1 for entry in self.stage_log if entry["error"]),
            "latency_s": round(sum(entry["latency_s"] or 0.0 for entry in self.stage_log), 3),
            "stages": list(self.stage_log),
        }
