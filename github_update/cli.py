"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys

from .config import Config, Settings, load_config
from .orchestrator import run_all, summarise


def _check_prerequisites() -> list[str]:
    problems: list[str] = []
    for tool in ("git", "gh", "claude"):
        if shutil.which(tool) is None:
            problems.append(f"required tool not found on PATH: {tool}")
    return problems


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="github-update",
        description="Spin up Claude Agent SDK workers to update dependencies and "
        "fix Dependabot alerts across your GitHub repositories.",
    )
    p.add_argument("-c", "--config", default="config.yaml",
                   help="Path to the YAML config file (default: config.yaml).")
    p.add_argument("-r", "--repo", action="append", dest="repos", metavar="OWNER/NAME",
                   help="Process this repo instead of the config's list. Repeatable.")
    p.add_argument("-j", "--concurrency", type=int,
                   help="Number of workers to run in parallel.")
    p.add_argument("--model", help="Override the model used by every worker.")
    p.add_argument("--dry-run", action="store_true",
                   help="Analyse and report only; make no changes, commits, or PRs.")
    p.add_argument("--no-pr", action="store_true",
                   help="Commit locally but do not push or open pull requests.")
    p.add_argument("--work-dir", help="Directory to clone repos into.")
    return p


def _config_from_args(args: argparse.Namespace) -> Config:
    if args.repos:
        config = Config(repos=list(args.repos), settings=Settings())
    else:
        config = load_config(args.config)

    s = config.settings
    if args.concurrency is not None:
        s.concurrency = args.concurrency
    if args.model:
        s.model = args.model
    if args.dry_run:
        s.dry_run = True
    if args.no_pr:
        s.open_pr = False
    if args.work_dir:
        s.work_dir = args.work_dir
    return config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    problems = _check_prerequisites()
    if problems:
        for msg in problems:
            print(f"error: {msg}", file=sys.stderr)
        return 2

    try:
        config = _config_from_args(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Processing {len(config.repos)} repo(s) with "
        f"{config.settings.concurrency} worker(s)"
        + (" [dry run]" if config.settings.dry_run else ""),
        file=sys.stderr,
    )

    try:
        results = asyncio.run(run_all(config))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(summarise(results))
    # Non-zero exit if anything failed outright.
    return 1 if any(r.status in ("failed", "error") for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
