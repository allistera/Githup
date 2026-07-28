import type Anthropic from "@anthropic-ai/sdk";

import type { Env } from "./types";

const TOOL_PREFIX = "projektor__";
const TOOL_NAME_PATTERN = /^[A-Za-z0-9_-]+$/;
const MAX_RESULT_CHARS = 40_000;

interface ProjektorConfig {
  url: string;
  apiToken: string;
  accessClientId: string | null;
  accessClientSecret: string | null;
}

interface JsonRpcResponse {
  error?: {
    code?: number;
    message?: string;
    data?: unknown;
  };
  result?: unknown;
}

interface McpTool {
  name: string;
  description?: string;
  inputSchema?: {
    type?: unknown;
    properties?: unknown;
    required?: unknown;
    [key: string]: unknown;
  };
}

interface ToolsListResult {
  tools?: unknown;
}

function optionalValue(value: string | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

export function projektorConfig(env: Env): ProjektorConfig | null {
  const url = optionalValue(env.PROJEKTOR_MCP_URL);
  const apiToken = optionalValue(env.PROJEKTOR_API_TOKEN);
  const accessClientId = optionalValue(env.PROJEKTOR_ACCESS_CLIENT_ID);
  const accessClientSecret = optionalValue(env.PROJEKTOR_ACCESS_CLIENT_SECRET);

  if (!url && !apiToken && !accessClientId && !accessClientSecret) return null;
  if (!url || !apiToken) {
    throw new Error("PROJEKTOR_MCP_URL and PROJEKTOR_API_TOKEN must be configured together");
  }
  if (Boolean(accessClientId) !== Boolean(accessClientSecret)) {
    throw new Error(
      "PROJEKTOR_ACCESS_CLIENT_ID and PROJEKTOR_ACCESS_CLIENT_SECRET must be configured together",
    );
  }

  let parsedUrl: URL;
  try {
    parsedUrl = new URL(url);
  } catch {
    throw new Error("PROJEKTOR_MCP_URL must be a valid URL");
  }
  if (
    parsedUrl.protocol !== "https:" &&
    parsedUrl.hostname !== "localhost" &&
    parsedUrl.hostname !== "127.0.0.1"
  ) {
    throw new Error("PROJEKTOR_MCP_URL must use HTTPS unless it targets local development");
  }

  return {
    url: parsedUrl.toString(),
    apiToken,
    accessClientId,
    accessClientSecret,
  };
}

async function callProjektor(
  config: ProjektorConfig,
  method: string,
  params: Record<string, unknown>,
): Promise<unknown> {
  const headers = new Headers({
    Accept: "application/json",
    Authorization: `Bearer ${config.apiToken}`,
    "Content-Type": "application/json",
  });
  if (config.accessClientId && config.accessClientSecret) {
    headers.set("CF-Access-Client-Id", config.accessClientId);
    headers.set("CF-Access-Client-Secret", config.accessClientSecret);
  }

  const response = await fetch(config.url, {
    method: "POST",
    headers,
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: crypto.randomUUID(),
      method,
      params,
    }),
  });
  if (!response.ok) {
    const details = (await response.text()).slice(0, 2_000);
    throw new Error(
      `Projektor MCP request failed with HTTP ${response.status}${details ? `: ${details}` : ""}`,
    );
  }

  let payload: JsonRpcResponse;
  try {
    payload = (await response.json()) as JsonRpcResponse;
  } catch {
    throw new Error("Projektor MCP returned an invalid JSON response");
  }
  if (payload.error) {
    const code = payload.error.code === undefined ? "" : ` ${payload.error.code}`;
    const message = payload.error.message || "Unknown JSON-RPC error";
    throw new Error(`Projektor MCP error${code}: ${message}`);
  }
  if (!("result" in payload)) throw new Error("Projektor MCP response did not include a result");
  return payload.result;
}

function mcpTool(value: unknown): McpTool {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Projektor tools/list returned an invalid tool");
  }
  const tool = value as McpTool;
  if (
    typeof tool.name !== "string" ||
    !TOOL_NAME_PATTERN.test(tool.name) ||
    `${TOOL_PREFIX}${tool.name}`.length > 64
  ) {
    throw new Error(`Projektor returned an unsupported tool name: ${String(tool.name)}`);
  }
  if (tool.description !== undefined && typeof tool.description !== "string") {
    throw new Error(`Projektor tool ${tool.name} has an invalid description`);
  }
  if (!tool.inputSchema || tool.inputSchema.type !== "object") {
    throw new Error(`Projektor tool ${tool.name} does not have an object input schema`);
  }
  return tool;
}

export async function listProjektorTools(env: Env): Promise<Anthropic.Tool[]> {
  const config = projektorConfig(env);
  if (!config) return [];

  const result = (await callProjektor(config, "tools/list", {})) as ToolsListResult;
  if (!Array.isArray(result?.tools)) {
    throw new Error("Projektor tools/list response did not include a tools array");
  }
  return result.tools.map((value) => {
    const tool = mcpTool(value);
    return {
      name: `${TOOL_PREFIX}${tool.name}`,
      description: `Projektor: ${tool.description ?? tool.name}`,
      input_schema: tool.inputSchema as Anthropic.Tool.InputSchema,
    };
  });
}

export function isProjektorTool(name: string): boolean {
  return name.startsWith(TOOL_PREFIX);
}

export async function executeProjektorTool(
  env: Env,
  name: string,
  input: unknown,
): Promise<string> {
  if (!isProjektorTool(name)) throw new Error(`Not a Projektor tool: ${name}`);
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new Error("Projektor tool input must be an object");
  }
  const config = projektorConfig(env);
  if (!config) throw new Error("Projektor integration is not configured");
  const result = await callProjektor(config, "tools/call", {
    name: name.slice(TOOL_PREFIX.length),
    arguments: input as Record<string, unknown>,
  });
  const serialized = JSON.stringify(result ?? null);
  return serialized.length <= MAX_RESULT_CHARS
    ? serialized
    : `${serialized.slice(0, MAX_RESULT_CHARS)}\n… output truncated …`;
}
