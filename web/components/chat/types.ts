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
  uri: string;               // ui:// 资源 URI，前端按此拉取 HTML 模板（/api/ui-resources/read）
  data?: Record<string, unknown>;  // 传给 iframe 的数据（postMessage init）
  html?: string;             // 兼容字段：旧数据可能内联 html；新链路留空，按 uri 拉取
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
