"""Progenitor platform entrypoint implementing the file/stdout contract.

No platform SDK is imported - the container contract is: read
AGENT_INPUT_PATH, write AGENT_OUTPUT_PATH, emit optional "::agent-event::"
progress lines, exit 0 on success.

Run input:

    {"repos": ["owner/name", ...], "settings": {...}}

``settings`` is optional and accepts the same keys as the ``settings:``
section of config.yaml. Run output is a JSON object with per-repo results,
totals, and any pull-request URLs.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from .config import Config, Settings
from .orchestrator import run_all


def _emit(event_type: str, **payload: Any) -> None:
    print(f"::agent-event::{json.dumps({'type': event_type, **payload})}", flush=True)


def _settings_from(raw: Any) -> Settings:
    if raw is None:
        return Settings()
    if not isinstance(raw, dict):
        raise TypeError("'settings' must be an object")
    known = {f.name for f in fields(Settings)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"Unknown settings keys: {', '.join(sorted(unknown))}")
    return Settings(**raw)


def _load_config(input_path: Path) -> Config:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("run input must be a JSON object")
    repos = payload.get("repos")
    if not isinstance(repos, list) or not all(
        isinstance(r, str) and r.strip() for r in repos
    ):
        raise ValueError("'repos' must be a non-empty list of 'owner/name' strings")
    if not repos:
        raise ValueError("'repos' must not be empty")
    return Config(repos=[r.strip() for r in repos], settings=_settings_from(payload.get("settings")))


def main() -> int:
    input_path = Path(os.environ["AGENT_INPUT_PATH"])
    output_path = Path(os.environ["AGENT_OUTPUT_PATH"])

    _emit("step.started", step="prepare", message="Reading run input.")
    try:
        config = _load_config(input_path)
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"invalid run input: {error}", file=sys.stderr)
        _emit("step.failed", step="prepare", message=str(error))
        return 1
    missing = [tool for tool in ("git", "gh", "claude") if shutil.which(tool) is None]
    if missing:
        message = f"required tool(s) not on PATH: {', '.join(missing)}"
        print(message, file=sys.stderr)
        _emit("step.failed", step="prepare", message=message)
        return 1
    _emit(
        "step.completed",
        step="prepare",
        summary=f"{len(config.repos)} repo(s), concurrency {config.settings.concurrency}"
        + (" [dry run]" if config.settings.dry_run else "") + ".",
    )

    _emit("step.started", step="update", message="Running the worker pool.")
    try:
        results = asyncio.run(run_all(config))
    except Exception as error:  # noqa: BLE001 - reported to the platform, not swallowed
        _emit("step.failed", step="update", message=str(error))
        return 1
    failed = [r for r in results if r.status in ("failed", "error")]
    all_failed = len(failed) == len(results)
    if all_failed:
        _emit("step.failed", step="update", message="Every repo failed.")
    else:
        _emit(
            "step.completed",
            step="update",
            summary=f"{len(results) - len(failed)}/{len(results)} repo(s) succeeded.",
        )

    _emit("step.started", step="report", message="Writing output.json.")
    output_path.write_text(
        json.dumps(
            {
                "repos": [asdict(r) for r in results],
                "succeeded": len(results) - len(failed),
                "failed": len(failed),
                "total_cost_usd": round(sum(r.cost_usd for r in results), 4),
                "pull_requests": [r.pr_url for r in results if r.pr_url],
            }
        ),
        encoding="utf-8",
    )
    _emit("step.completed", step="report", summary="Output written.")
    return 1 if all_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
