"""Deterministic unit tests for github-update's pure logic.

The agent-driven worker itself is exercised end-to-end with `--dry-run`
against a real repo; these tests cover the parsing/config/summary logic that
must stay correct regardless of what the agent does.
"""

from pathlib import Path

import pytest

from github_update.config import Config, Settings, load_config
from github_update.orchestrator import summarise
from github_update.worker import RepoResult, _extract_pr_url, _parse_report, _slug


# --- repo slug -------------------------------------------------------------

@pytest.mark.parametrize("repo,expected", [
    ("allistera/Cookie-Web", "allistera__Cookie-Web"),
    ("https://github.com/allistera/foo.git", "github.com__allistera__foo"),
    ("git@github.com:allistera/bar.git", "allistera__bar"),
    ("allistera/baz/", "allistera__baz"),
])
def test_slug(repo, expected):
    assert _slug(repo) == expected


# --- report parsing --------------------------------------------------------

def test_parse_report_extracts_known_keys():
    text = """
    Some preamble the agent wrote.
    STATUS: success
    ECOSYSTEMS: npm
    DEPENDABOT_ALERTS_FIXED: 2
    PULL_REQUEST: https://github.com/allistera/foo/pull/9
    NOTES: none
    IGNORED_KEY: should not appear
    """
    report = _parse_report(text)
    assert report["STATUS"] == "success"
    assert report["DEPENDABOT_ALERTS_FIXED"] == "2"
    assert report["PULL_REQUEST"].endswith("/pull/9")
    assert "IGNORED_KEY" not in report


def test_parse_report_empty_when_no_report():
    assert _parse_report("just some chatter, no report") == {}


# --- PR-URL detection (regression: "none (dry run)" is NOT a PR) -----------

@pytest.mark.parametrize("value,expected", [
    ("none (dry run)", None),
    ("none", None),
    ("", None),
    ("https://github.com/allistera/foo/pull/9", "https://github.com/allistera/foo/pull/9"),
])
def test_pr_url_detection(value, expected):
    # Exercises the real worker helper, not a copy of its logic.
    assert _extract_pr_url({"PULL_REQUEST": value}) == expected


def test_pr_url_detection_missing_key():
    assert _extract_pr_url({}) is None


# --- summary rendering -----------------------------------------------------

def test_summary_lists_only_real_prs():
    dry = RepoResult(repo="a/dry", status="success", cost_usd=0.5)
    dry.report = {"PULL_REQUEST": "none (dry run)"}
    dry.pr_url = _extract_pr_url(dry.report)
    real = RepoResult(repo="a/real", status="success", cost_usd=1.0)
    real.report = {
        "DEPENDENCIES_UPDATED": "12 packages",
        "DEPENDABOT_ALERTS_FIXED": "2",
        "PULL_REQUEST": "https://github.com/a/real/pull/3",
    }
    real.pr_url = _extract_pr_url(real.report)

    out = summarise([dry, real])
    # Only the repo with a real PR is tabulated.
    assert "https://github.com/a/real/pull/3" in out
    assert "a/dry" not in out
    # Header and both affirmative flags rendered.
    assert "Repository" in out and "Package Update" in out and "Security Fix" in out
    assert "✓" in out
    assert "1 pull request(s)" in out
    assert "total cost: $1.50" in out


def test_summary_no_prs_is_clean():
    r = RepoResult(repo="a/none", status="success", cost_usd=0.25)
    r.report = {"PULL_REQUEST": "none"}
    out = summarise([r])
    assert "No pull requests were opened." in out
    assert "0 pull request(s)" in out


def test_summary_flags_absent_when_no_work():
    r = RepoResult(repo="a/real", status="success", cost_usd=1.0)
    r.report = {
        "DEPENDENCIES_UPDATED": "none",
        "DEPENDABOT_ALERTS_FIXED": "0",
        "PULL_REQUEST": "https://github.com/a/real/pull/1",
    }
    r.pr_url = _extract_pr_url(r.report)
    out = summarise([r])
    # PR present but neither flag set -> no checkmark anywhere.
    assert "https://github.com/a/real/pull/1" in out
    assert "✓" not in out


# --- config loading --------------------------------------------------------

def test_load_config_example():
    example = Path(__file__).resolve().parent.parent / "config.example.yaml"
    cfg = load_config(example)
    assert cfg.repos[0] == "allistera/Cookie-Web"
    assert cfg.settings.concurrency == 3
    assert cfg.settings.open_pr is True


def test_load_config_rejects_unknown_setting(tmp_path):
    bad = tmp_path / "c.yaml"
    bad.write_text("repos: [a/b]\nsettings:\n  bogus: 1\n")
    with pytest.raises(ValueError, match="Unknown settings"):
        load_config(bad)


def test_config_normalises_dict_repo_entries(tmp_path):
    c = tmp_path / "c.yaml"
    c.write_text("repos:\n  - repo: a/b\n  - c/d\n")
    cfg = load_config(c)
    assert cfg.repos == ["a/b", "c/d"]
