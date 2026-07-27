import type { Sandbox } from "@cloudflare/sandbox";

export interface Env {
  Sandbox: DurableObjectNamespace<Sandbox>;
  GITHUP_WORKFLOW: Workflow<RunParameters>;
  ANTHROPIC_API_KEY: string;
  GITHUB_TOKEN: string;
  API_TOKEN: string;
  ANTHROPIC_MODEL: string;
  SANDBOX_TRANSPORT?: string;
}

export interface RunRequestBody {
  repos?: unknown;
  repo?: unknown;
  baseBranch?: unknown;
  workBranch?: unknown;
  dryRun?: unknown;
  openPullRequest?: unknown;
  waitForChecks?: unknown;
  maxTurns?: unknown;
}

export interface RunParameters {
  repo: string;
  baseBranch: string | null;
  workBranch: string;
  dryRun: boolean;
  openPullRequest: boolean;
  waitForChecks: boolean;
  maxTurns: number;
}

export interface RepositoryReport {
  repo: string;
  status: string;
  ecosystems: string;
  dependenciesUpdated: string;
  dependabotAlertsFixed: string;
  dependabotAlertsUnfixed: string;
  pullRequest: string | null;
  checks: string;
  notes: string;
  turns: number;
  inputTokens: number;
  outputTokens: number;
}

export interface ToolContext {
  env: Env;
  parameters: RunParameters;
  sandboxId: string;
}
