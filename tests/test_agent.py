"""Contract tests for the Progenitor entrypoint (github_update.agent).

The worker pool is monkeypatched so no Claude session, git, or network is
needed: these tests exercise the input.json/output.json contract only.
"""

from __future__ import annotations

import json

import pytest

from github_update import agent
from github_update.worker import RepoResult


@pytest.fixture
def contract_paths(tmp_path, monkeypatch):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    monkeypatch.setenv("AGENT_INPUT_PATH", str(input_path))
    monkeypatch.setenv("AGENT_OUTPUT_PATH", str(output_path))
    return input_path, output_path


def _fake_run_all(results):
    async def run_all(config):
        return results

    return run_all


def test_successful_run_writes_output(contract_paths, monkeypatch, capsys):
    input_path, output_path = contract_paths
    input_path.write_text(
        json.dumps({"repos": ["octo/repo"], "settings": {"dry_run": True}})
    )
    results = [
        RepoResult(repo="octo/repo", status="success", cost_usd=0.5,
                   pr_url="https://github.com/octo/repo/pull/1")
    ]
    monkeypatch.setattr(agent, "run_all", _fake_run_all(results))
    monkeypatch.setattr(agent.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    assert agent.main() == 0

    output = json.loads(output_path.read_text())
    assert output["succeeded"] == 1
    assert output["failed"] == 0
    assert output["total_cost_usd"] == 0.5
    assert output["pull_requests"] == ["https://github.com/octo/repo/pull/1"]
    assert output["repos"][0]["repo"] == "octo/repo"

    events = [
        json.loads(line.removeprefix("::agent-event::"))
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("::agent-event::")
    ]
    steps = [(e["type"], e["step"]) for e in events]
    assert steps == [
        ("step.started", "prepare"), ("step.completed", "prepare"),
        ("step.started", "update"), ("step.completed", "update"),
        ("step.started", "report"), ("step.completed", "report"),
    ]


def test_all_repos_failed_exits_nonzero_but_still_reports(
    contract_paths, monkeypatch
):
    input_path, output_path = contract_paths
    input_path.write_text(json.dumps({"repos": ["octo/repo"]}))
    results = [RepoResult(repo="octo/repo", status="error", error="clone: boom")]
    monkeypatch.setattr(agent, "run_all", _fake_run_all(results))
    monkeypatch.setattr(agent.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    assert agent.main() == 1

    output = json.loads(output_path.read_text())
    assert output["failed"] == 1
    assert output["repos"][0]["error"] == "clone: boom"


@pytest.mark.parametrize(
    "payload",
    [
        "[]",                                        # not an object
        "{}",                                        # repos missing
        json.dumps({"repos": "octo/repo"}),          # repos not a list
        json.dumps({"repos": []}),                   # repos empty
        json.dumps({"repos": ["octo/repo"], "settings": {"bogus": 1}}),
        "not json",
    ],
)
def test_invalid_input_fails_prepare_step(contract_paths, payload, capsys):
    input_path, output_path = contract_paths
    input_path.write_text(payload)

    assert agent.main() == 1
    assert not output_path.exists()
    events = [
        json.loads(line.removeprefix("::agent-event::"))
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("::agent-event::")
    ]
    assert events[-1]["type"] == "step.failed"
    assert events[-1]["step"] == "prepare"


def test_missing_tools_fail_prepare_step(contract_paths, monkeypatch):
    input_path, output_path = contract_paths
    input_path.write_text(json.dumps({"repos": ["octo/repo"]}))
    monkeypatch.setattr(agent.shutil, "which", lambda tool: None)

    assert agent.main() == 1
    assert not output_path.exists()


def test_settings_are_applied(contract_paths, monkeypatch):
    input_path, _ = contract_paths
    input_path.write_text(
        json.dumps({"repos": ["octo/repo"], "settings": {"concurrency": 7}})
    )
    seen = {}

    async def run_all(config):
        seen["concurrency"] = config.settings.concurrency
        return [RepoResult(repo="octo/repo", status="success")]

    monkeypatch.setattr(agent, "run_all", run_all)
    monkeypatch.setattr(agent.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    assert agent.main() == 0
    assert seen["concurrency"] == 7
