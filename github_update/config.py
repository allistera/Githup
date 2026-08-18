"""Configuration loading for github-update.

A run is described by a YAML file (see ``config.example.yaml``). Anything not
set there falls back to the defaults below, and a handful of settings can be
overridden on the command line.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

_OWNER_GLOB_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*)/\*$")


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

    # When true, workers analyse and report but make no changes, no commits, no
    # pushes, and no PRs. Use this for a first, read-only pass.
    dry_run: bool = False

    # Safety cap per worker so a stuck repo can't run forever.
    max_turns: int = 60

    # Per-worker spend ceiling in USD. `None` disables the cap.
    max_budget_usd: float | None = 2.0

    # Freshen an existing clone instead of re-cloning when the directory exists.
    reuse_clones: bool = True


@dataclass
class Config:
    repos: list[str] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    @property
    def work_dir_path(self) -> Path:
        # Resolve relative work dirs under the system temp dir, not the CWD: on
        # the agent platform the image filesystem is read-only and /tmp is the
        # only writable path, and locally this keeps clones out of the checkout.
        work_dir = Path(self.settings.work_dir).expanduser()
        if not work_dir.is_absolute():
            work_dir = Path(tempfile.gettempdir()) / work_dir
        return work_dir.resolve()


def _normalise_repo(entry: Any) -> str:
    """Accept ``owner/name``, a full URL, or a mapping with a ``repo`` key."""
    if isinstance(entry, dict):
        entry = entry.get("repo") or entry.get("name") or entry.get("url")
    if not isinstance(entry, str) or not entry.strip():
        raise ValueError(f"Invalid repo entry: {entry!r}")
    return entry.strip()


def _list_owner_repos(owner: str) -> list[str]:
    """All non-fork, non-archived repos owned by ``owner``, via ``gh``."""
    try:
        proc = subprocess.run(
            [
                "gh", "repo", "list", owner,
                "--source", "--no-archived",
                "--json", "nameWithOwner",
                "--limit", "1000",
            ],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "'gh' is required to expand an 'owner/*' repo entry"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"failed to list repos for '{owner}': {exc.stderr.strip() or exc}"
        ) from exc
    try:
        entries = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"unexpected 'gh repo list' output for '{owner}'"
        ) from exc
    return [e["nameWithOwner"] for e in entries]


def expand_repos(repos: list[str]) -> list[str]:
    """Expand any ``owner/*`` entries into individual ``owner/name`` repos.

    Everything else passes through unchanged. Duplicates (e.g. an explicit
    repo also covered by a glob) are dropped, keeping first-seen order.
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for entry in repos:
        match = _OWNER_GLOB_RE.match(entry)
        names = _list_owner_repos(match.group(1)) if match else [entry]
        for name in names:
            if name not in seen:
                seen.add(name)
                expanded.append(name)
    return expanded


def load_config(path: str | os.PathLike[str]) -> Config:
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise TypeError("Config root must be a mapping")

    repos = expand_repos([_normalise_repo(r) for r in (raw.get("repos") or [])])

    known = {f.name for f in fields(Settings)}
    raw_settings = raw.get("settings") or {}
    unknown = set(raw_settings) - known
    if unknown:
        raise ValueError(f"Unknown settings keys: {', '.join(sorted(unknown))}")
    settings = Settings(**{k: v for k, v in raw_settings.items() if k in known})

    return Config(repos=repos, settings=settings)
