"""Blind selection-quality evaluation checks, no synthetic claimed results."""
import importlib.util
import json
from pathlib import Path
import pytest

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("editorial_evaluate", root / "scripts/editorial_evaluate.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


@pytest.fixture
def sample(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "source.txt").write_text("四条示例新闻。", encoding="utf-8")
    (d / "news_items.json").write_text(json.dumps({"items": [
        {"story_id": f"s{i}", "headline": f"headline{i}"} for i in range(1, 5)]}))
    (d / "editorial_ranking.json").write_text(json.dumps({"rows": [
        {"story_id": f"s{i}", "rank": i} for i in range(1, 5)]}))
    (d / "editorial_selection.json").write_text(json.dumps({"top_k": 2, "selected": ["s1", "s3"]}))
    return ev.case_from_run(d)


def label(sample, annotator, positives, grades):
    obj = ev.blank_template(sample)
    obj["annotator_id"] = annotator
    for entry in obj["labels"]:
        sid = entry["story_id"]
        entry.update(relevance=grades[sid], should_select=sid in positives,
                     must_include=sid == "s1", reason="independent judgement")
    return obj


def test_template_is_blind_and_unlabelled(sample):
    t = ev.blank_template(sample)
    assert t["annotator_id"] == ""
    assert "selected" not in t
    assert all(r["should_select"] is None for r in t["labels"])


def test_incomplete_or_foreign_labels_are_rejected(sample, tmp_path):
    file = tmp_path / "labels.json"
    file.write_text(json.dumps(ev.blank_template(sample)))
    with pytest.raises(ValueError, match="annotator_id"):
        ev.load_labels(file, sample)
    data = label(sample, "A", {"s1"}, {s: 2 for s in sample["ids"]})
    data["source_hash"] = "wrong"
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hashes do not match"):
        ev.load_labels(file, sample)


def test_two_independent_annotators_and_metrics(sample, tmp_path):
    a = label(sample, "A", {"s1", "s2"}, {"s1": 3, "s2": 2, "s3": 1, "s4": 0})
    b = label(sample, "B", {"s1", "s3"}, {"s1": 3, "s2": 0, "s3": 2, "s4": 0})
    judges = []
    for i, data in enumerate((a, b)):
        path = tmp_path / f"{i}.json"
        path.write_text(json.dumps(data))
        judges.append(ev.load_labels(path, sample))
    result = ev.evaluate(sample, judges)
    assert result["annotators"][0]["precision_at_k"] == 0.5
    assert result["annotators"][1]["precision_at_k"] == 1.0
    assert result["annotators"][0]["ndcg_at_k"] == 1.0
    assert result["annotators"][1]["ndcg_at_k"] < 1.0
    assert result["agreement"]["disagreement_story_ids"] == ["s2", "s3"]
    assert result["agreement"]["cohen_kappa"] == 0.0


def test_kappa_perfect_agreement_and_undefined_ndcg(sample):
    zero = {s: 0 for s in sample["ids"]}
    assert ev.ndcg_at_k(sample["rank_ids"], zero, 2) is None
    a = {s: {"should_select": False} for s in sample["ids"]}
    assert ev.cohen_kappa(a, a, sample["ids"]) == 1.0


def test_same_annotator_rejected(sample):
    with pytest.raises(ValueError, match="independent"):
        ev.evaluate(sample, [{"id": "same"}, {"id": "same"}])


def test_template_cli_refuses_overwrite(sample, tmp_path):
    dest = tmp_path / "person-a.json"
    assert ev.main(["template", "--run-dir", str(tmp_path / "run"), "--out", str(dest)]) == 0
    with pytest.raises(FileExistsError, match="overwrite"):
        ev.main(["template", "--run-dir", str(tmp_path / "run"), "--out", str(dest)])
