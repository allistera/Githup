"""A single worker: clone one repo and run a Claude Agent SDK session on it."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from .config import Config
from .prompts import SYSTEM_PROMPT, build_task_prompt

# Tools each worker is allowed to use. Bash covers git/gh/package managers; the
# file tools let the agent read and adjust manifests and lockfiles.
ALLOWED_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "TodoWrite"]

_REPORT_KEYS = (
    "STATUS",
    "ECOSYSTEMS",
    "DEPENDENCIES_UPDATED",
    "DEPENDABOT_ALERTS_FIXED",
    "DEPENDABOT_ALERTS_UNFIXED",
    "PULL_REQUEST",
    "NOTES",
)


@dataclass
class RepoResult:
    repo: str
    status: str = "unknown"  # success | partial | skipped | failed | error
    cost_usd: float = 0.0
    num_turns: int = 0
    duration_s: float = 0.0
    pr_url: str | None = None
    report: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def _otel_env_for_repo(repo: str) -> dict[str, str]:
    """Tag this worker's OTEL logs/metrics with the repo it's processing.

    Appends `repo=<repo>` to any OTEL_RESOURCE_ATTRIBUTES already set in the
    environment (e.g. service.name=github-update), so SigNoz can filter one
    worker's telemetry out of the pool.
    """
    base = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
    tag = f"repo={repo}"
    attrs = f"{base},{tag}" if base else tag
    return {"OTEL_RESOURCE_ATTRIBUTES": attrs}


def _slug(repo: str) -> str:
    """A filesystem-safe directory name for a repo reference."""
    name = repo.rstrip("/")
    name = re.sub(r"^https?://", "", name)
    name = re.sub(r"^git@[^:]+:", "", name)
    name = re.sub(r"\.git$", "", name)
    return name.replace("/", "__").replace(":", "__")


async def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace")


async def clone_or_update(repo: str, work_dir: Path, reuse: bool) -> Path:
    """Clone ``repo`` into ``work_dir`` (or freshen an existing clone)."""
    dest = work_dir / _slug(repo)

    if dest.exists():
        if reuse and (dest / ".git").exists():
            code, out = await _run(["git", "fetch", "--all", "--prune"], cwd=dest)
            if code != 0:
                raise RuntimeError(f"git fetch failed: {out.strip()[:400]}")
            return dest
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    # `gh repo clone` handles auth and both owner/name and URL forms.
    code, out = await _run(["gh", "repo", "clone", repo, str(dest)])
    if code != 0:
        raise RuntimeError(f"clone failed: {out.strip()[:400]}")
    return dest


def _parse_report(text: str) -> dict[str, str]:
    report: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Z_]+)\s*:\s*(.*)$", line)
        if m and m.group(1) in _REPORT_KEYS:
            report[m.group(1)] = m.group(2).strip()
    return report


async def run_worker(
    repo: str,
    config: Config,
    semaphore: asyncio.Semaphore,
    log,
) -> RepoResult:
    """Process a single repository end to end, bounded by ``semaphore``."""
    result = RepoResult(repo=repo)
    started = time.monotonic()

    async with semaphore:
        log(repo, "starting")
        try:
            repo_path = await clone_or_update(
                repo, config.work_dir_path, config.settings.reuse_clones
            )
        except Exception as exc:  # noqa: BLE001 - report, don't crash the pool
            result.status = "error"
            result.error = f"clone: {exc}"
            result.duration_s = time.monotonic() - started
            log(repo, f"clone failed: {exc}")
            return result

        log(repo, f"cloned -> {repo_path}")

        options = ClaudeAgentOptions(
            cwd=str(repo_path),
            system_prompt=SYSTEM_PROMPT,
            allowed_tools=ALLOWED_TOOLS,
            permission_mode="bypassPermissions",
            max_turns=config.settings.max_turns,
            max_budget_usd=config.settings.max_budget_usd,
            model=config.settings.model,
            # Do not inherit the user's global/project CLAUDE.md or settings:
            # each worker runs in a clean, predictable context.
            setting_sources=None,
            env=_otel_env_for_repo(repo),
        )
        task = build_task_prompt(
            repo,
            config.settings.work_branch,
            config.settings.base_branch,
            config.settings,
        )

        last_text = ""
        try:
            async for message in query(prompt=task, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            last_text = block.text
                        elif isinstance(block, ToolUseBlock):
                            log(repo, f"tool: {block.name}")
                elif isinstance(message, ResultMessage):
                    result.cost_usd = message.total_cost_usd or 0.0
                    result.num_turns = message.num_turns or 0
                    if message.result:
                        last_text = message.result
                    if message.is_error:
                        result.status = "failed"
                        result.error = (message.subtype or "agent error")
        except Exception as exc:  # noqa: BLE001
            result.status = "error"
            result.error = f"agent: {exc}"
            result.duration_s = time.monotonic() - started
            log(repo, f"agent failed: {exc}")
            return result

        result.report = _parse_report(last_text)
        if result.status not in ("failed", "error"):
            result.status = result.report.get("STATUS", "success").lower()
        pr = result.report.get("PULL_REQUEST", "").strip()
        # Only treat it as a real PR if it actually looks like a URL; the agent
        # writes things like "none (dry run)" otherwise.
        if pr.startswith("http"):
            result.pr_url = pr

    result.duration_s = time.monotonic() - started
    log(repo, f"done: {result.status} (${result.cost_usd:.2f}, {result.duration_s:.0f}s)")
    return result
