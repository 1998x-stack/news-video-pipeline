"""Regression tests for the cross-platform news skill catalog."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install_agents.py"
VALIDATOR = ROOT / "scripts/validate_skills.py"

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
