import { describe, expect, it } from "vitest";

import { parseRunRequest, shellQuote } from "../src/config";

describe("parseRunRequest", () => {
  it("uses safe dry-run defaults", () => {
    expect(parseRunRequest({ repo: "allistera/example" })).toEqual([
      {
        repo: "allistera/example",
        baseBranch: null,
        workBranch: "chore/dependency-updates",
        dryRun: true,
        openPullRequest: false,
        waitForChecks: false,
        maxTurns: 30,
      },
    ]);
  });

  it("accepts multiple write-mode repositories", () => {
    const result = parseRunRequest({
      repos: ["a/one", "b/two"],
      dryRun: false,
      workBranch: "chore/deps-2026",
      maxTurns: 12,
    });
    expect(result).toHaveLength(2);
    expect(result[1]).toMatchObject({
      repo: "b/two",
      dryRun: false,
      openPullRequest: true,
      waitForChecks: true,
      maxTurns: 12,
    });
  });

  it.each([
    [{}, "Provide repo"],
    [{ repo: "not-a-repository" }, "Invalid repository"],
    [{ repo: "a/b", workBranch: "-unsafe" }, "workBranch"],
    [{ repo: "a/b", maxTurns: 61 }, "maxTurns"],
    [{ repo: "a/b", dryRun: "yes" }, "dryRun"],
    [{ repo: "a/b", dryRun: false, openPullRequest: false }, "sandboxes are temporary"],
  ])("rejects invalid input %#", (body, message) => {
    expect(() => parseRunRequest(body)).toThrow(message);
  });
});

describe("shellQuote", () => {
  it("quotes apostrophes for a POSIX shell", () => {
    expect(shellQuote("it's-safe")).toBe("'it'\"'\"'s-safe'");
  });
});
