from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .editorial import critique as editorial_critique
from .editorial import extractor as editorial_extractor
from .editorial import insight as editorial_insight
from .editorial import ranking as editorial_ranking
from .editorial import scripting as editorial_scripting
from .editorial import selection as editorial_selection
from .editorial.models import AnalysisBrief, StoryCandidate
from .pipeline import run, validate_existing
from .planner import plan, read_input

EDITORIAL_STAGES = ("extract", "rank", "select", "script")


def _atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _build_candidates(args, cfg: dict, out: Path) -> tuple[list[StoryCandidate], dict]:
    """Extraction is deterministic and cheap, but the artifact is reused when present."""
    items_file = out / "news_items.json"
    if items_file.is_file() and not args.refresh:
        payload = json.loads(items_file.read_text(encoding="utf-8"))
        return [StoryCandidate.from_dict(item) for item in payload["items"]], payload["report"]
    from .pipeline import _editorial_llm

    title, body = read_input(args.input)
    candidates, report = editorial_extractor.extract_candidates(
        body, title, cfg, llm=_editorial_llm(cfg, out))
    _atomic(items_file, {"schema_version": 1, "source_id": report["source_id"],
                         "report": report, "items": [item.to_dict() for item in candidates]})
    return candidates, report


def _build_ratings(args, cfg: dict, out: Path, candidates: list[StoryCandidate]):
    ranking_file = out / "editorial_ranking.json"
    if ranking_file.is_file() and not args.refresh:
        payload = json.loads(ranking_file.read_text(encoding="utf-8"))
        from .editorial.models import StoryRating

        rows = payload["rows"]
        if not all("rating" in row for row in rows):
            raise ValueError(
                f"{ranking_file} predates this version and cannot be reused; re-run with --refresh"
            )
        return [StoryRating.from_dict(row["rating"]) for row in rows]
    from .pipeline import _editorial_llm

    ratings = editorial_ranking.rate_candidates(candidates, cfg, _editorial_llm(cfg, out))
    _atomic(ranking_file, {"schema_version": 1, "weights": cfg["editorial"]["weights"],
                           "rows": editorial_ranking.ranked_table(ratings, candidates)})
    return ratings


def _build_selection(args, cfg: dict, out: Path, candidates, ratings):
    from .pipeline import _editorial_llm

    selection = editorial_selection.select(candidates, ratings, cfg, _editorial_llm(cfg, out))
    _atomic(out / "editorial_selection.json", {"schema_version": 1, **selection.to_dict()})
    return selection


def _build_briefs(args, cfg: dict, out: Path, candidates, selection):
    from .pipeline import _editorial_llm

    llm = _editorial_llm(cfg, out)
    briefs = editorial_insight.build_briefs(list(selection.selected), candidates, cfg, llm)
    report = editorial_insight.claim_report(briefs)
    _atomic(out / "analysis_briefs.json", {"schema_version": 1, "briefs": [b.to_dict() for b in briefs]})
    _atomic(out / "claims.json", {"schema_version": 1, "counts": report["counts"],
                                  "claims": [c.to_dict() for c in editorial_insight.all_claims(briefs)]})
    return briefs, llm


def editorial_main(args) -> int:
    cfg = load_config(args.config)
    cfg["editorial"]["mode"] = "curated-analysis"
    if getattr(args, "top_k", None):
        cfg["editorial"]["top_k"] = int(args.top_k)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    if args.editorial_command == "extract":
        args.refresh = True  # `extract` means extract, never reuse an earlier artifact
    title, _ = read_input(args.input)
    if args.editorial_command == "extract":
        candidates, report = _build_candidates(args, cfg, out)
        print(json.dumps({"stage": "extract", "artifact": str(out / "news_items.json"),
                          "candidates": len(candidates),
                          "aggregate_blocks": report["aggregate_blocks"],
                          "split_briefs": report["split_briefs"],
                          "uncertain_blocks": report["uncertain_blocks"]}, ensure_ascii=False))
        return 0
    candidates, _ = _build_candidates(args, cfg, out)
    ratings = _build_ratings(args, cfg, out, candidates)
    if args.editorial_command == "rank":
        rows = editorial_ranking.ranked_table(ratings, candidates)
        print(json.dumps({"stage": "rank", "artifact": str(out / "editorial_ranking.json"),
                          "ranked": len(rows),
                          "top": [{"rank": row["rank"], "story_id": row["story_id"],
                                   "headline": row["headline"], "total": row["weighted_total"],
                                   "topic": row["topic"], "flags": row["flags"]}
                                  for row in rows[:args.show]]}, ensure_ascii=False))
        return 0
    selection = _build_selection(args, cfg, out, candidates, ratings)
    if args.editorial_command == "select":
        print(json.dumps({"stage": "select", "artifact": str(out / "editorial_selection.json"),
                          "top_k": selection.top_k, "selected": list(selection.selected),
                          "insufficient": selection.insufficient, "notes": list(selection.notes),
                          "rejected": [{"story_id": row["story_id"], "reason": row["reason"], "total": row["total"]}
                                       for row in selection.rejected]},
                         ensure_ascii=False))
        return 0
    if not selection.selected:
        raise ValueError("No story cleared the editorial thresholds; nothing to script")
    briefs, llm = _build_briefs(args, cfg, out, candidates, selection)
    script, critic = editorial_critique.build_script_with_critique(briefs, selection, cfg, llm, candidates)
    editorial_scripting.assert_selection_grounded(script, candidates, selection, cfg)
    (out / "editorial_script.md").write_text(script.markdown(), encoding="utf-8")
    scenes = editorial_scripting.script_to_scenes(script, cfg)
    _atomic(out / "scenes.json", [scene.to_dict() for scene in scenes])
    _atomic(out / "editorial_report.json", {
        "schema_version": 1, "mode": "curated-analysis", "selection": selection.to_dict(),
        "critic": critic, "llm": llm.summary(),
    })
    print(json.dumps({"stage": "script", "artifact": str(out / "editorial_script.md"),
                      "sections": len(script.sections), "scenes": len(scenes),
                      "selected": list(selection.selected), "critique_failed": critic["failed"]},
                     ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="news-video", description="Article/news manuscript → PPTX + TTS + SRT + timeline + MP4")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--input", required=True, type=Path)
        p.add_argument("--config", type=Path)
        p.add_argument("--planner", choices=("heuristic", "openai-compatible"))
        p.add_argument("--tts", choices=("espeak", "edge", "synthetic"))
        p.add_argument("--editorial", choices=("none", "curated-analysis"), default="none",
                       help="none = whole manuscript (default); curated-analysis = AI news chief editor")
        p.add_argument("--top-k", type=int, help="number of stories to select in curated-analysis mode")
        if name == "run":
            p.add_argument("--out", type=Path, default=Path("outputs"))
            p.add_argument("--source-url", default="")
            p.add_argument("--force", action="store_true")
    editorial = sub.add_parser("editorial", help="run a single editorial stage and write its artifact")
    editorial_stage = editorial.add_subparsers(dest="editorial_command", required=True)
    for name in EDITORIAL_STAGES:
        p = editorial_stage.add_parser(name)
        p.add_argument("--input", required=True, type=Path)
        p.add_argument("--config", type=Path)
        p.add_argument("--out", type=Path, default=Path("outputs") / "editorial")
        p.add_argument("--top-k", type=int)
        p.add_argument("--show", type=int, default=10, help="how many ranked rows to print")
        p.add_argument("--refresh", action="store_true", help="ignore the earlier stage artifacts in --out")
    check = sub.add_parser("validate")
    check.add_argument("output", type=Path)
    check.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.command == "validate":
            print(json.dumps(validate_existing(args.output, cfg), ensure_ascii=False, indent=2))
            return 0
        if args.command == "editorial":
            return editorial_main(args)
        if args.planner:
            cfg["planner"]["provider"] = args.planner
        if args.tts:
            cfg["voice"]["provider"] = args.tts
        if args.command == "plan":
            title, body = read_input(args.input)
            if args.editorial == "curated-analysis":
                from .pipeline import build_editorial_assets
                import tempfile

                if args.top_k:
                    cfg["editorial"]["top_k"] = int(args.top_k)
                with tempfile.TemporaryDirectory() as scratch:
                    scenes, curated = build_editorial_assets(title, body, cfg, Path(scratch), Path(scratch))
                print(json.dumps({"title": title, "editorial": curated,
                                  "scenes": [x.to_dict() for x in scenes]}, ensure_ascii=False, indent=2))
                return 0
            scenes = plan(title, body, cfg)
            print(json.dumps({"title": title, "scenes": [x.to_dict() for x in scenes]}, ensure_ascii=False, indent=2))
            return 0
        if cfg["voice"]["provider"] == "synthetic":
            print("WARNING: synthetic provider generates test tones, NOT speech. DO NOT PUBLISH.", file=sys.stderr)
        result = run(args.input, args.out, cfg, force=args.force, source_url=args.source_url,
                     editorial=args.editorial, top_k=args.top_k)
        print(json.dumps({"result": "qa_passed", "directory": str(result), "manifest": str(result / 'manifest.json')}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(f"ERROR {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
