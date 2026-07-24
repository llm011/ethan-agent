import type { ToolStep } from "../components/tool-timeline";

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

// 搜索结果卡片（web_search 工具产出）
export interface SearchResultCard {
  type: "search_result";
  title: string;
  url: string;
  snippet: string;
  engine: string;        // google/bing/duckduckgo/searxng/tavily/rss
  published: string;     // 新闻才有，如 "2024-01-01"
  source: string;        // RSS 来源（Google News/百度新闻）
}

// 图片卡片（image_search 工具产出）
export interface ImageCard {
  type: "image";
  title: string;
  url: string;          // 图片远程 URL
  local_path: string;   // 下载模式才有，如 "/tmp/ethan_images/img_xxx.jpg"
  source: string;       // bing images/flickr/openverse 等
  page_url: string;     // 来源页面 URL
  width: number | null;
  height: number | null;
  size_kb: number | null;
}

// 文件卡片（deliver_file 工具产出）
export interface FileCard {
  type: "file";
  filename: string;
  title?: string;
  path: string;          // 服务器本地路径（仅用于拼 /api/files URL 参数）
  size_kb: number | null;
  kind: string;          // pptx / pdf / ...
  project_dir?: string;  // pptx 项目目录（含 deck.json + pages/ 时存在，可预览）
  page_count?: number;
}

// 结构化卡片数据（web_search/image_search/deliver_file 工具产出）
export type CardData = SearchResultCard | ImageCard | FileCard;

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
  mcpApps?: McpApp[];  // 工具 UI 资源，前端按 uri 拉取模板后在 iframe 沙箱渲染
  images?: PendingFile[];  // 发送时附带的图片
  matchedSkills?: SkillMatch[];  // 本次对话命中的 Skill 列表，用于可视化
  cards?: CardData[];  // 结构化卡片数据（web_search/image_search 产出）
}
