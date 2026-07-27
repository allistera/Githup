"""Configuration loading for Githup.

A run is described by a YAML file (see ``config.example.yaml``). Anything not
set there falls back to the defaults below, and a handful of settings can be
overridden on the command line.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Settings:
    """Run-wide settings shared by every worker."""

    # How many repos to process at the same time. Each unit of concurrency is a
    # separate Claude Agent SDK session (its own `claude` subprocess), so this is
    # the "number of workers" that run in parallel.
    concurrency: int = 3

    # Where repos get cloned. One subdirectory per repo. Kept out of the way of
    # any working copies you already have.
    work_dir: str = "work_repos"

    # The model each worker uses. `None` lets the SDK/CLI pick its default.
    model: str | None = None

    # Branch to base the work on. `None` uses the repo's default branch.
    base_branch: str | None = None

    # Name of the branch each worker creates its changes on.
    work_branch: str = "chore/dependency-updates"

    # When true, open a pull request at the end of a successful run. When false,
    # the worker still commits to the work branch locally but pushes nothing.
    open_pr: bool = True

    # After opening a PR, wait for its CI checks and fix failures until they
    # pass (or the worker runs out of budget). When false, the PR is opened and
    # left as-is without waiting on checks. Only relevant when open_pr is true.
    checks_pass: bool = True

    # When true, workers analyse and report but make no changes, no commits, no
    # pushes, and no PRs. Use this for a first, read-only pass.
    dry_run: bool = False

    # Safety cap per worker so a stuck repo can't run forever.
    max_turns: int = 60

    # Per-worker spend ceiling in USD. `None` disables the cap.
    max_budget_usd: float | None = 2.0

    # Freshen an existing clone instead of re-cloning when the directory exists.
    reuse_clones: bool = True

    # Delete every repo's clone once the whole run has finished. Only the clone
    # directories this run manages are removed, plus the work dir if it ends up
    # empty. Off by default so clones can be inspected/reused; enable per-run.
    cleanup: bool = False

    # Stream a detailed play-by-play of what each worker is doing: every tool
    # call (with its key argument), the agent's narration, and a per-repo
    # start/finish line. Off by default to keep the output clean.
    verbose: bool = False


@dataclass
class Config:
    repos: list[str] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    @property
    def work_dir_path(self) -> Path:
        return Path(self.settings.work_dir).expanduser().resolve()


def _normalise_repo(entry: Any) -> str:
    """Accept ``owner/name``, a full URL, or a mapping with a ``repo`` key."""
    if isinstance(entry, dict):
        entry = entry.get("repo") or entry.get("name") or entry.get("url")
    if not isinstance(entry, str) or not entry.strip():
        raise ValueError(f"Invalid repo entry: {entry!r}")
    return entry.strip()


def load_config(path: str | os.PathLike[str]) -> Config:
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")  # noqa: TRY004

    repos = [_normalise_repo(r) for r in (raw.get("repos") or [])]

    known = {f.name for f in fields(Settings)}
    raw_settings = raw.get("settings") or {}
    unknown = set(raw_settings) - known
    if unknown:
        raise ValueError(f"Unknown settings keys: {', '.join(sorted(unknown))}")
    settings = Settings(**{k: v for k, v in raw_settings.items() if k in known})

    return Config(repos=repos, settings=settings)
