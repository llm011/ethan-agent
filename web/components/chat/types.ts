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

export interface Message {
  role: "user" | "assistant";
  content: string;
  files?: string[];
  toolSteps?: ToolStep[];
  toolsExpanded?: boolean;
  created_at?: number;
  usage?: Usage;
  ttft?: number;
  thought?: string;
  quote?: Quote;
  a2ui?: unknown[];  // ui_card 工具产出的 A2UI envelope 列表，渲染成卡片
  images?: PendingFile[];  // 发送时附带的图片
  matchedSkills?: SkillMatch[];  // 本次对话命中的 Skill 列表，用于可视化
}
