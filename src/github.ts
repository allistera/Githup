import type { Env, RunParameters } from "./types";

interface GitHubError {
  message?: string;
}

interface PullRequest {
  html_url: string;
  number: number;
  head: { sha: string };
}

async function githubRequest<T>(
  env: Env,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "githup-cloudflare-worker",
      "X-GitHub-Api-Version": "2022-11-28",
      ...init.headers,
    },
  });
  if (!response.ok) {
    const error: GitHubError = await response.json<GitHubError>().catch(() => ({}));
    throw new Error(`GitHub API ${response.status}: ${error.message ?? response.statusText}`);
  }
  return response.json<T>();
}

export async function defaultBranch(env: Env, repo: string): Promise<string> {
  const result = await githubRequest<{ default_branch: string }>(env, `/repos/${repo}`);
  return result.default_branch;
}

export async function dependabotAlerts(env: Env, repo: string): Promise<unknown> {
  return githubRequest<unknown>(
    env,
    `/repos/${repo}/dependabot/alerts?state=open&per_page=100`,
  );
}

export async function openPullRequest(
  env: Env,
  parameters: RunParameters,
  title: string,
  body: string,
): Promise<PullRequest> {
  const owner = parameters.repo.split("/")[0];
  if (!owner) throw new Error("Repository owner is missing");

  const existing = await githubRequest<PullRequest[]>(
    env,
    `/repos/${parameters.repo}/pulls?state=open&head=${encodeURIComponent(`${owner}:${parameters.workBranch}`)}`,
  );
  if (existing[0]) return existing[0];

  const footer = "🤖 Generated with Githup";
  const trimmedBody = body.trim().replace(/\n*🤖 Generated with Githup\s*$/u, "").trim();
  return githubRequest<PullRequest>(env, `/repos/${parameters.repo}/pulls`, {
    method: "POST",
    body: JSON.stringify({
      title: title.slice(0, 256),
      body: `${trimmedBody}\n\n${footer}`,
      head: parameters.workBranch,
      base: parameters.baseBranch ?? (await defaultBranch(env, parameters.repo)),
    }),
  });
}

interface CheckRun {
  name: string;
  status: string;
  conclusion: string | null;
  html_url: string | null;
}

interface PullRequestCheckResult {
  sha: string;
  overall: "passed" | "failed" | "pending" | "none";
  checkRuns: CheckRun[];
  commitStatus: { state: string; statuses: unknown[] };
}

export async function pullRequestChecks(
  env: Env,
  repo: string,
  pullNumber: number,
): Promise<PullRequestCheckResult> {
  const pull = await githubRequest<PullRequest>(env, `/repos/${repo}/pulls/${pullNumber}`);
  const [checks, status] = await Promise.all([
    githubRequest<{ check_runs: CheckRun[] }>(
      env,
      `/repos/${repo}/commits/${pull.head.sha}/check-runs?per_page=100`,
    ),
    githubRequest<{ state: string; statuses: unknown[] }>(
      env,
      `/repos/${repo}/commits/${pull.head.sha}/status`,
    ),
  ]);
  const hasChecks = checks.check_runs.length > 0 || status.statuses.length > 0;
  const failed =
    status.state === "failure" ||
    status.state === "error" ||
    checks.check_runs.some(
      (check) =>
        check.status === "completed" &&
        check.conclusion !== null &&
        !["success", "neutral", "skipped"].includes(check.conclusion),
    );
  const pending =
    checks.check_runs.some((check) => check.status !== "completed") ||
    (status.statuses.length > 0 && status.state === "pending");
  const overall = !hasChecks ? "none" : failed ? "failed" : pending ? "pending" : "passed";
  return { sha: pull.head.sha, overall, checkRuns: checks.check_runs, commitStatus: status };
}

export async function waitForPullRequestChecks(
  env: Env,
  repo: string,
  pullNumber: number,
  waitSeconds: number,
): Promise<PullRequestCheckResult> {
  const deadline = Date.now() + waitSeconds * 1_000;
  let result = await pullRequestChecks(env, repo, pullNumber);
  while (result.overall === "pending" && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 15_000));
    result = await pullRequestChecks(env, repo, pullNumber);
  }
  return result;
}
