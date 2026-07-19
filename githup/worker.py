"""A single worker: clone one repo and run a Claude Agent SDK session on it."""

from __future__ import annotations

import asyncio
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
    "CHECKS",
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


def _tool_detail(tool_input: object) -> str:
    """A short, human-readable summary of a tool call's key argument."""
    if not isinstance(tool_input, dict):
        return ""
    for key in ("command", "file_path", "pattern", "path", "query", "url"):
        val = tool_input.get(key)
        if val:
            first = str(val).strip().splitlines()[0] if str(val).strip() else ""
            return first[:120]
    return ""


def _snippet(text: str, limit: int = 200) -> str:
    """First non-empty line of ``text``, trimmed to ``limit`` characters."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:limit] + ("…" if len(line) > limit else "")
    return ""


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


def cleanup_clones(repos: list[str], work_dir: Path) -> int:
    """Delete the clone directory for each repo. Returns how many were removed.

    Only the per-repo clone directories this run would have created (keyed by
    :func:`_slug`) are touched; the work dir itself is removed only if it ends
    up empty, so an unrelated or shared directory is never blown away.
    """
    removed = 0
    for repo in repos:
        dest = work_dir / _slug(repo)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
            removed += 1
    try:
        if work_dir.exists() and not any(work_dir.iterdir()):
            work_dir.rmdir()
    except OSError:
        pass
    return removed


def _parse_report(text: str) -> dict[str, str]:
    report: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Z_]+)\s*:\s*(.*)$", line)
        if m and m.group(1) in _REPORT_KEYS:
            report[m.group(1)] = m.group(2).strip()
    return report


def _extract_pr_url(report: dict[str, str]) -> str | None:
    """Return the PR URL from a report, or None.

    Only a value that actually looks like a URL counts; the agent writes
    things like "none" or "none (dry run)" when there is no PR.
    """
    pr = report.get("PULL_REQUEST", "").strip()
    return pr if pr.startswith("http") else None


async def run_worker(
    repo: str,
    config: Config,
    semaphore: asyncio.Semaphore,
    log,
) -> RepoResult:
    """Process a single repository end to end, bounded by ``semaphore``."""
    result = RepoResult(repo=repo)
    started = time.monotonic()
    verbose = config.settings.verbose

    async with semaphore:
        if verbose:
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

        log(repo, "Cloned, running agent...")

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
                            if verbose and (s := _snippet(block.text)):
                                log(repo, s)
                        elif isinstance(block, ToolUseBlock) and verbose:
                            detail = _tool_detail(block.input)
                            log(repo, f"{block.name}: {detail}" if detail else block.name)
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
        result.pr_url = _extract_pr_url(result.report)

    result.duration_s = time.monotonic() - started
    log(repo, "finished in {:.0f}s".format(result.duration_s))

    if verbose:
        log(repo, f"done: {result.status} (${result.cost_usd:.2f}, "
                  f"{result.duration_s:.0f}s, {result.num_turns} turns)")
    elif result.status not in ("success", "partial"):
        log(repo, result.status)
    return result
