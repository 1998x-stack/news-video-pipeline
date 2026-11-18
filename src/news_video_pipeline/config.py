from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

from .editorial.models import CRITIQUE_DIMENSIONS, DIMENSIONS

DEFAULT_CONFIG = Path(__file__).with_name("default.yaml")


def merge(base: dict, overrides: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path | None = None) -> dict:
    with DEFAULT_CONFIG.open(encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    if path:
        with Path(path).open(encoding="utf-8") as fh:
            config = merge(config, yaml.safe_load(fh) or {})
    config["planner"]["model"] = config["planner"].get("model") or os.getenv("OPENAI_MODEL", "")
    config["planner"]["base_url"] = config["planner"].get("base_url") or os.getenv("OPENAI_BASE_URL", "")
    if config["voice"]["provider"] not in {"espeak", "edge", "synthetic"}:
        raise ValueError("Unsupported voice.provider")
    if config["planner"]["provider"] not in {"heuristic", "openai-compatible"}:
        raise ValueError("Unsupported planner.provider")
    if int(config["planner"].get("chunk_chars", 0)) < 0 or (
        0 < int(config["planner"].get("chunk_chars", 0)) < 64
    ):
        raise ValueError("planner.chunk_chars must be 0 or at least 64")
    if int(config["planner"].get("max_chunks", 16)) < 1:
        raise ValueError("planner.max_chunks must be >= 1")
    if not 0 < float(config["planner"].get("chunk_min_retention", 0.6)) <= 1:
        raise ValueError("planner.chunk_min_retention must be in (0, 1]")
    if float(config["planner"]["timeout_s"]) <= 0:
        raise ValueError("planner.timeout_s must be positive")
    if float(config["planner"]["max_total_s"]) <= 0:
        raise ValueError("planner.max_total_s must be positive")
    if int(config["planner"]["max_tokens"]) < 256:
        raise ValueError("planner.max_tokens must be at least 256")
    if int(config["planner"]["max_retries"]) < 0:
        raise ValueError("planner.max_retries must not be negative")
    if not 0 < float(config["planner"]["min_source_coverage"]) <= 1:
        raise ValueError("planner.min_source_coverage must be in (0, 1]")
    if int(config["voice"]["sample_rate"]) not in {16000, 22050, 24000, 44100, 48000}:
        raise ValueError("Unsupported sample rate")
    if config["render"].get("embed_subtitles"):
        raise NotImplementedError("render.embed_subtitles is planned but not implemented; use external SRT")
    if config["render"].get("preset", "veryfast") not in {
        "ultrafast", "superfast", "veryfast", "faster", "fast",
        "medium", "slow", "slower", "veryslow",
    }:
        raise ValueError("render.preset is not a supported x264 preset")
    if not 0 <= int(config["render"].get("crf", 22)) <= 51:
        raise ValueError("render.crf must be within 0..51")
    if not 30 <= int(config["render"].get("timeout_s", 1200)) <= 14400:
        raise ValueError("render.timeout_s must be within 30..14400 seconds")
    if int(config["render"]["fps"]) <= 0:
        raise ValueError("fps must be positive")
    validate_editorial(config["editorial"])
    return config


def validate_editorial(editorial: dict) -> dict:
    """Fail closed on an editorial config that could silently change selection."""
    mode = editorial.get("mode", "none")
    if mode not in {"none", "curated-analysis"}:
        raise ValueError(f"Unsupported editorial.mode: {mode!r}")
    weights = editorial.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(DIMENSIONS):
        unknown = sorted(set(weights or {}) - set(DIMENSIONS))
        if unknown:
            raise ValueError(f"editorial.weights has unknown dimension(s): {unknown}")
        raise ValueError(f"editorial.weights must define exactly {list(DIMENSIONS)}")
    if any(not isinstance(v, int) or v < 0 for v in weights.values()):
        raise ValueError("editorial.weights values must be non-negative integers")
    if sum(weights.values()) != 100:
        raise ValueError(f"editorial.weights must sum to 100, got {sum(weights.values())}")
    rubric = editorial.get("critique_min")
    if not isinstance(rubric, dict) or set(rubric) != set(CRITIQUE_DIMENSIONS):
        raise ValueError(f"editorial.critique_min must define exactly {list(CRITIQUE_DIMENSIONS)}")
    if any(not isinstance(v, int) or not 0 <= v <= 10 for v in rubric.values()):
        raise ValueError("editorial.critique_min thresholds must be integers within 0..10")
    top_k, minimum = int(editorial["top_k"]), int(editorial["min_candidates"])
    if minimum < 1 or top_k < minimum:
        raise ValueError(f"editorial.top_k ({top_k}) must be >= editorial.min_candidates ({minimum}) >= 1")
    if int(editorial["shortlist"]) < top_k:
        raise ValueError(f"editorial.shortlist ({editorial['shortlist']}) must be >= editorial.top_k ({top_k})")
    if not 0 < float(editorial["min_confidence"]) <= 1:
        raise ValueError("editorial.min_confidence must be in (0, 1]")
    if not 0 < float(editorial["max_topic_share"]) <= 1:
        raise ValueError("editorial.max_topic_share must be in (0, 1]")
    if not 0 <= float(editorial["min_total_score"]) <= 100:
        raise ValueError("editorial.min_total_score must be within 0..100")
    if int(editorial["batch_size"]) < 1:
        raise ValueError("editorial.batch_size must be >= 1")
    if int(editorial["max_revisions"]) < 0:
        raise ValueError("editorial.max_revisions must not be negative")
    if not 0 < float(editorial["fact_anchor_min"]) <= 1:
        raise ValueError("editorial.fact_anchor_min must be in (0, 1]")
    headings = editorial.get("aggregate_headings")
    if not isinstance(headings, list) or not headings or any(not isinstance(x, str) or not x.strip() for x in headings):
        raise ValueError("editorial.aggregate_headings must be a non-empty list of strings")
    if not 0 < float(editorial["speech_chars_per_second"]) <= 20:
        raise ValueError("editorial.speech_chars_per_second must be in (0, 20]")
    if not 1.0 <= float(editorial["length_tolerance"]) <= 2.0:
        raise ValueError("editorial.length_tolerance must be within 1.0..2.0")
    window = editorial.get("target_duration_ms")
    if (not isinstance(window, list) or len(window) != 2
            or not all(isinstance(x, int) for x in window) or window[0] >= window[1] or window[0] <= 0):
        raise ValueError("editorial.target_duration_ms must be [min_ms, max_ms] with 0 < min < max")
    return editorial
