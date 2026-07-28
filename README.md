# Githup

Githup is an Anthropic-powered dependency-maintenance agent deployed as a
[Cloudflare Worker](https://developers.cloudflare.com/workers/). Each repository
run is a durable [Cloudflare Workflow](https://developers.cloudflare.com/workflows/)
and gets its own isolated [Sandbox container](https://developers.cloudflare.com/sandbox/).

The Worker can:

1. Clone a public or private GitHub repository.
2. Ask Claude to detect its package ecosystems and update dependencies.
3. Read open Dependabot alerts through the GitHub API.
4. Run install, build, lint, and test commands inside an isolated Linux container.
5. Commit and push a dedicated branch, then open a pull request.
6. Inspect the pull request's GitHub check runs and iterate on failures.
7. Optionally coordinate an issue-linked run through a self-hosted
   [Projektor](https://tajd.github.io/projektor/) workspace over MCP.

Runs are asynchronous. `POST /runs` returns an ID immediately and `GET /runs/:id`
returns Cloudflare's durable status and, when complete, the agent's structured report.

## Architecture

```text
HTTP API ──▶ Cloudflare Workflow ──▶ Cloudflare AI Gateway ──▶ Anthropic Messages API
                    │                                            │
                    │                                            ├── bash
                    │                                            ├── Dependabot alerts
                    │                                            ├── push branch
                    │                                            ├── PR/check status
                    │                                            └── Projektor MCP tools (optional)
                    ▼
             Sandbox container
             git + Node + Python + uv
```

Claude never receives either API key. General `bash` commands run without secrets;
the GitHub token is supplied only to the exact clone and push commands constructed by
the Worker. Use a fine-grained GitHub token limited to the repositories this service
may maintain.

## Prerequisites

- Node.js 20+
- Docker for local Sandbox development and image builds
- A Cloudflare account on the Workers Paid plan with Containers/Sandbox available
- An Anthropic API key
- A fine-grained GitHub token with access to the target repositories and permissions
  for contents, pull requests, Dependabot alerts, actions, and commit statuses
- Optionally, a deployed Projektor instance and a workspace-scoped API token with
  read/write access

## Setup

```bash
npm install
cp .dev.vars.example .dev.vars
```

Fill in `.dev.vars`:

```dotenv
ANTHROPIC_API_KEY=...
GITHUB_TOKEN=...
API_TOKEN=... # a long random bearer token for this Worker's HTTP API
```

To enable Projektor locally, also set:

```dotenv
PROJEKTOR_MCP_URL=https://projektor.example/mcp/WORKSPACE_UUID
PROJEKTOR_API_TOKEN=pk_...
# Required only when Cloudflare Access protects the Projektor instance:
PROJEKTOR_ACCESS_CLIENT_ID=...
PROJEKTOR_ACCESS_CLIENT_SECRET=...
```

The MCP URL must include the workspace UUID. The API token is created in Projektor
under Settings → Tokens and must belong to that workspace. If the instance is behind
Cloudflare Access, use a service token for the two `PROJEKTOR_ACCESS_*` values so the
headless Workflow can pass the Access gate.

The default model is `claude-sonnet-4-5`. Anthropic requests are routed through
Cloudflare AI Gateway using the built-in AI binding and the automatically provisioned
`default` gateway. Change `ANTHROPIC_MODEL` or `AI_GATEWAY_ID` in
[`wrangler.jsonc`](./wrangler.jsonc) if needed. The Anthropic API key remains a Worker
secret and is forwarded only to Anthropic through the gateway.

## Local development

```bash
npm run dev
```

The first start builds the Sandbox image and can take a few minutes. Check health:

```bash
curl http://localhost:8787/health
```

Start a safe, read-only run (dry run is the default):

```bash
curl -X POST http://localhost:8787/runs \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"repo":"OWNER/NAME"}'
```

Start a write run that can push and open a pull request:

```bash
curl -X POST http://localhost:8787/runs \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"repo":"OWNER/NAME","dryRun":false}'
```

Poll or terminate a run:

```bash
curl -H "Authorization: Bearer $API_TOKEN" http://localhost:8787/runs/RUN_ID
curl -X DELETE -H "Authorization: Bearer $API_TOKEN" http://localhost:8787/runs/RUN_ID
```

## API

### `POST /runs`

Accepts one `repo` or up to 20 `repos`:

```json
{
  "repos": ["owner/one", "owner/two"],
  "baseBranch": "main",
  "workBranch": "chore/dependency-updates",
  "dryRun": false,
  "waitForChecks": true,
  "maxTurns": 30,
  "projektorIssue": "PROJ-42"
}
```

Defaults are deliberately safe: `dryRun` is `true`, the work branch is
`chore/dependency-updates`, and Claude is capped at 30 turns. Cloudflare runs each
repository as an independent Workflow instance, so fan-out does not keep one HTTP
request open. Write runs always open a pull request because their temporary sandbox
is destroyed at completion; set `dryRun` to inspect without publishing changes.

`projektorIssue` is optional and can only be used with a single `repo`. When present,
Claude is instructed to fetch Projektor's canonical workflow and issue, register and
claim the work, report the result with verifiable PR or commit evidence, and release
its agent session. Projektor's live MCP tool schemas are discovered at the start of
each Workflow and exposed to Claude with a `projektor__` prefix. Runs without
`projektorIssue` can still use Projektor tools when the integration is configured, but
their normal dependency-maintenance behavior is unchanged.

### `GET /runs/:id`

Returns the Workflow state. A completed response includes an `output` object with the
repository status, dependency/Dependabot summary, pull-request URL, check status,
turn count, and Anthropic token usage.

### `DELETE /runs/:id`

Terminates an in-progress Workflow instance.

All run endpoints require `Authorization: Bearer <API_TOKEN>`. `GET /health` is public.

## Deploy

```bash
npx wrangler login
npm run deploy
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put API_TOKEN
```

For Projektor-backed runs, deploy Projektor separately first. Its
[deployment guide](https://tajd.github.io/projektor/guides/deploying/#2-provision-cloudflare-resources)
provisions its D1 database, KV namespace, and R2 bucket:

```bash
wrangler d1 create projektor
wrangler kv namespace create projektor
wrangler r2 bucket create projektor-files
```

Finish the Projektor deployment, create a workspace API token, then configure this
Worker:

```bash
npx wrangler secret put PROJEKTOR_MCP_URL
npx wrangler secret put PROJEKTOR_API_TOKEN
# Only when the Projektor instance is behind Cloudflare Access:
npx wrangler secret put PROJEKTOR_ACCESS_CLIENT_ID
npx wrangler secret put PROJEKTOR_ACCESS_CLIENT_SECRET
```

Set each Access value together or omit both. Likewise, the MCP URL and Projektor token
must either both be present or both be absent. `GET /health` reports `projektor: true`,
`false`, or returns an invalid-configuration error without exposing any credentials.

Deploy once before adding secrets because Wrangler creates the Worker and its
Sandbox/Workflow bindings on the first deployment. A production secret update creates
a new Worker version. Never put secret values in `wrangler.jsonc`.

Validate the bundle and container without deploying:

```bash
npm run deploy:dry-run
```

## Development checks

```bash
npm run check
```

This runs ESLint, strict TypeScript checking, and the deterministic Vitest suite.
The Anthropic agent loop is intentionally not invoked by unit tests; use a dry run
against a small repository for an end-to-end check.

## Runtime notes

- Sandboxes are temporary and are destroyed after each Workflow completes.
- The image includes Git, Node.js, npm, Python, pip, `uv`, `jq`, and `ripgrep`.
  Claude may install other project tooling inside that run's container.
- The Worker never force-pushes or merges. The dedicated work branch and pull request
  remain the review boundary.
- A repository can execute arbitrary scripts during dependency installation. Sandbox
  isolation protects the Worker host, but target repositories should still be trusted
  and the GitHub token should have the least possible privilege.
