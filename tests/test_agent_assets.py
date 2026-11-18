"""Regression tests for the cross-platform news skill catalog."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_agents.py"
VALIDATOR = ROOT / "scripts/validate_skills.py"
sys.path.insert(0, str(ROOT / "scripts"))
import validate_skills  # noqa: E402  (script module, imported by path)


def test_skill_documents_only_reference_existing_resources():
    """Every backticked repo path in a Skill/adapter must resolve."""
    for folder in sorted(p for p in (ROOT / "skills").iterdir() if p.is_dir()):
        text = (folder / "SKILL.md").read_text(encoding="utf-8")
        assert not validate_skills.missing_resources([(folder.name, text, folder)])


def test_reference_extraction_ignores_artifacts_and_placeholders():
    text = "check `qa_report.json` then `references/source-provenance.md` and `skills/<id>/SKILL.md`"
    assert validate_skills.referenced_resources(text) == ["references/source-provenance.md"]


def test_reference_check_detects_a_dangling_path(tmp_path):
    text = "read `references/missing-playbook.md`"
    assert validate_skills.missing_resources([("fake", text, tmp_path)]) == [
        "fake: references/missing-playbook.md"]


def test_validator_fails_when_a_promised_resource_disappears():
    """The catalog gate must fail, not warn, when a referenced resource is gone."""
    folder = ROOT / "skills/news-quality-gate"
    victim = folder / "references/qa-matrix.md"
    backup = victim.read_bytes()
    try:
        victim.unlink()
        with pytest.raises(ValueError):
            validate_skills.validate()
        assert validate_skills.missing_resources(
            [("news-quality-gate", (folder / "SKILL.md").read_text(encoding="utf-8"), folder)]
        ) == ["news-quality-gate: references/qa-matrix.md"]
    finally:
        victim.write_bytes(backup)
    assert validate_skills.validate()["status"] == "passed"

def call(*args, env=None):
    return subprocess.run([sys.executable, str(INSTALLER), *map(str, args)],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)

def test_catalog_valid():
    r = subprocess.run([sys.executable, str(VALIDATOR)], cwd=ROOT,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "'skills': 9" in r.stdout and "'agents': 5" in r.stdout

def test_pi_install_is_idempotent(tmp_path):
    for _ in range(2):
        r = call("--platform", "pi", "--target", tmp_path)
        assert r.returncode == 0, r.stderr
    root = tmp_path / ".pi/skills/news-input-governance"
    assert (root / "SKILL.md").is_file()
    assert (root / "references/source-provenance.md").is_file()
    assert (root / "assets/review-checklist.json").is_file()
    assert (root / "scripts/audit_input.py").is_file()
    assert (tmp_path / ".pi/prompts/news-producer.md").is_file()

def test_all_platforms_reuse_shared_skill_discovery(tmp_path):
    r = call("--platform", "all", "--target", tmp_path)
    assert r.returncode == 0, r.stderr
    for p in (".agents/skills/news-voice-production/SKILL.md",
              ".claude/skills/news-visual-slides/SKILL.md",
              ".codex/agents/news-producer.toml",
              ".claude/agents/news-producer.md",
              ".opencode/agents/news-producer.md",
              ".pi/prompts/news-producer.md"):
        assert (tmp_path / p).is_file(), p
    assert not (tmp_path / ".pi/skills/news-input-governance/SKILL.md").exists()
    assert not (tmp_path / ".opencode/skills/news-input-governance/SKILL.md").exists()

def test_conflicting_file_not_overwritten_without_force(tmp_path):
    assert call("--platform", "pi", "--target", tmp_path).returncode == 0
    path = tmp_path / ".pi/skills/news-input-governance/SKILL.md"
    path.write_text("custom edits", encoding="utf-8")
    assert call("--platform", "pi", "--target", tmp_path).returncode == 2
    assert path.read_text(encoding="utf-8") == "custom edits"
    r = call("--platform", "pi", "--target", tmp_path, "--force")
    assert r.returncode == 0, r.stderr
    assert path.read_text(encoding="utf-8").startswith("---\nname: news-input-governance")

def test_dry_run_no_files(tmp_path):
    target = tmp_path / "new-project"
    r = call("--platform", "codex", "--target", target, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert not target.exists()

def test_user_scope(tmp_path):
    r = call("--platform", "pi", "--scope", "user", env={**os.environ, "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    assert (tmp_path / ".pi/agent/skills/news-scene-planning/SKILL.md").is_file()
    assert (tmp_path / ".pi/agent/prompts/news-producer.md").is_file()

def test_symlink_destination_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "project"
    root.mkdir()
    (root / ".pi").symlink_to(outside, target_is_directory=True)
    assert call("--platform", "pi", "--target", root).returncode == 2
    assert not list(outside.iterdir())

def test_stage_scripts_and_manual_release_gate(tmp_path):
    manuscript = tmp_path / "news.json"
    manuscript.write_text(json.dumps({"title": "示例", "body": "这是一条新闻。"}), encoding="utf-8")
    script = ROOT / "skills/news-input-governance/scripts/audit_input.py"
    r = subprocess.run([sys.executable, str(script), str(manuscript)],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["public_release_approved"] is False
    (tmp_path / "manifest.json").write_text(json.dumps({
        "run_id": "sample", "status": "qa_passed",
        "rights_status": "unverified", "public_release_approved": False
    }), encoding="utf-8")
    gate = ROOT / "skills/news-release-review/scripts/release_check.py"
    r = subprocess.run([sys.executable, str(gate), str(tmp_path)],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 2
    assert "No publishing/authorization performed" in r.stdout


def test_forged_approval_flag_does_not_bypass_release_gate(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({
        "run_id": "forged", "status": "qa_passed",
        "rights_status": "verified", "public_release_approved": True
    }), encoding="utf-8")
    gate = ROOT / "skills/news-release-review/scripts/release_check.py"
    r = subprocess.run([sys.executable, str(gate), str(tmp_path)],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 2
    assert "No publishing/authorization performed" in r.stdout
