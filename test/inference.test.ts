import { describe, expect, it, vi } from "vitest";

import { createAnthropicClient } from "../src/inference";

describe("createAnthropicClient", () => {
  it("routes Anthropic through the configured Cloudflare AI Gateway", async () => {
    const getUrl = vi.fn().mockResolvedValue("https://gateway.example/anthropic");
    const gateway = vi.fn().mockReturnValue({ getUrl });

    const client = await createAnthropicClient({
      AI: { gateway } as unknown as Ai,
      AI_GATEWAY_ID: "githup",
      ANTHROPIC_API_KEY: "test-key",
    });

    expect(gateway).toHaveBeenCalledWith("githup");
    expect(getUrl).toHaveBeenCalledWith("anthropic");
    expect(client.baseURL).toBe("https://gateway.example/anthropic");
  });

  it("uses Cloudflare's default gateway when no gateway ID is configured", async () => {
    const gateway = vi.fn().mockReturnValue({
      getUrl: vi.fn().mockResolvedValue("https://gateway.example/anthropic"),
    });

    await createAnthropicClient({
      AI: { gateway } as unknown as Ai,
      AI_GATEWAY_ID: "",
      ANTHROPIC_API_KEY: "test-key",
    });

    expect(gateway).toHaveBeenCalledWith("default");
  });
});
