"""Fan work out across repos with a bounded pool of concurrent workers."""

from __future__ import annotations

import asyncio
import sys
import threading

from .config import Config
from .worker import RepoResult, run_worker

_print_lock = threading.Lock()


def _log(repo: str, msg: str) -> None:
    with _print_lock:
        print(f"[{repo}] {msg}", file=sys.stderr, flush=True)


async def run_all(config: Config) -> list[RepoResult]:
    if not config.repos:
        raise ValueError("No repos configured. Add some under 'repos:' in the config.")

    semaphore = asyncio.Semaphore(max(1, config.settings.concurrency))
    tasks = [
        asyncio.create_task(run_worker(repo, config, semaphore, _log))
        for repo in config.repos
    ]
    return await asyncio.gather(*tasks)


def summarise(results: list[RepoResult]) -> str:
    lines: list[str] = []
    lines.append("")
    lines.append("=" * 72)
    lines.append("SUMMARY")
    lines.append("=" * 72)

    total_cost = 0.0
    counts: dict[str, int] = {}
    for r in results:
        total_cost += r.cost_usd
        counts[r.status] = counts.get(r.status, 0) + 1

    for r in results:
        header = f"{r.repo:<45} {r.status:<9} ${r.cost_usd:>6.2f}  {r.duration_s:>5.0f}s"
        lines.append(header)
        if r.error:
            lines.append(f"    error: {r.error}")
        if r.report:
            for key in ("DEPENDENCIES_UPDATED", "DEPENDABOT_ALERTS_FIXED",
                        "DEPENDABOT_ALERTS_UNFIXED", "PULL_REQUEST", "NOTES"):
                val = r.report.get(key)
                if val and val.lower() != "none":
                    lines.append(f"    {key.lower()}: {val}")

    lines.append("-" * 72)
    status_bits = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    lines.append(f"{len(results)} repo(s): {status_bits}")
    lines.append(f"total cost: ${total_cost:.2f}")
    prs = [r.pr_url for r in results if r.pr_url]
    if prs:
        lines.append("pull requests:")
        lines.extend(f"    {u}" for u in prs)
    lines.append("=" * 72)
    return "\n".join(lines)
