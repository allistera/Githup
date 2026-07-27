import Anthropic from "@anthropic-ai/sdk";
import type { MessageParam, ToolResultBlockParam, ToolUseBlock } from "@anthropic-ai/sdk/resources/messages";
import { getSandbox } from "@cloudflare/sandbox";
import { WorkflowEntrypoint, type WorkflowEvent, type WorkflowStep } from "cloudflare:workers";

import { buildTaskPrompt, parseReport, SYSTEM_PROMPT } from "./prompts";
import { executeTool, prepareRepository, TOOLS } from "./tools";
import type { Env, RepositoryReport, RunParameters, ToolContext } from "./types";

interface AgentState {
  messages: MessageParam[];
  finalText: string;
  inputTokens: number;
  outputTokens: number;
  turns: number;
}

function responseText(content: Anthropic.Messages.ContentBlock[]): string {
  return content
    .filter((block): block is Anthropic.Messages.TextBlock => block.type === "text")
    .map((block) => block.text)
    .join("\n")
    .trim();
}

function resultFromState(repo: string, state: AgentState): RepositoryReport {
  const parsed = parseReport(state.finalText);
  const rawPullRequest = parsed.PULL_REQUEST.trim();
  return {
    repo,
    status: parsed.STATUS || "partial",
    ecosystems: parsed.ECOSYSTEMS || "none",
    dependenciesUpdated: parsed.DEPENDENCIES_UPDATED || "none",
    dependabotAlertsFixed: parsed.DEPENDABOT_ALERTS_FIXED || "0",
    dependabotAlertsUnfixed: parsed.DEPENDABOT_ALERTS_UNFIXED || "none",
    pullRequest: /^https:\/\/github\.com\//.test(rawPullRequest) ? rawPullRequest : null,
    checks: parsed.CHECKS || "not applicable",
    notes: parsed.NOTES || (state.turns >= 1 ? "Agent did not return a complete report" : "none"),
    turns: state.turns,
    inputTokens: state.inputTokens,
    outputTokens: state.outputTokens,
  };
}

export class RepositoryMaintenanceWorkflow extends WorkflowEntrypoint<Env, RunParameters> {
  async run(
    event: WorkflowEvent<RunParameters>,
    step: WorkflowStep,
  ): Promise<RepositoryReport> {
    const parameters = event.payload;
    const context: ToolContext = {
      env: this.env,
      parameters,
      sandboxId: `repo-${event.instanceId}`,
    };

    try {
      await step.do(
        "clone and prepare repository",
        {
          retries: { limit: 2, delay: "10 seconds", backoff: "exponential" },
          timeout: "20 minutes",
        },
        async () => prepareRepository(context),
      );

      let state: AgentState = {
        messages: [{ role: "user", content: buildTaskPrompt(parameters) }],
        finalText: "",
        inputTokens: 0,
        outputTokens: 0,
        turns: 0,
      };

      for (let turn = 0; turn < parameters.maxTurns; turn += 1) {
        const responseJson = await step.do(
          `ask Claude ${turn + 1}`,
          {
            retries: { limit: 3, delay: "5 seconds", backoff: "exponential" },
            timeout: "10 minutes",
          },
          async () => {
            const anthropic = new Anthropic({ apiKey: this.env.ANTHROPIC_API_KEY });
            const response = await anthropic.messages.create({
              model: this.env.ANTHROPIC_MODEL || "claude-sonnet-4-5",
              max_tokens: 8_192,
              system: SYSTEM_PROMPT,
              messages: state.messages,
              tools: TOOLS,
            });
            return JSON.stringify(response);
          },
        );
        const response = JSON.parse(responseJson) as Anthropic.Message;

        const finalText = responseText(response.content) || state.finalText;
        const assistantMessage: MessageParam = { role: "assistant", content: response.content };
        state = {
          messages: [...state.messages, assistantMessage],
          finalText,
          inputTokens: state.inputTokens + response.usage.input_tokens,
          outputTokens: state.outputTokens + response.usage.output_tokens,
          turns: turn + 1,
        };

        const toolUses = response.content.filter(
          (block): block is ToolUseBlock => block.type === "tool_use",
        );
        if (toolUses.length === 0) return resultFromState(parameters.repo, state);

        const toolResults: ToolResultBlockParam[] = [];
        for (let toolIndex = 0; toolIndex < toolUses.length; toolIndex += 1) {
          const toolUse = toolUses[toolIndex];
          if (!toolUse) continue;
          const result = await step.do(
            `tool ${turn + 1}.${toolIndex + 1} ${toolUse.name}`,
            {
              retries: { limit: 1, delay: "5 seconds", backoff: "constant" },
              timeout: "20 minutes",
            },
            async () => {
              try {
                return { content: await executeTool(toolUse.name, toolUse.input, context) };
              } catch (error) {
                return {
                  content: error instanceof Error ? error.message : String(error),
                  isError: true,
                };
              }
            },
          );
          toolResults.push({
            type: "tool_result",
            tool_use_id: toolUse.id,
            content: result.content,
            ...(result.isError ? { is_error: true } : {}),
          });
        }
        state = { ...state, messages: [...state.messages, { role: "user", content: toolResults }] };
      }

      return resultFromState(parameters.repo, {
        ...state,
        finalText: state.finalText || "STATUS: partial\nNOTES: Maximum agent turns reached",
      });
    } finally {
      await step.do(
        "destroy repository sandbox",
        { retries: { limit: 3, delay: "5 seconds", backoff: "exponential" } },
        async () => getSandbox(this.env.Sandbox, context.sandboxId).destroy(),
      );
    }
  }
}
