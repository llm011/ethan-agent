# arxiv skill

来源：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/tree/main/skills/research/arxiv)

- 原始协议：MIT
- 原始作者：Hermes Agent (NousResearch)
- 集成日期：2025-07

## 改动

- frontmatter 增加了 `trigger` 字段以适配 ethan 的 skill 路由机制
- `scripts/search_arxiv.py` User-Agent 从 `HermesAgent/1.0` 改为 `EthanAgent/1.0`
- 去除了原文中的 `{% raw %}` / `{% endraw %}` Jekyll 模板标签
