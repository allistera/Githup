import Anthropic from "@anthropic-ai/sdk";

import type { Env } from "./types";

type InferenceEnv = Pick<Env, "AI" | "AI_GATEWAY_ID" | "ANTHROPIC_API_KEY">;

export async function createAnthropicClient(env: InferenceEnv): Promise<Anthropic> {
  const baseURL = await env.AI.gateway(env.AI_GATEWAY_ID || "default").getUrl("anthropic");
  return new Anthropic({ apiKey: env.ANTHROPIC_API_KEY, baseURL });
}
