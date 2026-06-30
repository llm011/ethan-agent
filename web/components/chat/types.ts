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
}
