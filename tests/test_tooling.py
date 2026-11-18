"""The reproducible verification tooling must itself be verifiable and secret-free."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                          cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=300)


def test_environment_report_is_valid_json_and_redacted():
    result = run("check_environment.py")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["python"] and report["requirements"]["python>=3.10"] is True
    assert set(report["credentials"].values()) <= {"set", "unset"}
    assert report["credentials_redacted"] is True
    for name in ("OPENAI_API_KEY", "IAUTO_API_KEY"):
        secret = os.getenv(name)
        if secret:
            assert secret not in result.stdout, f"{name} value leaked into the report"
    assert "configs" in report and report["configs"]


def test_environment_report_writes_file(tmp_path):
    target = tmp_path / "env.json"
    assert run("check_environment.py", "--out", target).returncode == 0
    assert json.loads(target.read_text(encoding="utf-8"))["os"]


def test_environment_strict_mode_flags_missing_hard_requirement(monkeypatch, tmp_path):
    """Without ffmpeg the strict check must fail loudly instead of passing quietly."""
    stripped = tmp_path / "bin"
    stripped.mkdir()
    for name in ("python3", "git"):
        source = shutil.which(name)
        if source:
            (stripped / name).symlink_to(source)
    env = {**ENV, "PATH": str(stripped)}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/check_environment.py"), "--strict"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 1
    assert "MISSING hard requirements" in result.stderr
    assert json.loads(result.stdout)["requirements"]["ffmpeg"] is False


def test_smoke_static_tier_passes():
    result = run("smoke_test.py", "--tier", "static")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.split("\nsummary:", 1)[1].split("\n", 1)[1])
    assert report["summary"]["failed"] == 0
    assert report["summary"]["passed"] >= 3


def test_smoke_offline_tier_passes_and_reports_hashes(tmp_path):
    report_path = tmp_path / "smoke.json"
    result = run("smoke_test.py", "--tier", "all-offline", "--report", report_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "summary:" in result.stdout
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["failed"] == 0
    checks = {entry["check"]: entry for entry in report["checks"]}
    assert checks["heuristic_plan"]["status"] == "passed"
    assert checks["input_rejection"]["status"] == "passed"
    assert report["environment"]["credentials"]["OPENAI_API_KEY"] in {"set", "unset"}


def test_smoke_paid_tiers_are_opt_in(tmp_path):
    """A tier that needs a paid API must be skipped, never silently attempted."""
    env = {k: v for k, v in ENV.items() if k not in {"OPENAI_API_KEY", "OPENAI_MODEL"}}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/smoke_test.py"), "--tier", "llm"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "[skipped]" in result.stdout


def test_smoke_rejects_unknown_tier():
    assert run("smoke_test.py", "--tier", "publish-everything").returncode == 2
