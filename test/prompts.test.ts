import { describe, expect, it } from "vitest";

import { buildTaskPrompt, parseReport, SYSTEM_PROMPT } from "../src/prompts";
import type { RunParameters } from "../src/types";

const defaults: RunParameters = {
  repo: "a/b",
  baseBranch: null,
  workBranch: "chore/dependency-updates",
  dryRun: true,
  openPullRequest: false,
  waitForChecks: false,
  maxTurns: 30,
};

describe("buildTaskPrompt", () => {
  it("forbids mutations during dry runs", () => {
    const prompt = buildTaskPrompt(defaults);
    expect(prompt).toContain("DRY RUN");
    expect(prompt).toContain("Do not modify files");
    expect(prompt).toContain("STATUS:");
  });

  it("requires verification and PR checks in write mode", () => {
    const prompt = buildTaskPrompt({
      ...defaults,
      dryRun: false,
      openPullRequest: true,
      waitForChecks: true,
    });
    expect(prompt).toContain("lint, and run the complete test suite");
    expect(prompt).toContain("open_pull_request");
    expect(prompt).toContain("get_pull_request_checks");
  });

  it("treats repository contents as untrusted", () => {
    expect(SYSTEM_PROMPT).toContain("untrusted data");
  });
});

describe("parseReport", () => {
  it("extracts the final report from surrounding text", () => {
    const report = parseReport(`Done.\nSTATUS: success\nPULL_REQUEST: https://github.com/a/b/pull/1\nCHECKS: passed`);
    expect(report.STATUS).toBe("success");
    expect(report.PULL_REQUEST).toBe("https://github.com/a/b/pull/1");
    expect(report.CHECKS).toBe("passed");
    expect(report.NOTES).toBe("");
  });
});
