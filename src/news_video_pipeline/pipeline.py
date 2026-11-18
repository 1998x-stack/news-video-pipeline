from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import __version__
from .models import Scene
from .planner import plan, read_input
from .quality import file_hash, validate_outputs
from .slides import render_slides
from .timeline import make_audio_and_timeline, write_srt
from .tts import encode_mp3
from .video import render_video


def atomic_json(path: Path, obj: dict | list) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def lock_run(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def identity(input_path: Path, cfg: dict, source_url: str = "") -> str:
    content = input_path.read_bytes()
    digest = hashlib.sha256()
    digest.update(content)
    digest.update(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    digest.update(source_url.strip().encode("utf-8"))
    digest.update(__version__.encode("ascii"))
    return digest.hexdigest()[:16]


def run(input_path: Path, output_root: Path, cfg: dict, *, force: bool = False, source_url: str = "") -> Path:
    input_path = input_path.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    title, body = read_input(input_path)
    run_id = identity(input_path, cfg, source_url)
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{input_path.stem[:55]}-{run_id}"
    with lock_run(output_root / f".{run_id}.lock"):
        manifest_file = target / "manifest.json"
        if manifest_file.is_file() and not force:
            try:
                existing = verify_manifest(target)
            except (ValueError, OSError, TypeError, json.JSONDecodeError):
                # A forged, incomplete or damaged cache never counts as success.
                # Fall through to a fresh staged build, preserving the input.
                pass
            else:
                if (existing.get("run_id") == run_id
                        and existing.get("engine_version") == __version__
                        and existing.get("config") == cfg
                        and existing.get("input_sha256") == file_hash(input_path)):
                    return target
        stage = Path(tempfile.mkdtemp(prefix=f".building-{run_id}-", dir=output_root))
        try:
            (stage / "source.txt").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
            scenes = plan(title, body, cfg)
            atomic_json(stage / "scenes.json", [scene.to_dict() for scene in scenes])
            print(f"[1/5] planned {len(scenes)} scenes", flush=True)
            images = render_slides(scenes, title, cfg, stage / "presentation" / "slides")
            print(f"[2/5] created PPTX + {len(images)} slide images", flush=True)
            timeline = make_audio_and_timeline(scenes, cfg, stage, output_root / ".cache" / "tts")
            encode_mp3(stage / "audio" / "narration.wav", stage / "audio" / "narration.mp3")
            write_srt(timeline, stage / "subtitles" / "zh.srt")
            print(f"[3/5] TTS + SRT: {timeline['duration_ms']} ms", flush=True)
            render_video(images, timeline, stage / "audio" / "narration.wav", stage / "video" / "landscape.mp4", cfg)
            print("[4/5] rendered MP4", flush=True)
            qa = validate_outputs(stage, scenes, timeline, cfg)
            atomic_json(stage / "qa_report.json", qa)
            print("[5/5] QA passed", flush=True)
            assets = {str(path.relative_to(stage)): file_hash(path) for path in stage.rglob("*") if path.is_file() and path.name != "manifest.json"}
            atomic_json(stage / "manifest.json", {
                "schema_version": 1, "engine_version": __version__, "run_id": run_id,
                "source_name": input_path.name, "source_url": source_url, "rights_status": "unverified",
                "input_sha256": file_hash(input_path), "title": title, "status": "qa_passed",
                "config": cfg, "sha256": assets,
                "public_release_approved": False,
            })
            if target.exists():
                # Only replace an exact engine-generated output, never arbitrary directories.
                old = target / "manifest.json"
                if not old.is_file() or json.loads(old.read_text(encoding="utf-8")).get("run_id") != run_id:
                    raise RuntimeError(f"Refusing to replace unmanaged output directory: {target}")
                shutil.rmtree(target)
            os.replace(stage, target)
            return target
        except Exception:
            # Keep failed staging directory for inspection/recovery; never publish it.
            (stage / "FAILED.txt").write_text("This run failed; inspect logs and retry. No publication occurred.\n", encoding="utf-8")
            raise


def verify_manifest(directory: Path) -> dict:
    """Fail closed on a missing, failed, tampered or unsafe manifest."""
    directory = directory.resolve()
    manifest_file = directory / "manifest.json"
    if not manifest_file.is_file():
        raise FileNotFoundError(manifest_file)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("status") != "qa_passed":
        raise ValueError(f"Manifest status is not qa_passed: {manifest.get('status')!r}")
    assets = manifest.get("sha256")
    if not isinstance(assets, dict) or not assets:
        raise ValueError("Manifest has no file hashes; cannot verify output integrity")
    for name, digest in assets.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ValueError("Malformed manifest hash entry")
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError(f"Unsafe or missing manifest asset: {name}")
        if file_hash(path) != digest:
            raise ValueError(f"Output file hash mismatch: {name}")
    return manifest


def validate_existing(directory: Path, cfg: dict) -> dict:
    manifest = verify_manifest(directory)
    directory = directory.resolve()
    scenes_data = json.loads((directory / "scenes.json").read_text(encoding="utf-8"))
    scenes = [Scene(**{**scene, "sentences": tuple(scene["sentences"])}) for scene in scenes_data]
    timeline = json.loads((directory / "timeline.json").read_text(encoding="utf-8"))
    return {
        **validate_outputs(directory, scenes, timeline, cfg),
        "run_id": manifest.get("run_id"),
        "assets_verified": len(manifest["sha256"]),
        "engine_version": manifest.get("engine_version"),
        "public_release_approved": False,
        "human_review_required": ["news facts", "rights/licensing", "platform release"],
    }
