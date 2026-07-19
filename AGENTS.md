# Repository Guidelines

## Project Structure & Module Organization

`githup/` contains the Python package. `cli.py` parses command-line options,
`config.py` loads YAML configuration, `orchestrator.py` coordinates concurrent
workers, `worker.py` runs an individual repository task, and `prompts.py`
builds its agent instructions. Put deterministic unit tests in `tests/`.
`config.example.yaml` documents user-facing settings; keep it aligned with
`Settings` in `githup/config.py`. Runtime clones belong in `work_repos/` and
must not be committed.

## Build, Test, and Development Commands

- `uv sync` installs the Python 3.12+ project and development dependencies.
- `uv run pytest` runs the test suite configured in `pyproject.toml`.
- `uv run githup --dry-run` exercises the CLI without changing target repos.
- `uv run githup --repo OWNER/NAME -v` runs one repository with detailed
  worker output. Ensure `git`, authenticated `gh`, and authenticated `claude`
  are on `PATH` before a real run.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations, `from __future__ import
annotations`, and standard-library-first imports, matching the existing
modules. Prefer small, pure helpers for parsing and rendering. Use
`snake_case` for functions, variables, and module names; `PascalCase` for
dataclasses such as `RepoResult` and `Settings`. Keep command-line flags and
YAML keys explicit and document any new setting in both `Settings` and
`config.example.yaml`.

## Testing Guidelines

Write `pytest` tests in `tests/test_*.py`, naming cases `test_<behaviour>`.
Parametrize edge cases where it improves clarity. Test the real helper or
public CLI parser instead of duplicating production logic. Keep agent-driven
work out of unit tests; use a deliberate `--dry-run` against a real repository
for end-to-end validation. Run `uv run pytest` before every commit.

## Commit & Pull Request Guidelines

Use concise, imperative commit subjects, for example `Add checks_pass config
option` or `Wait for PR checks and fix failures`. Keep each commit focused.
PRs should explain the behavioral change, list validation performed, mention
configuration or safety implications, and link related issues. Include CLI
output or screenshots only when they clarify changed user-visible behavior.
