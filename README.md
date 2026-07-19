# Githup

Spin up a pool of [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview)
workers that fan out across your GitHub repositories. Each worker:

1. **Clones** the repo into a throwaway working directory.
2. **Installs** its dependencies using whatever tooling the project actually uses.
3. **Updates all dependencies** to their latest compatible versions (and lockfiles).
4. **Checks GitHub Dependabot alerts** for the repo and **fixes** the ones it can.
5. Opens a **pull request** with the result (never merges, never touches `main`).
6. **Waits for the PR's CI checks** and, if any fail, diagnoses and fixes the
   cause, pushing until they pass (or reports it couldn't within its budget).

Because each worker is a full Claude agent, it adapts to the repo in front of it —
npm / pnpm / yarn, uv / pip / poetry, cargo, go modules, bundler, composer,
gradle/maven — instead of relying on hard-coded, per-ecosystem logic.

## How it works

```
config.yaml ─▶ orchestrator ─▶ asyncio pool (N workers)
                                  │
                    ┌─────────────┼─────────────┐
                  worker        worker         worker
                    │             │              │
              clone repo     clone repo     clone repo
              Claude agent   Claude agent   Claude agent
              → update deps  → update deps  → update deps
              → fix alerts   → fix alerts   → fix alerts
              → open PR      → open PR      → open PR
```

`concurrency` controls how many workers run at once. Each is an independent
`claude` session (its own subprocess) running in `bypassPermissions` mode so it
can execute package managers and `git`/`gh` without prompting. Workers never load
your global or project `CLAUDE.md` — each runs in a clean, predictable context.

## Prerequisites

- **Python 3.12+** and [`uv`](https://docs.astral.sh/uv/).
- **Claude Code CLI** on your `PATH` and authenticated (`claude`). The SDK drives it.
- **`gh` (GitHub CLI)** authenticated and configured: `gh auth refresh -s security_events`.
- **`git`**.

### Dependabot alert access

Reading Dependabot alerts needs a token with the `security_events` scope (or
`repo` scope for repos you own). If alert queries return `403`/`404`, refresh:

```bash
gh auth refresh -s security_events
```

Workers treat unavailable alerts as a skipped step and note it in the report,
rather than failing.

## Setup

```bash
cd githup
uv sync                       # install dependencies
cp config.example.yaml config.yaml
vim config.yaml              # list your repos
```

## Usage

Start with a **dry run** — it analyses and reports but changes nothing:

```bash
uv run githup --dry-run
```

Various options:

```bash
uv run githup                              # use config.yaml
uv run githup -j 5                         # 5 workers in parallel, ignore config parallel
uv run githup --repo allistera/monzo-mcp   # ad-hoc, ignore config list
uv run githup --branch chore/deps-2026     # override the work branch
uv run githup --model claude-sonnet-5
uv run githup -v                            # verbose play-by-play
```

### Options

| Flag | Meaning |
|------|---------|
| `-c, --config PATH` | Config file (default `config.yaml`). |
| `-r, --repo OWNER/NAME` | Process this repo instead of the config list. Repeatable. |
| `-j, --concurrency N` | Number of workers in parallel. |
| `--model NAME` | Model for every worker. |
| `--dry-run` | Analyse and report only. No changes, commits, or PRs. |
| `--branch NAME` | Branch each worker creates its changes on (overrides `work_branch`). |
| `--work-dir DIR` | Where repos are cloned. |
| `--cleanup / --no-cleanup` | Delete (or keep) the cloned repos when the run finishes. |
| `-v, --verbose` | Detailed play-by-play: every tool call, agent narration, per-repo timing. |

## Configuration

See [`config.example.yaml`](./config.example.yaml). Everything under `settings:`
is optional and falls back to sensible defaults; `--dry-run`, `--branch`,
`--concurrency`, `--model`, `--work-dir`, `--cleanup`, and `--verbose` can
override the file at runtime.

Key knobs: `concurrency`, `work_branch`, `base_branch`, `open_pr`, `dry_run`,
`max_turns`, and `max_budget_usd` (a per-worker spend ceiling, default $2).

## Output

Progress is streamed per repo to stderr as a bulleted list while workers run
(`-v` adds a full play-by-play). At the end, a table lists only the repos that
opened a pull request — flagging whether dependencies were updated, Dependabot
alerts were fixed, and CI checks passed (✓) or failed (✗):

```
* allistera/Cookie-Web - Cloned, running agent...
* allistera/monzo-mcp - Cloned, running agent...

Repository            Package Update  Security Fix  Checks  URL
--------------------  --------------  ------------  ------  -----------------------------------------------
allistera/Cookie-Web        ✓              ✓          ✓     https://github.com/allistera/Cookie-Web/pull/41
allistera/monzo-mcp         ✓                         ✗     https://github.com/allistera/monzo-mcp/pull/7

2 pull request(s) · total cost: $3.60
```

## Safety

- Workers only ever operate inside their own clone under `work_dir/`.
- They create a dedicated work branch, never modify the default branch, never
  force-push, and never merge. A PR is the endpoint — you review and merge.
- `--dry-run` makes zero changes. `max_budget_usd` and `max_turns` bound each
  worker.
