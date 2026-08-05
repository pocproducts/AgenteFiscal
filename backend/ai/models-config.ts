export const DEFAULT_CHAT_MODEL = "moonshotai/kimi-k2.5";

export const titleModel = {
  id: "moonshotai/kimi-k2.5",
  name: "Kimi K2.5",
  provider: "moonshotai",
  description: "Fast model for title generation",
  gatewayOrder: ["fireworks", "bedrock"],
};

export type ModelCapabilities = {
  tools: boolean;
  vision: boolean;
  reasoning: boolean;
};

export type ChatModel = {
  id: string;
  name: string;
  provider: string;
  description: string;
  gatewayOrder?: string[];
  reasoningEffort?: "none" | "minimal" | "low" | "medium" | "high";
};

export const chatModels: ChatModel[] = [
  {
    id: "deepseek/deepseek-v3.2",
    name: "DeepSeek V3.2",
    provider: "deepseek",
    description: "Fast and capable model with tool use",
    gatewayOrder: ["bedrock", "deepinfra"],
  },
  {
    id: "moonshotai/kimi-k2.5",
    name: "Kimi K2.5",
    provider: "moonshotai",
    description: "Moonshot AI flagship model",
    gatewayOrder: ["fireworks", "bedrock"],
  },
  {
    id: "openai/gpt-oss-20b",
    name: "GPT OSS 20B",
    provider: "openai",
    description: "Compact reasoning model",
    gatewayOrder: ["groq", "bedrock"],
    reasoningEffort: "low",
  },
  {
    id: "openai/gpt-oss-120b",
    name: "GPT OSS 120B",
    provider: "openai",
    description: "Open-source 120B parameter model",
    gatewayOrder: ["fireworks", "bedrock"],
    reasoningEffort: "low",
  },
  {
    id: "xai/grok-4.1-fast-non-reasoning",
    name: "Grok 4.1 Fast",
    provider: "xai",
    description: "Fast non-reasoning model with tool use",
    gatewayOrder: ["xai"],
  },
];
