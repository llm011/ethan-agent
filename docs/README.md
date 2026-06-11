# Ethan Agent 文档索引

> 本文档体系随代码同步更新。每个模块都有对应的设计文档，记录架构决策和使用方式。

---

## 文档列表

| 文档 | 描述 |
|------|------|
| [架构总览](./architecture.md) | 整体系统架构、模块关系图、数据流 |
| [Agent Loop](./agent-loop.md) | 核心循环设计、参考来源、ReAct 模式详解 |
| [Provider 层](./providers.md) | 多模型接入、Anthropic / OpenAI 协议适配 |
| [工具系统](./tools.md) | Tool 抽象、注册表、执行器、6 个内置工具 |
| [记忆系统](./memory.md) | Session 持久化、三层记忆（热/温/冷）、压缩机制 |
| [Skill 系统](./skills.md) | Skill 加载、关键词匹配注入、自动生成 |
| [调度器](./scheduler.md) | 定时任务、cron + interval、SQLite 持久化 |
| [接口层](./interface.md) | REPL、HTTP API (SSE)、CLI 命令结构 |

---

## 开发进度

- [x] 阶段一：Provider 层 + 基础 Agent Loop
- [x] 阶段二：记忆系统（Session + 三层记忆 + 压缩器）
- [x] 阶段三：Skill 系统（加载 + 匹配 + 自动生成）
- [x] 阶段四：调度器（cron + interval + 持久化）
- [x] 阶段五：工具系统完善（shell + web_search + web_fetch + file）
- [x] 阶段六：Interface 层（REPL + HTTP API + SSE）
- [ ] 阶段七：ACP 协议 + 外部 Coding Agent 集成
- [ ] 阶段八：知识库系统 + 插件化接入
- [ ] 阶段九：Web UI

详细进度见 [PLAN.md](../PLAN.md)。
