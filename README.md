# github-update

Spin up a pool of [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview)
workers that fan out across your GitHub repositories. Each worker:

1. **Clones** the repo into a throwaway working directory.
2. **Installs** its dependencies using whatever tooling the project actually uses.
3. **Updates all dependencies** to their latest compatible versions (and lockfiles).
4. **Checks GitHub Dependabot alerts** for the repo and **fixes** the ones it can.
5. Opens a **pull request** with the result (never merges, never touches `main`).

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
- **`gh` (GitHub CLI)** authenticated: `gh auth status`.
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
git clone https://github.com/allistera/Githup.git
cd Githup
uv sync                       # install dependencies
$EDITOR config.yaml           # list your repos (see Configuration)
```

`config.yaml` is gitignored. A minimal one is just a repo list:

```yaml
repos:
  - allistera/Cookie-Web
  - allistera/monzo-mcp
```

## Usage

Start with a **dry run** — it analyses and reports but changes nothing:

```bash
uv run github-update --dry-run
```

Then a real run:

```bash
uv run github-update                              # use config.yaml
uv run github-update -j 5                         # 5 workers in parallel
uv run github-update --repo allistera/monzo-mcp   # ad-hoc, ignore config list
uv run github-update --repo 'allistera/*'         # every repo allistera owns
uv run github-update --no-pr                      # commit locally, don't push/PR
uv run github-update --model claude-sonnet-5-5
```

`--repo` skips `config.yaml` entirely, so the run uses default settings plus
whatever flags you pass.

### Options

| Flag | Meaning |
|------|---------|
| `-c, --config PATH` | Config file (default `config.yaml`). |
| `-r, --repo OWNER/NAME` | Process this repo instead of the config list. Repeatable. `OWNER/*` processes every repo the owner has. |
| `-j, --concurrency N` | Number of workers in parallel. |
| `--model NAME` | Model for every worker. |
| `--dry-run` | Analyse and report only. No changes, commits, or PRs. |
| `--no-pr` | Commit to the work branch locally; don't push or open a PR. |
| `--work-dir DIR` | Where repos are cloned. |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Every repo finished without a `failed` or `error` status. |
| `1` | At least one repo ended as `failed` or `error`. |
| `2` | Nothing ran: a required tool (`git`, `gh`, `claude`) is missing, or the config is invalid. |
| `130` | Interrupted with Ctrl-C. |

## Configuration

Everything under `settings:` is optional and falls back to the defaults shown
below; `--dry-run`, `--no-pr`, `--concurrency`, `--model`, and `--work-dir`
override the file at runtime. Unknown keys under `settings:` are rejected.

```yaml
repos:
  - allistera/Cookie-Web                        # owner/name
  - https://github.com/allistera/monzo-mcp.git  # or a full URL
  - allistera/*                                 # or every repo an owner has

settings:
  concurrency: 3                        # workers running in parallel
  work_dir: work_repos                  # where repos are cloned
  model: null                           # null = the Claude Code CLI default
  base_branch: null                     # null = each repo's default branch
  work_branch: chore/dependency-updates # branch each worker commits to
  open_pr: true                         # false = commit locally, no push or PR
  dry_run: false                        # true = analyse and report only
  max_turns: 60                         # per-worker turn cap
  max_budget_usd: 2.0                   # per-worker spend cap; null disables it
  reuse_clones: true                    # fetch an existing clone, don't re-clone
```

An `owner/*` entry expands (via `gh repo list`, excluding forks and archived
repos) into every repo that owner has. Repos listed twice are processed once.

A relative `work_dir` is resolved under the system temp directory, not the
current directory, so clones land in e.g. `$TMPDIR/work_repos/<owner>__<name>`.
Pass an absolute path to put them somewhere else.

### Telemetry

`.env` is loaded automatically at startup and its variables are inherited by
every worker's `claude` subprocess. Copy [`.env.example`](./.env.example) to
`.env` to export Claude Code's OpenTelemetry logs and metrics to an OTLP
collector. Each worker appends `repo=<repo>` to `OTEL_RESOURCE_ATTRIBUTES`, so
concurrent workers can be told apart in the backend.

## Output

Progress is streamed per repo to stderr while workers run. At the end a summary
lists each repo's status, cost, what was updated, which alerts were fixed, and
any pull-request URLs. Example (dry run):

```
========================================================================
SUMMARY
========================================================================
allistera/monzo-mcp                           success   $  0.94     82s
    dependencies_updated: Would update 2: typescript-eslint 8.63→8.64, typescript 6.0.3→7.0.2 (major)
    dependabot_alerts_fixed: 0
    dependabot_alerts_unfixed: none (0 open)
------------------------------------------------------------------------
1 repo(s): success=1
total cost: $0.94
========================================================================
```

A repo's status is the one its worker reports (`success`, `partial`, `skipped`,
or `failed`), or `error` when the clone or the agent session itself failed.

## Running on Progenitor

This repo is also packaged as an agent for the
[Progenitor](https://github.com/allistera/Progenitor) orchestration platform:
[`agent.yaml`](./agent.yaml) is the manifest, [`Dockerfile`](./Dockerfile)
builds the image (Python + `git` + `gh` + Claude Code CLI), and
`python -m github_update.agent` implements the platform's file/stdout contract
directly — read `AGENT_INPUT_PATH`, write `AGENT_OUTPUT_PATH`, emit
`::agent-event::` progress lines, exit 0 on success. No platform SDK is used.

Register the repository with the platform's GitHub App using
`manifest_path: agent.yaml` (the default), and bind two secrets:
`ANTHROPIC_API_KEY` (authenticates the Claude workers) and `GH_TOKEN`
(authenticates `gh` for cloning, Dependabot alerts, and PRs; needs the
`repo` + `security_events` scopes).

Run input (`input.json`) mirrors config.yaml: `repos` is required and accepts
the same entries (including `owner/*`), `settings` is optional:

```json
{"repos": ["allistera/Cookie-Web"], "settings": {"dry_run": true}}
```

Run output (`output.json`):

```json
{"repos": [...], "succeeded": 1, "failed": 0, "total_cost_usd": 0.94, "pull_requests": []}
```

Each `repos` entry carries that repo's `status`, `cost_usd`, `num_turns`,
`duration_s`, `pr_url`, parsed `report`, and `error`. The run exits non-zero
only when the input is invalid, a required tool is missing, or every repo
fails; a partial failure still exits 0 and is visible in `failed`.

The manifest declares three steps — `prepare` (parse input, check tools),
`update` (the worker pool), `report` (write output) — which the entrypoint
reports via `::agent-event::` lines.

## Development

```bash
uv sync               # installs the dev group (ruff, pytest) too
uv run ruff check .   # lint
uv run pytest         # tests
```

## Safety

- Workers are told to stay inside their own clone under `work_dir`, but they
  run with `bypassPermissions`, so that is an instruction, not a sandbox.
- They create a dedicated work branch, never modify the default branch, never
  force-push, and never merge. A PR is the endpoint — you review and merge.
- `--dry-run` makes zero changes. `max_budget_usd` and `max_turns` bound each
  worker.
