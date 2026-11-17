import json
import shutil
from pathlib import Path

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.pipeline import run, identity


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg not installed")
def test_pipeline_and_cache(tmp_path: Path):
    inp = tmp_path / "short.md"
    inp.write_text("# 示例标题\n\n第一句话。第二句话。\n\n第三句话。", encoding="utf-8")
    cfg = load_config()
    cfg["voice"]["provider"] = "synthetic"
    cfg["render"]["width"] = 640
    cfg["render"]["height"] = 360
    target = run(inp, tmp_path / "results", cfg)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "qa_passed"
    assert (target / "presentation" / "daily.pptx").is_file()
    assert (target / "audio" / "narration.mp3").is_file()
    assert (target / "subtitles" / "zh.srt").is_file()
    assert (target / "video" / "landscape.mp4").is_file()
    assert target == run(inp, tmp_path / "results", cfg)


def test_source_url_is_part_of_run_id(tmp_path: Path):
    inp = tmp_path / "a.txt"
    inp.write_text("测试。", encoding="utf-8")
    cfg = load_config()
    assert identity(inp, cfg, "https://a.example") != identity(inp, cfg, "https://b.example")


def test_reject_unsupported_caption_burnin(tmp_path: Path):
    cfg = tmp_path / "invalid.yaml"
    cfg.write_text("render:\n  embed_subtitles: true\n", encoding="utf-8")
    with pytest.raises(NotImplementedError):
        load_config(cfg)
