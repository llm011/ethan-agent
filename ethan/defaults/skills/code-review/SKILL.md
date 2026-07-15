---
name: code-review
version: 2.4.0
category: discoverable
trigger: "code review|代码审查|review代码|review一下|帮我看看代码|看下代码|审查代码|pr review|diff review|检查代码|代码质量|代码评审|代码走查|review pr|审查pr|把评论打上去|发评论|打评论|提交评论|发布评论|pr评论"
description: "对代码变更做审查：识别 bug、安全漏洞、性能问题。P0 必须修复写评论，P1 建议性评论，P2 只在总结里一句带过。用户要求 review、审查、发评论、打评论时都必须先用 skill_read 读全文。"
---

# code-review

对 PR/MR diff 做审查，发现问题并发布行内评论。

## ⚠️ 硬约束（违反即失败）

1. **只看 diff**：不 clone 仓库、不拉完整源文件、不读 diff 之外的文件。
2. **只读不写**：不编译、不运行代码、不跑测试。
3. **禁止写脚本**：绝不写 python/shell 脚本去解析 diff。不写 `python3 -c "..."`，不写 `sed -n`。读 diff 只能用 `file_read`（支持 offset + max_lines 分段读）。
4. **跳过噪音文件**（见下方完整列表）。
5. **最多 8 轮工具调用**：1 轮拉 diff + 1 轮定位 + 2 轮读 diff + 1 轮发评论 + 3 轮余量。

## 跳过这些文件（不读 diff 内容）

**数据/生成文件**：`.jsonl .csv .json .lock .snap .txt .md .rst .yaml .yml .toml .ini .cfg .conf .env .svg .png .jpg .jpeg .gif .ico .webp .mp4 .mp3 .wav .pdf .zip .tar .gz .bz2 .7z .bin .dat .db .sqlite .parquet .arrow .pkl .pickle .npy .npz .h5 .pt .pth .onnx .model`

**lockfile**：`pnpm-lock.yaml package-lock.json yarn.lock go.sum poetry.lock Cargo.lock Gemfile.lock Pipfile.lock composer.lock uv.lock`

**二进制/构建产物**：`.so .o .a .dll .dylib .exe .class .jar .war .pyc .pyo .wasm .min.js .min.css .map`

**vendored/生成代码**：`vendor/ node_modules/ dist/ build/ target/ __pycache__/ .next/ .nuxt/`

**纯格式化**：import 排序、空白变更、行尾符变更

## 流程（严格 5 步）

### 第 1 步：拉 diff 和文件列表（1 轮，3 条命令一次性跑完）

```bash
gh pr diff <N> --repo <owner/repo> > /tmp/pr_<N>.diff
gh api repos/<owner/repo>/pulls/<N>/files > /tmp/pr_<N>_files.json
gh api repos/<owner/repo>/pulls/<N> --jq '.head.sha' > /tmp/pr_<N>_sha.txt
```

不要 clone。不要 `gh pr checkout`。

### 第 2 步：选 top 2 文件 + 定位行号（1 轮，两个工具并行）

```
shell(command=jq -r '.[] | "\(.additions + .deletions)\t\(.filename)"' /tmp/pr_<N>_files.json | sort -rn | head -5)
rg_search(pattern=^diff --git, path=/tmp/pr_<N>.diff)
```

> jq 输出按改动量排序的文件列表。rg_search 输出每个文件在 diff 中的起始行号。
> 交叉比对，选出改动量最大的 2 个源码文件（跳过噪音文件），记住它们的 diff 起始行号。

### 第 3 步：读 diff 并找问题（2 轮，每个文件 1 轮）

用 `file_read` 的 **offset**（1-based 行号，与 rg_search 输出对齐）和 **max_lines** 读指定文件的 diff 块：

```
# 文件 1 在 diff 第 1 行，改动约 187 行
file_read(path=/tmp/pr_59.diff, offset=1, max_lines=200)

# 文件 2 在 diff 第 432 行，改动约 167 行
file_read(path=/tmp/pr_59.diff, offset=432, max_lines=200)
```

读完立即在脑子里找问题，不要多读一轮。

**P0 — 必须修复（写行内评论）**
- 逻辑 bug：off-by-one、空指针/nil、并发竞态、类型错误
- 安全：SQL/命令注入、硬编码密钥、路径穿越
- 数据安全：静默丢数据、不可逆操作无保护
- 关键异常被吞掉

**P1 — 建议修复（写行内评论）**
- 性能：N+1 查询、热路径重复 IO
- 可靠性：缺超时/重试、资源未释放

**P2 — 不写评论，总结里一句带过**

### 第 4 步：验证（0 轮，在脑子里做）

每条 finding 必须能说出：「什么输入 → 走哪条路径 → 什么错误」。说不出来就删掉。P0 必须是 CONFIRMED。

### 第 5 步：发评论（1 轮）

**关键：必须用单条评论 API（`/pulls/{n}/comments`），不能用批量 review API 的 `comments` 字段。** 批量 review API 不支持 `line`/`side`，会变成文件级评论。

每条评论单独 POST：

```bash
SHA=$(cat /tmp/pr_<N>_sha.txt)

# 评论 1
gh api repos/<owner/repo>/pulls/<N>/comments --method POST \
  -f body="问题描述

触发场景

建议修复" \
  -f commit_id="$SHA" \
  -f path="ethan/core/agent.py" \
  -F line=155 \
  -f side="RIGHT"

# 评论 2（如有更多，同样格式）
gh api repos/<owner/repo>/pulls/<N>/comments --method POST \
  -f body="..." -f commit_id="$SHA" -f path="..." -F line=... -f side="RIGHT"
```

发完所有行内评论后，再发一条 review 总结（不带 comments）：

```bash
gh api repos/<owner/repo>/pulls/<N>/reviews --method POST \
  -f body="整体看完了，详见行内评论。" \
  -f event="COMMENT"
```

> `path` 是文件在仓库中的相对路径（从 diff header `diff --git a/PATH b/PATH` 读取）。
> `line` 是新文件中的行号（从 `@@ +start,len @@` 读取，对应 `+` 开头的行），必须是整数。
> `side` 固定为 `"RIGHT"`（评论新文件侧）。
> **如果用批量 review API 的 `comments` 字段，`line`/`side` 会被丢弃变成文件级评论，这是错误的。**

聊天里只回一条简短总结：
> 看完了 PR N，发现 X 个 P0（已评论到行）：① 问题一 ② 问题二。其余没大问题，建议改完再合。

没有 P0 就说"没发现阻塞性问题，可以合并"。

## 语气

协作式，不是审判式。

| ❌ 避免 | ✅ 改用 |
|--------|--------|
| "这里有 bug" | "这里有个边界情况值得确认" |
| "必须改" | "建议改一下，因为..." |

## GitHub 账号

先 `gh auth status` 确认当前账号身份。多账号时用 `gh auth switch --user <账号>` 切换，用完切回。

## 评论语言

跟仓库语言一致：代码注释/commit 用中文 → 评论用中文；用英文 → 用英文。

## 纯本地 diff（无代码平台）

不发布评论，在对话里按 `📍 文件:行号` 格式输出评论列表。
