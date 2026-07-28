import { afterEach, describe, expect, it, vi } from "vitest";

import {
  executeProjektorTool,
  isProjektorTool,
  listProjektorTools,
  projektorConfig,
} from "../src/projektor";
import type { Env } from "../src/types";

function env(overrides: Partial<Env> = {}): Env {
  return {
    PROJEKTOR_MCP_URL: "https://projektor.example/mcp/workspace-id",
    PROJEKTOR_API_TOKEN: "pk_test",
    ...overrides,
  } as Env;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("projektorConfig", () => {
  it("disables the integration when no settings are present", () => {
    expect(projektorConfig({} as Env)).toBeNull();
  });

  it("rejects partial credentials", () => {
    expect(() =>
      projektorConfig({ PROJEKTOR_MCP_URL: "https://projektor.example/mcp/workspace-id" } as Env),
    ).toThrow("must be configured together");
    expect(() => projektorConfig(env({ PROJEKTOR_ACCESS_CLIENT_ID: "client-id" }))).toThrow(
      "ACCESS_CLIENT_ID",
    );
  });
});

describe("Projektor MCP tools", () => {
  it("discovers and namespaces Projektor tools", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({
        jsonrpc: "2.0",
        id: "request-id",
        result: {
          tools: [
            {
              name: "get_issue",
              description: "Get an issue",
              inputSchema: {
                type: "object",
                properties: { issueId: { type: "string" } },
                required: ["issueId"],
              },
            },
          ],
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(listProjektorTools(env())).resolves.toEqual([
      {
        name: "projektor__get_issue",
        description: "Projektor: Get an issue",
        input_schema: {
          type: "object",
          properties: { issueId: { type: "string" } },
          required: ["issueId"],
        },
      },
    ]);
    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(request.body as string)).toMatchObject({ method: "tools/list", params: {} });
    expect(new Headers(request.headers).get("Authorization")).toBe("Bearer pk_test");
  });

  it("calls the original MCP tool and includes Cloudflare Access credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({
        jsonrpc: "2.0",
        id: "request-id",
        result: { content: [{ type: "text", text: "PROJ-42" }] },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      executeProjektorTool(
        env({
          PROJEKTOR_ACCESS_CLIENT_ID: "access-id",
          PROJEKTOR_ACCESS_CLIENT_SECRET: "access-secret",
        }),
        "projektor__get_issue",
        { issueId: "PROJ-42" },
      ),
    ).resolves.toContain("PROJ-42");

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(request.headers);
    expect(headers.get("CF-Access-Client-Id")).toBe("access-id");
    expect(headers.get("CF-Access-Client-Secret")).toBe("access-secret");
    expect(JSON.parse(request.body as string)).toMatchObject({
      method: "tools/call",
      params: { name: "get_issue", arguments: { issueId: "PROJ-42" } },
    });
    expect(isProjektorTool("projektor__get_issue")).toBe(true);
    expect(isProjektorTool("bash")).toBe(false);
  });

  it("surfaces JSON-RPC failures without exposing the token", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({
          jsonrpc: "2.0",
          id: "request-id",
          error: { code: -32602, message: "Invalid arguments" },
        }),
      ),
    );

    await expect(executeProjektorTool(env(), "projektor__claim_issue", {})).rejects.toThrow(
      "Projektor MCP error -32602: Invalid arguments",
    );
  });
});
