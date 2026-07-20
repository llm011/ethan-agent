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
      { slug: "installation", label: "安装指南" },
      { slug: "quickstart", label: "快速上手" },
    ],
  },
  {
    group: "系统设计",
    items: [
      { slug: "architecture", label: "系统架构" },
      { slug: "providers", label: "模型 Provider" },
      { slug: "routing", label: "双轨路由" },
      { slug: "palantir-inspired-improvements", label: "Palantir 启发改进" },
    ],
  },
  {
    group: "核心引擎",
    items: [
      { slug: "agent-loop", label: "Agent Loop" },
      { slug: "memory", label: "记忆系统" },
      { slug: "heartbeat", label: "心跳机制" },
      { slug: "caching", label: "Prompt Caching" },
      { slug: "background-tasks", label: "后台任务" },
      { slug: "semantic-router", label: "语义路由器" },
    ],
  },
  {
    group: "功能模块",
    items: [
      { slug: "skills", label: "技能系统" },
      { slug: "tools", label: "工具系统" },
      { slug: "scheduler", label: "调度器" },
      { slug: "knowledge", label: "知识库" },
      { slug: "modes", label: "模式" },
    ],
  },
  {
    group: "浏览器控制",
    items: [
      { slug: "browser--overview", label: "总览与架构" },
      { slug: "browser--transport-protocol", label: "传输层与协议" },
      { slug: "browser--extension-internals", label: "扩展内核" },
      { slug: "browser--session-security", label: "会话/并发/安全" },
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
