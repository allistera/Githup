"""Tests for repo-list loading, including `owner/*` glob expansion."""

from __future__ import annotations

import json
import subprocess

import pytest

from github_update import config as config_module
from github_update.config import expand_repos, load_config


def _fake_run(stdout: str = "", returncode: int = 0, stderr: str = ""):
    def run(cmd, **kwargs):
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, cmd, stdout, stderr)
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    return run


def test_expand_repos_passes_through_plain_entries(monkeypatch):
    def run(cmd, **kwargs):
        raise AssertionError("gh should not be invoked for non-glob entries")

    monkeypatch.setattr(config_module.subprocess, "run", run)
    assert expand_repos(["octo/repo", "https://github.com/octo/other.git"]) == [
        "octo/repo",
        "https://github.com/octo/other.git",
    ]


def test_expand_repos_expands_owner_glob(monkeypatch):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        payload = [{"nameWithOwner": "octo/a"}, {"nameWithOwner": "octo/b"}]
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(config_module.subprocess, "run", run)
    assert expand_repos(["octo/*"]) == ["octo/a", "octo/b"]
    assert calls[0][:4] == ["gh", "repo", "list", "octo"]


def test_expand_repos_dedupes_across_glob_and_explicit(monkeypatch):
    def run(cmd, **kwargs):
        payload = [{"nameWithOwner": "octo/a"}, {"nameWithOwner": "octo/b"}]
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(config_module.subprocess, "run", run)
    assert expand_repos(["octo/a", "octo/*"]) == ["octo/a", "octo/b"]


def test_expand_repos_raises_on_gh_failure(monkeypatch):
    monkeypatch.setattr(
        config_module.subprocess, "run", _fake_run(returncode=1, stderr="not found")
    )
    with pytest.raises(RuntimeError, match="failed to list repos"):
        expand_repos(["octo/*"])


def test_expand_repos_raises_when_gh_missing(monkeypatch):
    def run(cmd, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(config_module.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="'gh' is required"):
        expand_repos(["octo/*"])


def test_load_config_expands_owner_glob(tmp_path, monkeypatch):
    def run(cmd, **kwargs):
        payload = [{"nameWithOwner": "octo/a"}, {"nameWithOwner": "octo/b"}]
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(config_module.subprocess, "run", run)

    config_path = tmp_path / "config.yaml"
    config_path.write_text("repos:\n  - octo/*\n")

    config = load_config(config_path)
    assert config.repos == ["octo/a", "octo/b"]
