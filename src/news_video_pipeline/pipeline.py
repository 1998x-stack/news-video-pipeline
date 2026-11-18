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
from .editorial import critique as editorial_critique
from .editorial import extractor as editorial_extractor
from .editorial import insight as editorial_insight
from .editorial import ranking as editorial_ranking
from .editorial import scripting as editorial_scripting
from .editorial import selection as editorial_selection
from .editorial.llm import EditorialLLM

EDITORIAL_MODES = ("none", "curated-analysis")
EDITORIAL_ARTIFACTS = (
    "news_items.json",
    "editorial_ranking.json",
    "editorial_selection.json",
    "analysis_briefs.json",
    "claims.json",
    "editorial_script.md",
)


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


def _editorial_llm(cfg: dict, output_root: Path) -> EditorialLLM:
    """Indirection so tests can substitute a fake editorial model."""
    return EditorialLLM(cfg, cache_dir=output_root / ".cache" / "editorial")


def build_editorial_assets(title: str, body: str, cfg: dict, stage: Path, output_root: Path) -> tuple[list[Scene], dict]:
    """The AI news-chief-editor chain: extract → rank → select → brief → script → scene.

    Every stage writes its artifact before the next one starts, so a later failure
    never forces re-paying for an earlier model call, and the whole decision trail
    is auditable after the fact.
    """
    llm = _editorial_llm(cfg, output_root)
    candidates, extraction = editorial_extractor.extract_candidates(body, title, cfg, llm=llm)
    print(f"[editorial] 已识别 {len(candidates)} 条候选新闻"
          f"（快讯容器 {extraction['aggregate_blocks']} 个，拆出简讯 {extraction['split_briefs']} 条）", flush=True)
    atomic_json(stage / "news_items.json", {
        "schema_version": 1, "source_id": extraction["source_id"],
        "report": extraction, "items": [item.to_dict() for item in candidates],
    })
    if not candidates:
        raise ValueError("No story candidates were extracted; refusing to produce a curated video")
    ratings = editorial_ranking.rate_candidates(candidates, cfg, llm)
    print(f"[editorial] 已完成第一轮重要性评估（{len(ratings)} 条，按七维度加权）", flush=True)
    atomic_json(stage / "editorial_ranking.json", {
        "schema_version": 1,
        "weights": cfg["editorial"]["weights"],
        "rows": editorial_ranking.ranked_table(ratings, candidates),
    })
    selection = editorial_selection.select(candidates, ratings, cfg, llm)
    print(f"[editorial] 已选出 {len(selection.selected)} 条重点新闻"
          f"（复核 {min(len(ratings), int(cfg['editorial']['shortlist']))} 条，入选不足={selection.insufficient}）", flush=True)
    atomic_json(stage / "editorial_selection.json", {"schema_version": 1, **selection.to_dict()})
    if not selection.selected:
        raise ValueError(
            "No story cleared the editorial thresholds; refusing to pad the selection into a video"
        )
    briefs = editorial_insight.build_briefs(list(selection.selected), candidates, cfg, llm)
    report = editorial_insight.claim_report(briefs)
    print(f"[editorial] 正在形成独立解读：{len(briefs)} 份分析简报，"
          f"{report['counts']['FACT']} 条事实 / {report['counts']['INFERENCE']} 条推论，已核查来源", flush=True)
    atomic_json(stage / "analysis_briefs.json", {
        "schema_version": 1, "briefs": [brief.to_dict() for brief in briefs],
    })
    atomic_json(stage / "claims.json", {
        "schema_version": 1, "counts": report["counts"],
        "claims": [claim.to_dict() for claim in editorial_insight.all_claims(briefs)],
    })
    script, critic = editorial_critique.build_script_with_critique(briefs, selection, cfg, llm, candidates)
    print(f"[editorial] 正在生成视频脚本并执行内容批评（未达标维度：{critic['failed'] or '无'}）", flush=True)
    (stage / "editorial_script.md").write_text(script.markdown(), encoding="utf-8")
    scenes = editorial_scripting.script_to_scenes(script, cfg)
    grounded = editorial_scripting.assert_selection_grounded(script, candidates, selection, cfg)
    atomic_json(stage / "editorial_report.json", {
        "schema_version": 1,
        "mode": "curated-analysis",
        "extraction": extraction,
        "selection": selection.to_dict(),
        "claims": report["counts"],
        "critic": critic,
        "grounding": grounded,
        "llm": llm.summary(),
        "note": "Editorial decisions and technical QA are separate from human fact/rights/release approval.",
    })
    return scenes, {
        "mode": "curated-analysis",
        "candidates": len(candidates),
        "selected": list(selection.selected),
        "insufficient": selection.insufficient,
        "claims": report["counts"],
        "sections": len(script.sections),
    }


def run(input_path: Path, output_root: Path, cfg: dict, *, force: bool = False, source_url: str = "",
        editorial: str = "none", top_k: int | None = None) -> Path:
    input_path = input_path.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if editorial not in EDITORIAL_MODES:
        raise ValueError(f"Unsupported editorial mode: {editorial!r}; expected one of {list(EDITORIAL_MODES)}")
    cfg["editorial"]["mode"] = editorial
    if top_k is not None:
        cfg["editorial"]["top_k"] = int(top_k)
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
            curated = {}
            if cfg["editorial"]["mode"] == "curated-analysis":
                scenes, curated = build_editorial_assets(title, body, cfg, stage, output_root)
            else:
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
            qa = validate_outputs(stage, scenes, timeline, cfg,
                                  editorial_artifacts=cfg["editorial"]["mode"] == "curated-analysis")
            atomic_json(stage / "qa_report.json", qa)
            print("[5/5] QA passed", flush=True)
            assets = {str(path.relative_to(stage)): file_hash(path) for path in stage.rglob("*") if path.is_file() and path.name != "manifest.json"}
            atomic_json(stage / "manifest.json", {
                "schema_version": 1, "engine_version": __version__, "run_id": run_id,
                "source_name": input_path.name, "source_url": source_url, "rights_status": "unverified",
                "input_sha256": file_hash(input_path), "title": title, "status": "qa_passed",
                "config": cfg, "sha256": assets,
                "editorial": curated or {"mode": "none"},
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
    editorial = manifest.get("editorial") or {"mode": "none"}
    result = {
        **validate_outputs(directory, scenes, timeline, cfg,
                           editorial_artifacts=editorial.get("mode") == "curated-analysis"),
        "run_id": manifest.get("run_id"),
        "assets_verified": len(manifest["sha256"]),
        "engine_version": manifest.get("engine_version"),
        "editorial": editorial,
        "public_release_approved": False,
        "human_review_required": ["news facts", "rights/licensing", "platform release"],
    }
    return result
