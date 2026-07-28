import { afterEach, describe, expect, it, vi } from "vitest";

import { openPullRequest } from "../src/github";
import type { Env, RunParameters } from "../src/types";

afterEach(() => vi.unstubAllGlobals());

describe("openPullRequest", () => {
  it("is idempotent when the branch already has an open pull request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json([{ html_url: "https://github.com/a/b/pull/7", number: 7, head: { sha: "abc" } }]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await openPullRequest(
      { GITHUB_TOKEN: "token" } as Env,
      parameters(),
      "Update dependencies",
      "Body",
    );

    expect(result.number).toBe(7);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("adds the Githup footer exactly once", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json([]))
      .mockResolvedValueOnce(Response.json({ html_url: "https://github.com/a/b/pull/8", number: 8, head: { sha: "def" } }));
    vi.stubGlobal("fetch", fetchMock);

    await openPullRequest(
      { GITHUB_TOKEN: "token" } as Env,
      parameters(),
      "Update dependencies",
      "Body\n\n🤖 Generated with Githup",
    );

    const request = fetchMock.mock.calls[1]?.[1] as RequestInit;
    const body = JSON.parse(String(request.body)) as { body: string };
    expect(body.body.match(/Generated with Githup/g)).toHaveLength(1);
  });
});

function parameters(): RunParameters {
  return {
    repo: "a/b",
    baseBranch: "main",
    workBranch: "chore/dependency-updates",
    dryRun: false,
    openPullRequest: true,
    waitForChecks: true,
    maxTurns: 30,
    projektorIssue: null,
  };
}
