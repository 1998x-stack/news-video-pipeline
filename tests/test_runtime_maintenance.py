"""Safe staging cleanup and configurable FFmpeg rendering tests."""
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from news_video_pipeline.config import load_config
from news_video_pipeline.video import render_video

ROOT = Path(__file__).resolve().parents[1]


def load_prune():
    spec = importlib.util.spec_from_file_location("prune_staging", ROOT / "scripts/prune_staging.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_stage(root: Path, ident="a" * 16):
    root.mkdir(exist_ok=True)
    name = f".building-{ident}-temp123"
    stage = root / name
    stage.mkdir()
    (stage / "FAILED.txt").write_text("diagnostic")
    (root / f".{ident}.lock").touch()
    old = time.time() - 3 * 3600
    os.utime(stage, (old, old))
    return stage


def test_cleanup_dry_run_and_explicit_delete(tmp_path):
    clean = load_prune()
    stage = make_stage(tmp_path)
    report = clean.prune(tmp_path, older_than_hours=2)
    assert stage.name in report["eligible"]
    assert stage.is_dir()
    report = clean.prune(tmp_path, older_than_hours=2, delete=True)
    assert stage.name in report["deleted"]
    assert not stage.exists()


def test_cleanup_refuses_recent_and_completed_stage(tmp_path):
    clean = load_prune()
    recent = make_stage(tmp_path, ident="b" * 16)
    os.utime(recent, None)
    assert clean.prune(tmp_path, older_than_hours=2, delete=True)["deleted"] == []
    old = make_stage(tmp_path, ident="c" * 16)
    (old / "manifest.json").write_text("{}")
    assert clean.prune(tmp_path, older_than_hours=2, delete=True)["deleted"] == []
    assert recent.exists() and old.exists()


def test_cleanup_refuses_active_lock(tmp_path):
    import fcntl
    clean = load_prune()
    stage = make_stage(tmp_path)
    lock = tmp_path / f".{'a'*16}.lock"
    # flock is per-process aware on separate open file descriptions
    with lock.open("rb") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            assert clean.prune(tmp_path, older_than_hours=2, delete=True)["deleted"] == []
            assert stage.exists()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def test_cleanup_refuses_symlinks_and_unknown_dirs(tmp_path):
    clean = load_prune()
    outside = tmp_path.parent / "outside-keep"
    outside.mkdir(exist_ok=True)
    (outside / "keep.txt").write_text("important")
    (tmp_path / (".building-" + "a" * 16 + "-link")).symlink_to(outside, target_is_directory=True)
    (tmp_path / "some-other-dir").mkdir()
    assert clean.prune(tmp_path, older_than_hours=1, delete=True)["deleted"] == []
    assert (outside / "keep.txt").is_file()


@pytest.mark.parametrize("bad", [{"preset": "unsafename"}, {"crf": -1},
                                 {"crf": 52}, {"timeout_s": 0}])
def test_invalid_render_config(tmp_path, bad):
    import yaml
    settings = tmp_path / "bad.yaml"
    settings.write_text(yaml.safe_dump({"render": bad}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(settings)


def test_render_video_uses_configurable_encoder_options(tmp_path, monkeypatch):
    image = tmp_path / "slide.png"
    image.write_bytes(b"irrelevant-mock")
    wav = tmp_path / "narration.wav"
    wav.write_bytes(b"irrelevant-mock")
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("news_video_pipeline.video.shutil.which", lambda _: "/usr/bin/tool")
    monkeypatch.setattr("news_video_pipeline.video.subprocess.run", fake_run)
    cfg = load_config()
    cfg["render"].update(preset="ultrafast", crf=26, timeout_s=3600)
    timeline = {"scenes": [{"start_ms": 0, "end_ms": 1000}],
                "duration_samples": 24000, "sample_rate": 24000}
    render_video([image], timeline, wav, tmp_path / "out.mp4", cfg)
    command, kwargs = commands[0]
    assert command[command.index("-preset") + 1] == "ultrafast"
    assert command[command.index("-crf") + 1] == "26"
    assert kwargs["timeout"] == 3600
    assert not (tmp_path / "slides.ffconcat").exists()
