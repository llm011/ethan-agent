---
name: code-review
version: 1.0.0
trigger: "code review|代码审查|review代码|review一下|帮我看看代码|看下代码|审查代码|pr review|diff review|检查代码|代码质量"
description: "对代码变更做系统性审查：识别 bug、安全漏洞、性能问题。只对 P0 级问题写评论，评论定位到具体行，语气友好协作。不依赖 GitHub/GitLab，直接读本地 diff 或文件。"
---

# code-review

对本地代码变更做系统性审查，不依赖任何代码平台。

## 使用方式

用户可以给你：
- `git diff` 输出（直接粘贴）
- 具体文件路径（让你读文件内容）
- PR 编号（用 `gh pr diff <N>` 拉 diff）
- 直接说"review 当前改动" → 自动运行 `git diff HEAD` 或 `git diff main...HEAD`

```bash
# 拿当前 working tree 改动
git diff

# 拿 staged 改动
git diff --cached

# 拿整个 feature branch 的变更
git diff main...HEAD
```

## 审查维度与优先级

### P0 — 必须修复（在 review 评论里指出）

| 维度 | 典型问题 |
|------|---------|
| **Correctness** | 逻辑 bug、off-by-one、并发竞态、空指针/nil 崩溃、类型错误 |
| **Security** | SQL/命令注入、XSS、路径穿越、硬编码密钥、不安全的反序列化、权限绕过 |
| **Data safety** | 静默丢数据、不可逆操作（无事务保护）、文件覆盖不检查 |
| **Critical error handling** | 关键路径上异常被吞掉、错误码被忽略 |

### P1 — 建议修复（review 评论里提出，但不阻塞）

| 维度 | 典型问题 |
|------|---------|
| **Performance** | N+1 查询、在热路径里做重复 IO、不必要的全量加载 |
| **Reliability** | 缺少超时/重试、资源未释放（fd、连接、锁） |
| **API design** | 接口语义不清晰、breaking change 无向后兼容 |

### P2 — 可选（不写 review 评论，最多在总结里一句话带过）

- 命名不够清晰
- 注释多余或过时
- 代码风格、格式
- 小的重构机会

**原则：P2 不出现在评论列表里，避免噪音掩盖真正的问题。**

## 评论格式

每条评论包含：
1. **定位**：`文件名:行号` 或 `文件名:起始行-结束行`
2. **一句话问题描述**（语气友好，见下方）
3. **为什么有风险**（简短说明后果）
4. **建议修复**（给出具体改法，能给代码片段最好）

示例：

```
📍 ethan/tools/builtin/shell.py:48

`output[:8000]` 这里硬截断可能把多行内容在中间截断，
导致 JSON 解析失败（如果调用方 parse stdout 的话）。

建议在换行处截断：
    if len(output) > 8000:
        output = output[:8000].rsplit("\n", 1)[0] + "\n...(truncated)"
```

## 语气指南

**目标**：协作式，而不是审判式。让对方觉得你是在帮他，不是在挑刺。

| ❌ 避免 | ✅ 改用 |
|--------|--------|
| "这里有 bug" | "这里有个边界情况值得确认一下" |
| "你应该用 X" | "可以考虑用 X，这样能避免 Y 问题" |
| "这个实现是错的" | "这里在 Z 场景下可能会..." |
| "必须改" | "建议改一下，因为..." |
| 连续指出 10 个问题 | 只列 P0，P1 简短提一两条 |

**开头**：先快速说一句整体印象（如"整体逻辑清晰，有几个点值得留意"），不要上来就列问题。

**结尾**：如果没有 P0 问题，明确说"没发现阻塞性问题，可以合并"。

## 审查流程

1. **读 diff**：先快速浏览所有改动，建立整体印象（新功能/修 bug/重构？）
2. **读上下文**：对有疑问的地方用 `file_read` 读前后 30 行，不要仅凭 diff 下结论
3. **逐维度过**：按 P0 → P1 顺序检查，记录发现
4. **去重合并**：同一文件相邻的问题合并成一条评论
5. **输出**：先写一段总体评价（2-3句），再逐条列 P0 评论，最后一句话总结

## 评论发布方式（GitHub PR）

**评论必须以用户身份发出，不能以 Claude 身份发。** `gh` CLI 默认使用用户的 GitHub auth，直接调即可。

**用 inline 评论，不用 conversation 评论**（inline 能精确定位到代码行，体验好得多）：

```bash
# 1. 先拿最新 commit sha（inline 评论必须绑定 commit）
gh api repos/{owner}/{repo}/pulls/{N} --jq '.head.sha'

# 2. 发 inline 评论（定位到具体行）
gh api repos/{owner}/{repo}/pulls/{N}/comments \
  --method POST \
  --field commit_id="<sha>" \
  --field path="src/foo.py" \
  --field line=42 \
  --field side="RIGHT" \
  --field body="这里在并发场景下可能 race，考虑加个锁？"
```

- `line` = diff 里的行号（RIGHT side = 新文件的行）
- 如果是多行范围：加 `start_line` + `start_side=RIGHT`
- 发完用 `gh pr view {N} --comments` 确认评论已出现

**没有 GitHub PR（纯本地 diff）时**：直接在对话里按评论格式输出即可，不调 API。

## 注意事项

- **不要改你没把握的东西**：看不懂业务背景时，用问句（"这里是不是假设了 X？"）而不是断言
- **不要重复 diff 已有内容**：不需要复述"这里改了 foo 函数"
- **测试代码放宽要求**：测试里的 hardcode、简化的 error handling 一般不是 P0
- **生成代码/迁移文件**：通常跳过，不做 review
