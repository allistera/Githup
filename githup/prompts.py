"""Prompts that steer each worker.

The agent is given a cloned repo as its working directory and is expected to be
ecosystem-agnostic: it detects whatever package manager the repo uses and drives
it, rather than us hard-coding npm/pip/cargo/etc.
"""

from __future__ import annotations

from .config import Settings

SYSTEM_PROMPT = """\
You are an autonomous dependency-maintenance engineer working inside a single \
cloned git repository. You are one of several workers each handling a different \
repository, so stay strictly within your own working directory.

Operating principles:
- Detect the project's ecosystem(s) from the files present (package.json, \
requirements.txt, pyproject.toml, poetry.lock, Pipfile, go.mod, Cargo.toml, \
Gemfile, composer.json, pom.xml, build.gradle, etc.). A repo may have more than \
one.
- Prefer the repo's own lockfile-aware tooling (npm/pnpm/yarn, uv/pip/poetry, \
cargo, go, bundler, composer, gradle/maven). Never invent commands a project \
doesn't use.
- Make the smallest change that achieves the goal. Do not rewrite code, reformat \
files, or change configuration beyond what dependency updates require.
- If something is ambiguous or a tool is missing, prefer to skip that step and \
record why in your final report rather than guessing destructively.
- Never run interactive commands; always pass non-interactive flags.
- Never touch git history beyond the single work branch you are told to use. \
Never force-push. Never merge. Never modify the default branch directly.
- You have a limited number of turns and a spend budget. Be efficient: batch \
shell commands, avoid re-reading large files, and stop once the goal is met.
"""


def build_task_prompt(repo: str, work_branch: str, base_branch: str | None,
                      settings: Settings) -> str:
    base_desc = (
        f"the branch '{base_branch}'" if base_branch else "the repository's default branch"
    )

    if settings.dry_run:
        action_section = """\
This is a DRY RUN. Do NOT modify files, do NOT commit, do NOT push, and do NOT \
open a pull request. Instead, investigate and report what you *would* do:
- Which package manager(s) the repo uses.
- Which dependencies are outdated and what the target versions would be.
- Which Dependabot alerts are open and how each would be fixed.
"""
    else:
        if not settings.open_pr:
            pr_line = ("6. Do NOT push or open a pull request; leave the commit "
                       "on the local work branch only.")
        else:
            pr_line = (
                "6. Push the work branch and open a pull request against "
                f"{base_desc} using `gh pr create`. Give it a clear title and a "
                "body that lists what was updated and which Dependabot alerts "
                "were addressed. End the PR body with exactly this final line and "
                "nothing after it:\n\n\U0001f916 Generated with Githup\n\n"
                "Do NOT add any other attribution, co-author trailer, or a "
                "'Generated with Claude Code' line to the PR body or the commits."
            )
            if settings.checks_pass:
                pr_line += (
                    "\n\n7. After the PR is open, WAIT for its CI checks to finish "
                    "and make them pass:\n"
                    "   - Wait with `gh pr checks <pr-url> --watch` (it blocks "
                    "until every check completes). If the repo has no checks "
                    "configured, gh reports that immediately — treat that as "
                    "passing and move on.\n"
                    "   - If all checks pass, you are done.\n"
                    "   - If any check FAILS, read the failure logs (e.g. "
                    "`gh run view <run-id> --log-failed`), diagnose the root "
                    "cause, and fix it with the smallest change — usually pinning "
                    "or rolling back the specific dependency update that broke the "
                    "build, or correcting a lockfile. Commit and push to the SAME "
                    "work branch, then wait for the checks again.\n"
                    "   - Repeat this fix-and-recheck loop until the checks pass "
                    "or you run low on turns/budget. If you cannot get them green "
                    "in time, set STATUS to 'partial', record the failing check "
                    "and why in the report, and leave the PR open. Never merge the "
                    "PR and never force-push."
                )
        action_section = f"""\
Carry out the following, committing as you go:

1. Create and switch to a branch named '{work_branch}' based on {base_desc}. \
If a branch with that name already exists locally, reuse it.

2. Install the project's dependencies using the correct tooling for the \
ecosystem(s) you detected (respecting any lockfile).

3. UPDATE ALL DEPENDENCIES to their latest compatible versions using the \
ecosystem's native upgrade command (e.g. `npm update` / `npm-check-updates`, \
`uv lock --upgrade`, `poetry update`, `cargo update`, `go get -u ./... && go \
mod tidy`, `bundle update`, `composer update`). Update lockfiles too. Keep \
changes to major versions conservative unless clearly safe.

4. Verify the project still builds/installs after updates when a cheap check \
exists (e.g. `npm run build` if defined, `uv sync`, `go build ./...`). If a \
check fails because of an update, roll that specific update back rather than \
leaving the repo broken. Do not spend excessive turns chasing test failures — \
note them in the report instead.

5. Fetch open Dependabot alerts for this repository with \
`gh api repos/{repo}/dependabot/alerts --paginate -f state=open` and FIX each \
one by bumping the affected dependency to the patched version the alert \
specifies. If an alert cannot be fixed automatically (e.g. no patched version, \
or it is a transitive dependency you cannot control), record it in the report. \
If the API returns 403/404, note that alert access may be unavailable and \
continue.

{pr_line}

Commit messages should be conventional (e.g. \
"chore(deps): update dependencies and fix Dependabot alerts").
"""

    return f"""\
You are working on the GitHub repository: {repo}
Your current working directory is a fresh clone of it.

{action_section}

When you are completely finished, output a concise FINAL REPORT as the last \
message, in exactly this format:

STATUS: <success | partial | skipped | failed>
ECOSYSTEMS: <comma-separated, or none>
DEPENDENCIES_UPDATED: <count or short summary>
DEPENDABOT_ALERTS_FIXED: <count>
DEPENDABOT_ALERTS_UNFIXED: <count and one-line reason each, or none>
PULL_REQUEST: <url, or "none">
CHECKS: <passed | failed | none | not applicable>
NOTES: <anything important, or none>
"""
