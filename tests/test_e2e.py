import json
import shutil
from pathlib import Path

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.pipeline import run, identity, validate_existing


def small_config():
    cfg = load_config()
    cfg["voice"]["provider"] = "synthetic"
    cfg["render"]["width"] = 640
    cfg["render"]["height"] = 360
    return cfg


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg not installed")
def test_pipeline_and_cache(tmp_path: Path):
    inp = tmp_path / "short.md"
    inp.write_text("# 示例标题\n\n第一句话。第二句话。\n\n第三句话。", encoding="utf-8")
    cfg = small_config()
    target = run(inp, tmp_path / "results", cfg)
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "qa_passed"
    assert (target / "presentation" / "daily.pptx").is_file()
    assert (target / "audio" / "narration.mp3").is_file()
    assert (target / "subtitles" / "zh.srt").is_file()
    assert (target / "video" / "landscape.mp4").is_file()
    assert target == run(inp, tmp_path / "results", cfg)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg not installed")
def test_validate_existing_verifies_hashes_and_rebuilds_tampered_output(tmp_path: Path):
    inp = tmp_path / "news.md"
    inp.write_text("# 标题\n\n第一句话。第二句话。", encoding="utf-8")
    cfg = small_config()
    target = run(inp, tmp_path / "results", cfg)
    report = validate_existing(target, cfg)
    assert report["status"] == "passed"
    assert report["assets_verified"] > 0
    assert report["public_release_approved"] is False

    (target / "subtitles" / "zh.srt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_existing(target, cfg)
    # The run-level cache must notice the damaged output and rebuild it.
    assert run(inp, tmp_path / "results", cfg) == target
    assert validate_existing(target, cfg)["status"] == "passed"


def test_failed_staging_is_never_published(tmp_path: Path, monkeypatch):
    inp = tmp_path / "news.md"
    inp.write_text("# 标题\n\n第一句话。", encoding="utf-8")
    cfg = small_config()

    def boom(*args, **kwargs):
        raise RuntimeError("injected renderer failure")

    monkeypatch.setattr("news_video_pipeline.pipeline.render_video", boom)
    with pytest.raises(RuntimeError, match="injected"):
        run(inp, tmp_path / "results", cfg)
    assert not list((tmp_path / "results").glob("news-*"))
    staging = list((tmp_path / "results").glob(".building-*"))
    assert len(staging) == 1 and (staging[0] / "FAILED.txt").is_file()
    assert not (staging[0] / "manifest.json").exists()


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
