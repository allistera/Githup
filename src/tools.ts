import type Anthropic from "@anthropic-ai/sdk";
import { getSandbox } from "@cloudflare/sandbox";

import { shellQuote } from "./config";
import { dependabotAlerts, openPullRequest, waitForPullRequestChecks } from "./github";
import type { ToolContext } from "./types";

const MAX_OUTPUT_CHARS = 40_000;

export const TOOLS: Anthropic.Tool[] = [
  {
    name: "bash",
    description:
      "Run a shell command in the cloned repository. No GitHub or Anthropic credentials are available to this command.",
    input_schema: {
      type: "object",
      properties: {
        command: { type: "string", description: "Non-interactive shell command" },
        timeout_ms: {
          type: "integer",
          minimum: 1_000,
          maximum: 900_000,
          description: "Timeout in milliseconds (default 120000)",
        },
      },
      required: ["command"],
    },
  },
  {
    name: "list_dependabot_alerts",
    description: "List up to 100 open Dependabot alerts for this repository.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "push_branch",
    description:
      "Push the current HEAD to the configured work branch. Commit and test changes first. Never force-pushes.",
    input_schema: { type: "object", properties: {} },
  },
  {
    name: "open_pull_request",
    description: "Open a pull request from the configured work branch, or return the existing one.",
    input_schema: {
      type: "object",
      properties: {
        title: { type: "string" },
        body: { type: "string" },
      },
      required: ["title", "body"],
    },
  },
  {
    name: "get_pull_request_checks",
    description:
      "Wait for pending CI checks (up to wait_seconds), then return check runs and commit statuses.",
    input_schema: {
      type: "object",
      properties: {
        pull_number: { type: "integer", minimum: 1 },
        wait_seconds: { type: "integer", minimum: 0, maximum: 600 },
      },
      required: ["pull_number"],
    },
  },
];

function record(input: unknown): Record<string, unknown> {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new Error("Tool input must be an object");
  }
  return input as Record<string, unknown>;
}

function requiredString(input: Record<string, unknown>, key: string): string {
  const value = input[key];
  if (typeof value !== "string" || !value.trim()) throw new Error(`${key} is required`);
  return value;
}

function truncate(value: string): string {
  if (value.length <= MAX_OUTPUT_CHARS) return value;
  return `${value.slice(0, MAX_OUTPUT_CHARS)}\n… output truncated …`;
}

export async function prepareRepository(context: ToolContext): Promise<void> {
  const { env, parameters, sandboxId } = context;
  const sandbox = getSandbox(env.Sandbox, sandboxId);
  const branchOption = parameters.baseBranch
    ? `--branch ${shellQuote(parameters.baseBranch)} `
    : "";
  const clone = await sandbox.exec(
    `rm -rf /workspace/repo && git -c http.extraHeader="Authorization: Bearer $GITHUB_TOKEN" clone --depth 1 ${branchOption}https://github.com/${parameters.repo}.git /workspace/repo`,
    { env: { GITHUB_TOKEN: env.GITHUB_TOKEN }, timeout: 900_000 },
  );
  if (!clone.success) throw new Error(`git clone failed: ${truncate(clone.stderr)}`);

  const setup = await sandbox.exec(
    `git config user.name ${shellQuote("Githup Worker")} && git config user.email ${shellQuote("githup@users.noreply.github.com")} && git checkout -B ${shellQuote(parameters.workBranch)}`,
    { cwd: "/workspace/repo", timeout: 60_000 },
  );
  if (!setup.success) throw new Error(`repository setup failed: ${truncate(setup.stderr)}`);
}

export async function executeTool(
  name: string,
  rawInput: unknown,
  context: ToolContext,
): Promise<string> {
  const input = record(rawInput);
  const { env, parameters, sandboxId } = context;

  if (name === "bash") {
    const command = requiredString(input, "command");
    const requestedTimeout = input.timeout_ms;
    const timeout =
      typeof requestedTimeout === "number"
        ? Math.max(1_000, Math.min(900_000, Math.trunc(requestedTimeout)))
        : 120_000;
    const result = await getSandbox(env.Sandbox, sandboxId).exec(command, {
      cwd: "/workspace/repo",
      timeout,
    });
    return JSON.stringify({
      success: result.success,
      exitCode: result.exitCode,
      stdout: truncate(result.stdout),
      stderr: truncate(result.stderr),
    });
  }

  if (name === "list_dependabot_alerts") {
    return JSON.stringify(await dependabotAlerts(env, parameters.repo));
  }

  if (name === "push_branch") {
    if (parameters.dryRun || !parameters.openPullRequest) {
      throw new Error("Pushing is disabled for this run");
    }
    const result = await getSandbox(env.Sandbox, sandboxId).exec(
      `git -c core.hooksPath=/dev/null -c http.extraHeader="Authorization: Bearer $GITHUB_TOKEN" push --set-upstream https://github.com/${parameters.repo}.git HEAD:refs/heads/${shellQuote(parameters.workBranch)}`,
      {
        cwd: "/workspace/repo",
        env: { GITHUB_TOKEN: env.GITHUB_TOKEN },
        timeout: 300_000,
      },
    );
    if (!result.success) throw new Error(`git push failed: ${truncate(result.stderr)}`);
    return JSON.stringify({ success: true, output: truncate(result.stdout) });
  }

  if (name === "open_pull_request") {
    if (parameters.dryRun || !parameters.openPullRequest) {
      throw new Error("Pull requests are disabled for this run");
    }
    const pull = await openPullRequest(
      env,
      parameters,
      requiredString(input, "title"),
      requiredString(input, "body"),
    );
    return JSON.stringify({ number: pull.number, url: pull.html_url });
  }

  if (name === "get_pull_request_checks") {
    const pullNumber = input.pull_number;
    if (!Number.isInteger(pullNumber) || (pullNumber as number) < 1) {
      throw new Error("pull_number must be a positive integer");
    }
    const requestedWait = input.wait_seconds;
    const waitSeconds =
      typeof requestedWait === "number"
        ? Math.max(0, Math.min(600, Math.trunc(requestedWait)))
        : 240;
    return JSON.stringify(
      await waitForPullRequestChecks(env, parameters.repo, pullNumber as number, waitSeconds),
    );
  }

  throw new Error(`Unknown tool: ${name}`);
}
