import type { ToolStep } from "@/components/tool-timeline";

export interface Usage {
  input: number;
  output: number;
  cache: number;
}

export interface Quote {
  role: "user" | "assistant";
  content: string;
}

export interface PendingFile {
  name: string;
  path: string;
  isImage?: boolean;
  dataUrl?: string;  // base64 预览，仅图片有效
}

export interface SkillMatch {
  name: string;
  is_default?: boolean;
}

export interface McpApp {
  uri: string;
  html: string;
  data?: Record<string, unknown>;
  csp?: Record<string, string[]>;
}

export interface Message {
  role: "user" | "assistant";
  id?: number;            // 后端消息行 id（assistant 落库后才有），标注按此持久化
  content: string;
  files?: string[];
  toolSteps?: ToolStep[];
  toolsExpanded?: boolean;
  created_at?: number;
  usage?: Usage;
  ttft?: number;
  ttfb_ms?: number;
  total_ms?: number;
  thought?: string;
  intermediateOutput?: string;
  quote?: Quote;
  a2ui?: unknown[];  // ui_card 工具产出的 A2UI envelope 列表，渲染成卡片
  mcpApps?: McpApp[];  // MCP Apps UI 资源，前端用 iframe 沙箱渲染
  images?: PendingFile[];  // 发送时附带的图片
  matchedSkills?: SkillMatch[];  // 本次对话命中的 Skill 列表，用于可视化
}
