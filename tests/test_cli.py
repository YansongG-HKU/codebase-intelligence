"""End-to-end CLI tests (docs/SPEC.md §3/§11).

These run the real scanner/parser/index/retrieval pipeline against the
``tests/fixtures/cli/demo_repo`` fixture repository and pin the observable
contract: canonical JSON, deterministic bytes, budgets, exit codes and error
envelopes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from codebase_intelligence import cli
from codebase_intelligence.util import canonical_json

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cli" / "demo_repo"


def _call(argv: list[str], capsys: Any) -> tuple[int, str, str]:
    code = cli.run(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _json_call(argv: list[str], capsys: Any) -> dict[str, Any]:
    code, out, err = _call(argv, capsys)
    assert code == 0, f"exit={code} stderr={err}"
    payload = json.loads(out)
    assert canonical_json(payload) + "\n" == out
    return payload


def _cache(tmp_path: Path) -> str:
    return str(tmp_path / "cbi-cache")


# -- basic commands ---------------------------------------------------------
def test_version_json(capsys: Any) -> None:
    payload = _json_call(["version", "--json"], capsys)
    assert payload["ok"] is True
    assert payload["schemaVersion"] == "1"
    assert payload["engineVersion"] == "0.1.0"


def test_doctor_reports_available_modules(capsys: Any) -> None:
    payload = _json_call(["doctor", "--json"], capsys)
    assert payload["ok"] is True
    assert payload["modules"]["scanner"] == "available"
    assert payload["modules"]["retrieval"] == "available"
    assert payload["defaults"]["tokenEstimator"] == "chars4-wide-v1"


def test_version_human_output(capsys: Any) -> None:
    code, out, _ = _call(["version"], capsys)
    assert code == 0
    assert out.startswith("cbi 0.1.0")


# -- index ------------------------------------------------------------------
def test_index_payload_and_deterministic_fingerprint(tmp_path: Path, capsys: Any) -> None:
    cache = _cache(tmp_path)
    first = _json_call(["index", str(FIXTURE), "--json", "--cache-dir", cache], capsys)
    second = _json_call(["index", str(FIXTURE), "--json", "--cache-dir", cache], capsys)
    assert first["repo"]["files"] > 0
    assert first["repo"]["symbols"] > 0
    assert first["repo"]["relations"] > 0
    assert first["index"]["fingerprint"] == second["index"]["fingerprint"]
    assert canonical_json(first) == canonical_json(second)
    assert "diagnostics" not in first  # volatile counters are opt-in only
    diagnostics = _json_call(
        ["index", str(FIXTURE), "--json", "--cache-dir", cache, "--diagnostics"], capsys
    )
    assert diagnostics["diagnostics"]["cache"]["cacheHit"] is True


def test_scan_json_lists_indexable_files(capsys: Any) -> None:
    payload = _json_call(["scan", str(FIXTURE), "--json", "--list-files"], capsys)
    paths = {item["path"] for item in payload["files"]}
    assert "src/demo/core.py" in paths
    assert "web/index.ts" in paths
    # .gitignore'd and build/ artifacts never enter the scan.
    assert "debug.log" not in paths
    assert "build/artifact.py" not in paths


# -- model-facing operations ------------------------------------------------
def test_overview_is_deterministic_budgeted_and_path_free(tmp_path: Path, capsys: Any) -> None:
    cache = _cache(tmp_path)
    first = _json_call(["overview", str(FIXTURE), "--json", "--cache-dir", cache], capsys)
    second = _json_call(["overview", str(FIXTURE), "--json", "--cache-dir", cache], capsys)
    assert canonical_json(first) == canonical_json(second)
    assert first["budgets"]["tokensEstimated"] <= first["budgets"]["maxTokens"]
    assert first["index"]["fingerprint"]
    rendered = canonical_json(first)
    assert str(FIXTURE) not in rendered
    assert "\\" not in rendered  # no Windows absolute paths leak into payloads


def test_map_focus_filters_paths(tmp_path: Path, capsys: Any) -> None:
    payload = _json_call(
        ["map", str(FIXTURE), "--json", "--focus", "src/demo", "--cache-dir", _cache(tmp_path)],
        capsys,
    )
    assert payload["focus"] == "src/demo"
    assert payload["entries"]
    assert all(entry["path"].startswith("src/demo/") for entry in payload["entries"])


def test_search_returns_path_line_evidence(tmp_path: Path, capsys: Any) -> None:
    payload = _json_call(
        ["search", str(FIXTURE), "--query", "clamp", "--json", "--cache-dir", _cache(tmp_path)],
        capsys,
    )
    assert payload["query"] == "clamp"
    assert payload["results"]
    top = payload["results"][0]
    assert top["path"] == "src/demo/util.py"
    assert isinstance(top["line"], int) and top["line"] > 0
    assert top["score"] > 0


def test_dependencies_resolves_src_layout_imports(tmp_path: Path, capsys: Any) -> None:
    payload = _json_call(
        [
            "dependencies",
            str(FIXTURE),
            "--target",
            "src/demo/core.py",
            "--json",
            "--cache-dir",
            _cache(tmp_path),
        ],
        capsys,
    )
    assert payload["target"] == {"path": "src/demo/core.py"}
    resolved = [
        edge
        for edge in payload["edges"]
        if edge["status"] == "resolved" and edge["to"] == "file:src/demo/util.py"
    ]
    assert resolved, "src-layout absolute import should resolve to src/demo/util.py"
    assert resolved[0]["evidence"] == "resolver"


def test_context_respects_small_budget(tmp_path: Path, capsys: Any) -> None:
    payload = _json_call(
        [
            "context",
            str(FIXTURE),
            "--task",
            "add a clamp helper",
            "--max-tokens",
            "400",
            "--json",
            "--cache-dir",
            _cache(tmp_path),
        ],
        capsys,
    )
    assert payload["budgets"]["maxTokens"] == 400
    assert payload["budgets"]["tokensEstimated"] <= 400
    assert payload["items"]
    for item in payload["items"]:
        assert item["path"] and item["startLine"] >= 1
        assert "excerpt" in item


def test_impact_lists_dependents(tmp_path: Path, capsys: Any) -> None:
    payload = _json_call(
        [
            "impact",
            str(FIXTURE),
            "--files",
            "src/demo/core.py",
            "--json",
            "--cache-dir",
            _cache(tmp_path),
        ],
        capsys,
    )
    assert payload["changed"]["files"] == ["src/demo/core.py"]
    paths = {entry["path"] for entry in payload["affectedFiles"]}
    assert "src/demo/sub/helper.py" in paths
    assert all(entry["confidence"] in {"high", "medium", "low"} for entry in payload["affectedFiles"])


def test_impact_rejects_workspace_escaping_paths(tmp_path: Path, capsys: Any) -> None:
    for value in (
        "../outside.py",
        "src/../../outside.py",
        "C:/outside.py",
        "/etc/passwd",
        "~/.ssh/id_rsa",
    ):
        code, out, _ = _call(
            ["impact", str(FIXTURE), "--files", value, "--json", "--cache-dir", _cache(tmp_path)],
            capsys,
        )
        assert code == 2, value
        payload = json.loads(out)
        assert payload["ok"] is False, value
        assert payload["error"]["code"] == "invalid_arguments", value


# -- error contract ---------------------------------------------------------
def test_usage_error_returns_envelope_and_exit_2(capsys: Any) -> None:
    code, out, _ = _call(["impact", str(FIXTURE), "--json"], capsys)
    assert code == 2
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"


def test_missing_repository_returns_envelope_and_exit_3(tmp_path: Path, capsys: Any) -> None:
    missing = tmp_path / "does-not-exist"
    code, out, _ = _call(["overview", str(missing), "--json"], capsys)
    assert code == 3
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_a_directory"


# -- report -----------------------------------------------------------------
def test_report_writes_cited_markdown(tmp_path: Path, capsys: Any) -> None:
    target = tmp_path / "architecture.md"
    code, out, _ = _call(
        ["report", str(FIXTURE), "--out", str(target), "--cache-dir", _cache(tmp_path)],
        capsys,
    )
    assert code == 0
    markdown = target.read_text(encoding="utf-8")
    assert "# Architecture report" in markdown
    assert "src/demo/core.py:" in markdown
    assert str(FIXTURE) not in markdown


# -- cross-process determinism ---------------------------------------------
def test_cross_process_cli_output_is_byte_identical(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    command = [
        sys.executable,
        "-m",
        "codebase_intelligence.cli",
        "overview",
        str(FIXTURE),
        "--json",
        "--cache-dir",
        _cache(tmp_path),
    ]
    first = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
    second = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["ok"] is True


def test_scan_with_unicode_paths_is_utf8_safe_on_non_utf8_console(tmp_path: Path) -> None:
    """A GBK console must not turn valid JSON with CJK paths into a crash."""

    unicode_repo = Path(__file__).resolve().parent / "fixtures" / "scanner" / "unicode-repo"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "gbk"
    command = [
        sys.executable,
        "-m",
        "codebase_intelligence.cli",
        "scan",
        str(unicode_repo),
        "--json",
        "--list-files",
    ]
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, check=True)
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["ok"] is True
    paths = {item["path"] for item in payload["files"]}
    assert any("日本語" in path for path in paths), paths
