export interface DocNavItem {
  slug: string;
  label: string;
}
export interface DocNavGroup {
  group: string;
  items: DocNavItem[];
}

// 两级导航，顺序和分组根据文档主题定义
export const DOC_NAV: DocNavGroup[] = [
  {
    group: "入门",
    items: [
      { slug: "architecture", label: "系统架构" },
      { slug: "providers", label: "模型 Provider" },
    ],
  },
  {
    group: "核心引擎",
    items: [
      { slug: "routing", label: "双轨推理引擎" },
      { slug: "memory", label: "记忆系统" },
      { slug: "caching", label: "Prompt Caching" },
      { slug: "heartbeat", label: "心跳机制" },
      { slug: "agent-loop", label: "Agent Loop" },
    ],
  },
  {
    group: "功能模块",
    items: [
      { slug: "skills", label: "技能系统" },
      { slug: "tools", label: "工具系统" },
      { slug: "scheduler", label: "调度器" },
      { slug: "knowledge", label: "知识库" },
    ],
  },
  {
    group: "接口层",
    items: [
      { slug: "interface", label: "API & Web UI" },
      { slug: "acp", label: "ACP 集成" },
    ],
  },
];
