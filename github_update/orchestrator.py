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


_CHECK = "✓"


def _is_affirmative(val: str | None) -> bool:
    """True when a report value indicates real work happened (not none/zero)."""
    if not val:
        return False
    return val.strip().lower() not in ("", "none", "0", "no", "n/a")


def summarise(results: list[RepoResult]) -> str:
    """Render a table of repos that opened a pull request.

    Only repos with a real PR appear. Columns: Repository, Package Update,
    Security Fix, URL — the first two flagged with a checkmark when true.
    """
    pr_results = [r for r in results if r.pr_url]

    lines: list[str] = [""]
    if pr_results:
        headers = ("Repository", "Package Update", "Security Fix", "URL")
        rows = [
            (
                r.repo,
                _CHECK if _is_affirmative(r.report.get("DEPENDENCIES_UPDATED")) else "",
                _CHECK if _is_affirmative(r.report.get("DEPENDABOT_ALERTS_FIXED")) else "",
                r.pr_url or "",
            )
            for r in pr_results
        ]

        widths = [len(h) for h in headers]
        for row in rows:
            widths = [max(w, len(cell)) for w, cell in zip(widths, row)]

        def _fmt(cells: tuple[str, ...]) -> str:
            # Repository/URL left-aligned; the two flag columns centred.
            out = [
                cell.center(widths[i]) if i in (1, 2) else cell.ljust(widths[i])
                for i, cell in enumerate(cells)
            ]
            return "  ".join(out).rstrip()

        lines.append(_fmt(headers))
        lines.append("  ".join("-" * w for w in widths))
        lines.extend(_fmt(row) for row in rows)
    else:
        lines.append("No pull requests were opened.")

    total_cost = sum(r.cost_usd for r in results)
    failed = [r for r in results if r.status in ("failed", "error")]
    lines.append("")
    footer = f"{len(pr_results)} pull request(s) · total cost: ${total_cost:.2f}"
    if failed:
        footer += f" · {len(failed)} repo(s) failed (see log above)"
    lines.append(footer)
    return "\n".join(lines)
