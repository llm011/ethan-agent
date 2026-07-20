---
name: rss-briefing
description: >
  TRIGGER WHEN: 用户提到"每日简报"、"RSS 简报"、"早报"、"晚报"、"新闻汇总"或要求抓取订阅的 RSS 资讯时。
  抓取、去重并深度提炼订阅源中的最新文章，生成符合飞书排版规范的中文化简报。
version: 4.0.0
author: Ethan Agent
license: MIT
trigger:
  - 每日简报
  - RSS 简报
  - 早报
  - 晚报
  - 新闻汇总
  - rss briefing
platforms: [linux, macos, windows]
metadata:
  ethan:
    tags: [RSS, News, Briefing, Feishu, Fetch]
source: internal (hermes agent)
---

# RSS 深度简报助手 (RSS Briefing)

本技能用于自动执行或按需抓取 RSS 订阅内容，并进行深度提炼。

## 🛡️ 核心工作流 (Workflow)

### 1. 抓取与预处理 (Fetch & Deduplicate)
- **执行指令**: `python3 scripts/run_briefing.py`
- **核心逻辑**: 脚本会自动读取 `rss_sources.json`，根据 URL 哈希进行增量去重，只抓取未读的新鲜资讯。
- **输出**: 脚本会输出 `-----START_RAW_BRIEFING-----` 标记之间的原始资讯列表（stdout），错误信息走 stderr。

### 2. AI 深度提炼与翻译 (Synthesis & Translation)
智能体捕获到原始资讯后，必须执行以下 SOP：
1. **全量翻译**: 无论原始文章是何种语言，最终简报必须**全部翻译为中文**。
2. **深度提炼**: 每个条目的"核心观点"必须包含至少 2-3 句详细、有洞见的中文总结。
3. **格式化**: 按照下方定义的"飞书安全排版"进行输出。

## 🌐 代理配置 (Proxy)

很多海外 RSS 源（openai.com、anthropic.com、huggingface.co 等）在境内直连不可达，必须走代理。脚本通过环境变量读取代理，**不要在代码里硬编码**。

### Mac mini / macOS 主机
```bash
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
export ALL_PROXY=http://127.0.0.1:7890
python3 scripts/run_briefing.py
```

### Docker 容器（宿主机代理）
Docker 容器内访问宿主机代理，必须用 `host.docker.internal`：
```bash
# docker run 时注入
docker run -e HTTPS_PROXY=http://host.docker.internal:7890 \
           -e HTTP_PROXY=http://host.docker.internal:7890 \
           -e ALL_PROXY=http://host.docker.internal:7890 \
           ...
```

### 优先级
`HTTPS_PROXY` > `HTTP_PROXY` > `ALL_PROXY`；三个都没设置时脚本走直连。

### 不需要代理时
```bash
unset HTTPS_PROXY HTTP_PROXY ALL_PROXY
python3 scripts/run_briefing.py
```

## 📅 定时任务建议
- **晨报**: 09:00 (获取昨日深夜至今晨的动态)
- **晚报**: 21:00 (获取今日日间的重点动态)

## 避坑指南 (Gotchas)

- **排版铁律**: 严禁使用 Markdown 链接格式 `[标题](链接)`，飞书会将其折叠或解析失败。必须使用**标题与链接分行显示**的格式（见下方示例）。
- **去重机制**: 脚本依赖 `rss_sent_hashes.json`，位置按优先级：`$ETHAN_MEMORY_DIR` → `~/.ethan/memory/` → 技能内置 `memory/`。如果想重新获取之前的文章，需要物理清理该 JSON 文件。
- **SSL 证书**: 脚本已内置 `CERT_NONE` 绕过，通常不需要担心 HTTPS 握手失败。注意这会带来中间人风险，仅在受信任的网络/代理环境下使用。
- **失败排查**: 抓取失败的信息会以 `✗ <源名> | <URL> | <错误类型>: <原因>` 的格式输出到 stderr，便于定位是哪个源、什么原因（HTTP 4xx/5xx、超时、SSL、XML 解析等）。
- **失效源**: `nitter.net` 系列源在 2024-2025 陆续失效，参见 `references/sources.md` 的"已知失效源"。

## 飞书安全排版示例 (Feishu-Safe Format)

```markdown
### 🏛️ 【订阅源名称】

**[中文标题]**
- https://example.com/raw-url
> 💡 核心观点：[此处为 2-3 句深度、详细的中文提炼，阐述文章核心价值...]

---
```

## 渐进式参考 (References)
- **管理订阅源**: 详见 `references/sources.md`。
- **调试单源**: 见 references 中提供的 curl 命令模板。
