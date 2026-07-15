# llm-wiki skill

来源：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/blob/main/skills/research/llm-wiki)

- 原始协议：MIT
- 原始作者：Hermes Agent (NousResearch)
- 基于：[Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- 集成日期：2025-07

## 改动

- frontmatter 增加了 `trigger` 字段以适配 ethan 的 skill 路由机制（wiki、知识库、obsidian、笔记整理等）
- 移除了 `${HERMES_HOME:-~/.hermes}/.env` 相关路径引用，简化为通用 `WIKI_PATH` 环境变量
