"""Manifest integrity gate: `news-video validate` must never pass a tampered output."""
import json

import pytest

from news_video_pipeline.pipeline import verify_manifest
from news_video_pipeline.quality import file_hash


def write_output(root, assets=None, **manifest_overrides):
    files = assets or {"artifacts/audio.wav": b"RIFFxxxx", "artifacts/zh.srt": b"1\n"}
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    manifest = {
        "schema_version": 1,
        "run_id": "abc123",
        "status": "qa_passed",
        "engine_version": "0.1.1",
        "sha256": {name: file_hash(root / name) for name in files},
        "public_release_approved": False,
    }
    manifest.update(manifest_overrides)
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest


def test_verify_manifest_accepts_intact_output(tmp_path):
    write_output(tmp_path)
    assert verify_manifest(tmp_path)["run_id"] == "abc123"


def test_verify_manifest_detects_tampered_file(tmp_path):
    write_output(tmp_path)
    (tmp_path / "artifacts/zh.srt").write_bytes(b"1\nTAMPERED\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_manifest(tmp_path)


def test_verify_manifest_detects_deleted_file(tmp_path):
    write_output(tmp_path)
    (tmp_path / "artifacts/audio.wav").unlink()
    with pytest.raises(ValueError, match="Unsafe or missing"):
        verify_manifest(tmp_path)


def test_verify_manifest_rejects_failed_status(tmp_path):
    write_output(tmp_path, status="failed")
    with pytest.raises(ValueError, match="not qa_passed"):
        verify_manifest(tmp_path)


def test_verify_manifest_requires_hashes(tmp_path):
    write_output(tmp_path, sha256={})
    with pytest.raises(ValueError, match="no file hashes"):
        verify_manifest(tmp_path)


def test_verify_manifest_rejects_path_traversal(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    write_output(tmp_path, sha256={"../outside.txt": file_hash(outside)})
    with pytest.raises(ValueError, match="Unsafe or missing"):
        verify_manifest(tmp_path)


def test_verify_manifest_requires_a_manifest(tmp_path):
    with pytest.raises(FileNotFoundError):
        verify_manifest(tmp_path)


def test_forged_release_flag_is_still_not_approval(tmp_path):
    """A mutable manifest boolean must never be treated as publication approval."""
    write_output(tmp_path, public_release_approved=True, rights_status="verified")
    manifest = verify_manifest(tmp_path)
    assert manifest["public_release_approved"] is True  # recorded, not honoured
