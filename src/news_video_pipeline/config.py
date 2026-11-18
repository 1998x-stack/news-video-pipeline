from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

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
    return config
