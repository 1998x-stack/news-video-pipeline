#!/usr/bin/env python3
"""Blind human-label evaluation. No complete labels, no claimed metrics."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def read(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"{path}: JSON object required")
    return result


def case_from_run(root: Path) -> dict:
    source = root / "source.txt"
    items = root / "news_items.json"
    candidates = read(items)["items"]
    rank = sorted(read(root / "editorial_ranking.json")["rows"], key=lambda r: r["rank"])
    selection = read(root / "editorial_selection.json")
    ids = [s["story_id"] for s in candidates]
    rank_ids = [r["story_id"] for r in rank]
    picks = selection["selected"]
    k = int(selection["top_k"])
    if not ids or len(ids) != len(set(ids)) or len(rank_ids) != len(set(rank_ids)) or set(ids) != set(rank_ids):
        raise ValueError("Ranking and candidate IDs must be unique and identical")
    if len(picks) != len(set(picks)) or not 1 <= len(picks) <= k or not set(picks) <= set(ids):
        raise ValueError("Invalid final selection")
    return {"ids": ids, "candidates": candidates, "rank_ids": rank_ids, "picks": picks, "k": k,
            "source_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
            "items_hash": hashlib.sha256(items.read_bytes()).hexdigest()}


def blank_template(case: dict) -> dict:
    """Do not show human annotators model scores, ranks, or selected IDs."""
    return {"schema_version": 1, "annotator_id": "", "source_hash": case["source_hash"],
            "items_hash": case["items_hash"],
            "labels": [{"story_id": item["story_id"], "headline": item["headline"],
                        "relevance": None, "should_select": None,
                        "must_include": None, "reason": ""}
                       for item in case["candidates"]]}


def load_labels(path: Path, case: dict) -> dict:
    obj = read(path)
    person = obj.get("annotator_id")
    if obj.get("schema_version") != 1 or not isinstance(person, str) or not person.strip():
        raise ValueError(f"{path}: schema_version 1 and annotator_id required")
    if obj.get("source_hash") != case["source_hash"] or obj.get("items_hash") != case["items_hash"]:
        raise ValueError(f"{path}: source/candidate hashes do not match")
    rows = obj.get("labels")
    if not isinstance(rows, list) or len(rows) != len(case["ids"]):
        raise ValueError(f"{path}: incomplete human labels")
    labels: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("story_id") not in case["ids"]:
            raise ValueError(f"{path}: unknown story id")
        sid = row["story_id"]
        if sid in labels:
            raise ValueError(f"{path}: duplicate story id {sid}")
        rel = row.get("relevance")
        if isinstance(rel, bool) or not isinstance(rel, int) or not 0 <= rel <= 3:
            raise ValueError(f"{path}: {sid} relevance must be integer 0..3")
        for key in ("should_select", "must_include"):
            if not isinstance(row.get(key), bool):
                raise ValueError(f"{path}: {sid}.{key} must be boolean")
        if row["must_include"] and not row["should_select"]:
            raise ValueError(f"{path}: {sid} must_include implies should_select")
        labels[sid] = row
    if set(labels) != set(case["ids"]):
        raise ValueError(f"{path}: missing story ids")
    return {"id": person.strip(), "labels": labels}


def ndcg_at_k(ranking: list[str], grades: dict[str, int], k: int) -> float | None:
    def gain(values):
        return sum((2**v - 1) / math.log2(i + 2) for i, v in enumerate(values))
    ideal = gain(sorted(grades.values(), reverse=True)[:k])
    return round(gain([grades[s] for s in ranking[:k]]) / ideal, 6) if ideal else None


def cohen_kappa(a: dict, b: dict, ids: list[str]) -> float | None:
    n = len(ids)
    observed = sum(a[s]["should_select"] == b[s]["should_select"] for s in ids) / n
    pa = sum(a[s]["should_select"] for s in ids) / n
    pb = sum(b[s]["should_select"] for s in ids) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return round((observed - expected) / (1 - expected), 6) if expected < 1 else (1.0 if observed == 1 else None)


def evaluate(case: dict, judges: list[dict]) -> dict:
    if len(judges) != 2 or judges[0]["id"] == judges[1]["id"]:
        raise ValueError("Exactly two independent annotators are required")
    out = []
    for judge in judges:
        labels = judge["labels"]
        mandatory = {s for s in case["ids"] if labels[s]["must_include"]}
        out.append({"annotator_id": judge["id"],
                    "precision_at_k": round(sum(labels[s]["should_select"] for s in case["picks"]) / case["k"], 6),
                    "ndcg_at_k": ndcg_at_k(case["rank_ids"], {s: labels[s]["relevance"] for s in case["ids"]}, case["k"]),
                    "must_include_recall": (round(len(mandatory & set(case["picks"])) / len(mandatory), 6)
                                            if mandatory else None)})
    a, b = [j["labels"] for j in judges]
    disagreements = [s for s in case["ids"] if a[s]["should_select"] != b[s]["should_select"]]
    union = {s for s in case["ids"] if a[s]["should_select"] or b[s]["should_select"]}
    intersection = {s for s in case["ids"] if a[s]["should_select"] and b[s]["should_select"]}
    return {"schema_version": 1, "source_hash": case["source_hash"], "candidates": len(case["ids"]),
            "top_k": case["k"], "selected": case["picks"], "annotators": out,
            "agreement": {"binary_agreement": round(1 - len(disagreements)/len(case["ids"]), 6),
                          "cohen_kappa": cohen_kappa(a, b, case["ids"]),
                          "selection_jaccard": round(len(intersection)/len(union), 6) if union else None,
                          "disagreement_story_ids": disagreements},
            "note": "Human selection labels are not fact verification, rights clearance or publication approval"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for action in ("template", "evaluate"):
        tool = sub.add_parser(action)
        tool.add_argument("--run-dir", type=Path, required=True)
        tool.add_argument("--out", type=Path, required=True)
        if action == "evaluate":
            tool.add_argument("--labels", type=Path, nargs=2, required=True)
    args = p.parse_args(argv)
    case = case_from_run(args.run_dir)
    if args.cmd == "template":
        if args.out.exists():
            raise FileExistsError("Refusing to overwrite existing human labels")
        result = blank_template(case)
    else:
        result = evaluate(case, [load_labels(path, case) for path in args.labels])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"action": args.cmd, "output": str(args.out), "candidate_count": len(case["ids"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
