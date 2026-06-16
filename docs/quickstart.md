# 快速上手

## 安装

需要 Python 3.12+：

```bash
pip3 install ethan-agent
```

设置 API Key：

```bash
# Anthropic Claude
ethan provider set anthropic --api-key sk-ant-xxx

# 或 OpenAI 兼容 API（Gemini / OpenRouter / Ollama 等）
ethan provider set openai_compat --api-key sk-xxx --base-url https://api.example.com/v1
```

启动：

```bash
ethan
```

首次运行自动初始化 `~/.ethan/`。

---

## 对话

打开 Web UI（http://localhost:3000），在底部输入框输入消息，按 Enter 发送。

Ethan 会根据消息长度和内容自动选择推理路径：

- **短指令**（12 字以内）或触发了某个技能的消息 → fast 路径，响应最快
- **中等长度**（80 字以内）→ medium 路径，使用全部工具，最多 4 轮工具调用
- **复杂任务** → full 路径，最多 10 轮工具调用

对话历史会自动保存。下次打开时可以在左侧 **Sessions** 列表中找到之前的会话，点击即可继续。

---

## 定时任务

### 在对话中创建

直接用自然语言告诉 Ethan：

```
每天早上 8 点提醒我喝水
每小时检查一下服务器状态
```

Ethan 会调用内置的 `schedule_create` 工具，将任务写入 SQLite，重启后也不会丢失。

### 在 Web UI 中管理

点击左侧导航的 **Scheduler**，可以查看所有定时任务，暂停、恢复或删除某个任务。

### heartbeat.md

`~/.ethan/system/heartbeat.md` 是一个特殊文件，用自然语言描述你希望 Ethan 周期性执行的任务。心跳系统会定期读取这个文件并执行其中的任务。例如：

```markdown
每天总结今天的待办事项完成情况。
每周一早上生成本周的工作计划。
```

---

## 知识库

知识库支持语义向量搜索，适合存放参考资料、文档片段、笔记等。

### 添加内容

在 Web UI 左侧点击 **Knowledge**，然后：

1. 点击 **Add** 按钮
2. 粘贴文本内容，或上传文件
3. 填写标题和标签（可选）
4. 保存

也可以在对话中让 Ethan 帮你添加：

```
把这段内容存到知识库：[内容]
```

### 搜索

在 Knowledge 页面的搜索框输入关键词，系统会用向量相似度检索最相关的条目。

对话中，当 Ethan 判断需要参考知识库时，会自动调用 `knowledge_search` 工具——无需手动触发。

---

## Skills（技能）

Skills 是注入系统提示的 Markdown 片段，当用户消息匹配到触发词时自动生效。

### 查看现有技能

在 Web UI 左侧点击 **Skills**，可以看到所有内置和用户自定义的技能，包括每个技能的触发词、命中次数等。

### 创建新技能

**方式一：在对话中创建**

```
帮我创建一个技能，触发词是"部署"，内容是我们团队的部署检查清单：[内容]
```

Ethan 会调用 `skill_create` 工具，自动写入 `~/.ethan/skills/`。

**方式二：手动创建文件**

在 `~/.ethan/skills/` 下新建目录，创建 `SKILL.md`：

```markdown
---
name: deploy-checklist
trigger: deploy|部署|上线
description: 部署前检查清单
fast_path: false
---

部署前请确认：
1. 所有测试通过
2. 没有未提交的代码
3. 已通知相关同学
```

**方式三：在 Web UI 中创建**

在 Skills 页面点击 **New Skill**，填写表单后保存。

### 技能自动进化

当你纠正 Ethan 的回答时，纠正内容会被记录到对应技能的 corrections 里。当积累的纠正达到阈值（默认 2 条）后，心跳任务会自动用廉价模型将纠正合并进技能内容，技能会越用越准。

---

## 通过 API 对话（completions 接口）

Ethan 提供兼容的 HTTP API，可以用任何 HTTP 客户端或脚本调用。

### 前提：创建 API Key

在 Web UI 的 **Settings → API Keys** 中生成一个 Token。

### 发起对话请求

```bash
curl -X POST http://localhost:8900/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "messages": [{"role": "user", "content": "今天天气怎么样？"}],
    "stream": false
  }'
```

返回示例：

```json
{
  "content": "我没有实时天气数据，不过可以帮你搜索一下——你在哪个城市？",
  "model": "claude-sonnet-4-6",
  "usage": {"input": 67, "output": 12, "cache": 0}
}
```

### 流式响应（SSE）

```bash
curl -X POST http://localhost:8900/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "messages": [{"role": "user", "content": "写一首关于秋天的诗"}],
    "stream": true
  }'
```

### 继续已有会话

```bash
curl -X POST http://localhost:8900/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "messages": [{"role": "user", "content": "继续刚才的话题"}],
    "session_id": "s_20260611_1753_d139",
    "stream": false
  }'
```

### 其他常用接口

```bash
GET  /health                    # 健康检查
GET  /models                    # 可用模型列表
GET  /sessions                  # 会话列表
GET  /sessions/{id}             # 会话详情 + 消息历史
GET  /skills                    # 技能列表
GET  /schedule                  # 定时任务列表
GET  /memory/facts              # 事实记忆列表
GET  /knowledge/search?q=关键词  # 知识库语义搜索
```

---

## 下一步

- [系统架构](./architecture.md) — 了解各模块的设计思路
- [记忆系统](./memory.md) — 深入了解五层记忆架构
- [技能系统](./skills.md) — 技能格式、触发机制、自动进化
- [调度器](./scheduler.md) — 定时任务的完整配置选项
- [接口层](./interface.md) — HTTP API 完整文档
