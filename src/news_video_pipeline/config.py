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
    if int(config["voice"]["sample_rate"]) not in {16000, 22050, 24000, 44100, 48000}:
        raise ValueError("Unsupported sample rate")
    if config["render"].get("embed_subtitles"):
        raise NotImplementedError("render.embed_subtitles is planned but not implemented; use external SRT")
    if int(config["render"]["fps"]) <= 0:
        raise ValueError("fps must be positive")
    return config
