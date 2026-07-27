export { Sandbox } from "@cloudflare/sandbox";
export { RepositoryMaintenanceWorkflow } from "./workflow";

import { parseRunRequest } from "./config";
import type { Env, RunRequestBody } from "./types";

function json(body: unknown, status = 200): Response {
  return Response.json(body, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

async function tokensMatch(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  const left = new Uint8Array(providedHash);
  const right = new Uint8Array(expectedHash);
  return left.every((value, index) => value === right[index]);
}

async function authenticated(request: Request, env: Env): Promise<boolean> {
  const header = request.headers.get("Authorization") ?? "";
  const provided = header.startsWith("Bearer ") ? header.slice(7) : "";
  return Boolean(env.API_TOKEN) && tokensMatch(provided, env.API_TOKEN);
}

async function createRuns(request: Request, env: Env): Promise<Response> {
  let body: RunRequestBody;
  try {
    body = await request.json<RunRequestBody>();
  } catch {
    return json({ error: "Request body must be valid JSON" }, 400);
  }

  let parameters;
  try {
    parameters = parseRunRequest(body);
  } catch (error) {
    return json({ error: error instanceof Error ? error.message : String(error) }, 400);
  }

  try {
    const instances = await Promise.all(
      parameters.map((params) =>
        env.GITHUP_WORKFLOW.create({ id: crypto.randomUUID(), params }),
      ),
    );
    return json(
      {
        runs: instances.map((instance, index) => ({
          id: instance.id,
          repo: parameters[index]?.repo,
          statusUrl: `/runs/${instance.id}`,
        })),
      },
      202,
    );
  } catch (error) {
    console.error("Could not create Workflow instances", error);
    return json({ error: "Could not create runs" }, 502);
  }
}

async function runRoute(request: Request, env: Env, id: string): Promise<Response> {
  const instance = await env.GITHUP_WORKFLOW.get(id);
  if (request.method === "GET") return json(await instance.status());
  if (request.method === "DELETE") {
    await instance.terminate();
    return json({ id, status: "terminated" });
  }
  return json({ error: "Method not allowed" }, 405);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "githup", provider: "anthropic" });
    }

    if (!(await authenticated(request, env))) {
      return json({ error: "Unauthorized" }, 401);
    }

    if (request.method === "POST" && url.pathname === "/runs") {
      return createRuns(request, env);
    }

    const match = /^\/runs\/([A-Za-z0-9_-]+)$/.exec(url.pathname);
    if (match?.[1]) return runRoute(request, env, match[1]);

    return json({ error: "Not found" }, 404);
  },
} satisfies ExportedHandler<Env>;
