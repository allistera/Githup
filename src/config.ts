import type { RunParameters, RunRequestBody } from "./types";

const REPOSITORY_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const BRANCH_PATTERN = /^(?!-)(?!.*\.\.)(?!.*\/\/)[A-Za-z0-9._/-]+$/;
const DEFAULT_WORK_BRANCH = "chore/dependency-updates";

function optionalBoolean(value: unknown, name: string, fallback: boolean): boolean {
  if (value === undefined) return fallback;
  if (typeof value !== "boolean") throw new Error(`${name} must be a boolean`);
  return value;
}

function optionalBranch(value: unknown, name: string): string | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value !== "string" || !BRANCH_PATTERN.test(value) || value.endsWith("/")) {
    throw new Error(`${name} is not a valid Git branch name`);
  }
  return value;
}

function repository(value: unknown): string {
  if (typeof value !== "string" || !REPOSITORY_PATTERN.test(value)) {
    throw new Error(`Invalid repository ${JSON.stringify(value)}; use owner/name`);
  }
  return value;
}

export function parseRunRequest(body: RunRequestBody): RunParameters[] {
  const rawRepos = body.repos ?? (body.repo === undefined ? undefined : [body.repo]);
  if (!Array.isArray(rawRepos) || rawRepos.length === 0) {
    throw new Error("Provide repo or a non-empty repos array");
  }
  if (rawRepos.length > 20) throw new Error("A request may contain at most 20 repositories");

  const baseBranch = optionalBranch(body.baseBranch, "baseBranch");
  const workBranch = optionalBranch(body.workBranch ?? DEFAULT_WORK_BRANCH, "workBranch");
  if (workBranch === null) throw new Error("workBranch cannot be empty");

  const dryRun = optionalBoolean(body.dryRun, "dryRun", true);
  const openPullRequest = optionalBoolean(body.openPullRequest, "openPullRequest", true);
  const waitForChecks = optionalBoolean(body.waitForChecks, "waitForChecks", true);
  if (!dryRun && !openPullRequest) {
    throw new Error("openPullRequest must be true for write runs because sandboxes are temporary");
  }
  const maxTurns = body.maxTurns ?? 30;
  if (!Number.isInteger(maxTurns) || (maxTurns as number) < 1 || (maxTurns as number) > 60) {
    throw new Error("maxTurns must be an integer between 1 and 60");
  }

  return rawRepos.map((value) => ({
    repo: repository(value),
    baseBranch,
    workBranch,
    dryRun,
    openPullRequest: !dryRun,
    waitForChecks: dryRun || !openPullRequest ? false : waitForChecks,
    maxTurns: maxTurns as number,
  }));
}

export function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}
