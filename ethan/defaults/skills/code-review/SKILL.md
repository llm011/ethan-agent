---
name: code-review
version: 2.8.0
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
5. **按文件数分档预算，分批 review**（不设固定总轮次，但每文件只读 1 轮）：

   | 值得 review 的文件数 | 策略 | 预算 |
   |---------------------|------|------|
   | 1-2 个 | 一次性读完发评论 | ~6 轮 |
   | 3-6 个 | 分批，每批 2-3 文件，每批走完「拉 diff → 读 → 发评论」 | ~10-15 轮 |
   | 7+ 个 | 走 `references/large-diff.md` 方法论，只看实质改动 | 按需 |

   **失败信号**（不是轮次硬上限，是行为红线）：
   - 连续 3 轮没新发现 → 停止，发已发现的评论
   - 开始 clone 仓库补上下文 → 失败（见「禁止 clone」）
   - 同一文件读第 2 轮 → 失败（读完立即判断，不回头）

6. **GitHub 链接必须先用 `gh`**：看到 github.com / PR / issue 链接，**第一反应用 `gh` CLI**，不许先 `web_fetch`。`gh` 不可用（未装/未认证）才降级。**禁止用 `web_search` 搜 GitHub PR/issue**——搜索引擎搜不到 PR 内容，404 也不许搜。

## 🚫 禁止 clone（硬约束第 1 条展开，违反即失败）

**绝不 clone 仓库。绝不 `git checkout` PR 分支。绝不读 diff 之外的源文件。**

diff 已经包含所有判断所需的信息——`@@ +start,len @@` 标注新文件行号，`diff --git a/PATH b/PATH` 给出文件路径。看不到上下文不是 clone 的理由，是「跳过这个 finding」的理由。

### ❌ 禁止行为

| ❌ 禁止 | 为什么 |
|--------|--------|
| `git clone https://github.com/owner/repo.git /tmp/...` | 第 1 条硬约束，且会拉一堆无关文件 |
| `git fetch origin pull/N/head && git checkout pr-N` | 同上，等价于 clone |
| `file_read(path=/tmp/clone-repo/scripts/foo.py)` | 读 diff 之外的源文件，违反第 1 条 |
| `cd /tmp/clone-repo && git diff origin/main pr-N -- foo.py` | 用 `git diff` 代替 `file_read` 读 diff，违反第 3 条 |
| 「上下文不够，clone 一下看看」 | 上下文不够 → 跳过这个 finding，不 clone |

### ✅ diff 看不懂时怎么办

- 行号对应看不清 → 用 `rg_search(pattern=^@@.*@@, path=/tmp/pr_<N>.diff)` 列出所有 hunk 起止
- 改动函数签名不确定 → 跳过这个 finding，P2 在总结里一句带过
- 想确认调用方有没有残留 → `gh api search/code -f q='OldName repo:owner/repo'`（这是搜索，不是 clone）

## 🥇 GitHub 访问策略（看到 GitHub 链接先读这段）

**优先级：`gh` CLI > `web_fetch`(.diff) > 停止并提示用户**

### 第 0 步：解析 URL + 检查 gh（每次必做，1 轮）

从用户给的 GitHub 链接解析出 `owner/repo` 和 PR 号：
- `https://github.com/<owner>/<repo>/pull/<N>` → owner/repo + N
- `https://github.com/<owner>/<repo>/pull/<N>/files` → 同上
- 只有 PR 号没有仓库 → 问用户要 owner/repo，**不要猜、不要搜**

然后检查 `gh` 是否可用：

```bash
gh auth status 2>&1 | head -5
```

### 情况 A：`gh` 可用（正常路径，99% 的情况）

直接进入「流程 第 1 步」，用 `gh pr diff` / `gh api` 拉 diff。**不要碰 `web_fetch`**。

### 情况 B：`gh` 未装或未认证（降级路径）

- **未装**：提示用户安装 `gh`，或降级 `web_fetch`（见下）。
- **未认证**（`gh auth status` 报错）：**先提示用户 `gh auth login`**。私有仓库 `web_fetch` 必 404，别浪费时间。
- 降级 `web_fetch` 只能抓公开仓库的 diff 原始文本：
  ```
  web_fetch(url=https://github.com/<owner>/<repo>/pull/<N>.diff)
  ```
  - 拿到 diff 文本后存到 `/tmp/pr_<N>.diff`，后续流程同 `gh` 路径。
  - **`web_fetch` 404 = 私有仓库或 PR 不存在** → 停止，告诉用户：「这个 PR 可能是私有仓库，需要先 `gh auth login` 认证。」**不许 `web_search`。**

### 禁止行为

| ❌ 禁止 | ✅ 应该 |
|--------|--------|
| `web_fetch` 抓 github.com/.../pull/16 页面 HTML | `gh pr diff 16 --repo owner/repo` |
| `web_search` 搜 `site:github.com owner repo pull 16` | `gh api repos/owner/repo/pulls/16` |
| `web_fetch` 抓 `.diff` 之前不试 `gh` | 先 `gh auth status`，可用就走 `gh` |
| 404 后 `web_search` 找「PR 信息」 | 404 → 告诉用户需要 `gh auth login` |

## 跳过这些文件（不读 diff 内容）

**数据/生成文件**：`.jsonl .csv .json .lock .snap .txt .md .rst .yaml .yml .toml .ini .cfg .conf .env .svg .png .jpg .jpeg .gif .ico .webp .mp4 .mp3 .wav .pdf .zip .tar .gz .bz2 .7z .bin .dat .db .sqlite .parquet .arrow .pkl .pickle .npy .npz .h5 .pt .pth .onnx .model`

**lockfile**：`pnpm-lock.yaml package-lock.json yarn.lock go.sum poetry.lock Cargo.lock Gemfile.lock Pipfile.lock composer.lock uv.lock`

**二进制/构建产物**：`.so .o .a .dll .dylib .exe .class .jar .war .pyc .pyo .wasm .min.js .min.css .map`

**vendored/生成代码**：`vendor/ node_modules/ dist/ build/ target/ __pycache__/ .next/ .nuxt/`

**纯格式化**：import 排序、空白变更、行尾符变更

## 流程（严格 6 步）

### 第 1 步：拉文件列表 + sha（1 轮，2 条命令并行）

```bash
gh api repos/<owner/repo>/pulls/<N>/files > /tmp/pr_<N>_files.json
gh api repos/<owner/repo>/pulls/<N> --jq '.head.sha' > /tmp/pr_<N>_sha.txt
```

不要 clone。不要 `gh pr checkout`。**先不拉全量 diff**——先看清单值不值得拉。

### 第 2 步：筛选值得 review 的文件（1 轮）

```bash
# 值得 review 的文件（排除 deleted + 噪音扩展名）
jq -r '.[] | select(.status != "removed") | select(.filename | test("\\.(pkl|pickle|jsonl|csv|json|lock|snap|md|rst|yaml|yml|toml|ini|cfg|conf|env|svg|png|jpg|jpeg|gif|ico|webp|mp4|mp3|wav|pdf|zip|tar|gz|bz2|7z|bin|dat|db|sqlite|parquet|arrow|npy|npz|h5|pt|pth|onnx|model|so|o|a|dll|dylib|exe|class|jar|war|pyc|pyo|wasm|min\\.js|min\\.css|map)$") | not) | "\(.status)\t\(.additions)+\(.deletions)-\t\(.filename)"' /tmp/pr_<N>_files.json

# 被删除的文件（不读 diff，但删了函数/类要查残留引用）
jq -r '.[] | select(.status == "removed") | "deleted\t\(.filename)"' /tmp/pr_<N>_files.json
```

看清单后决定：

| 清单状态 | 动作 |
|---------|------|
| 值得 review 的清单为空 + 无 deleted | 回「无可 review 的源码改动」，结束 |
| 值得 review 的清单为空 + 有 deleted | 只查残留引用（见 `references/large-diff.md` #8），不读 diff |
| 1-2 个值得 review | 一次性走第 3-6 步，全部读完发评论 |
| 3-6 个值得 review | **分批**：按改动量排序，每批 2-3 个文件，每批走完第 3-6 步（拉 diff → 读 → 发评论），发完一批继续下一批 |
| 7+ 个值得 review | 读 `references/large-diff.md` 方法论，只看实质改动，机械改动（重命名/签名变更）只抽查 2-3 个调用点 |

> 被删除的文件里如果有函数/类被删，review 完后搜一下旧符号有没有残留引用（`gh api search/code` 或本地 grep）。这步可选，P1 级别。

### 第 3 步：拉 diff + 定位行号（1 轮，2 条命令并行）

```bash
gh pr diff <N> --repo <owner/repo> > /tmp/pr_<N>.diff
rg_search(pattern=^diff --git, path=/tmp/pr_<N>.diff)
```

> rg_search 输出每个文件在 diff 中的起始行号。
> 交叉比对第 2 步选出的本批文件，记住它们的 diff 起始行号。
> **`rg_search` 必须传 `path` 参数**，不传会全盘扫描导致超时。

### 第 4 步：读 diff 并找问题（每文件 1 轮）

用 `file_read` 的 **offset**（1-based 行号，与 rg_search 输出对齐）和 **max_lines** 读指定文件的 diff 块：

```
# 文件 1 在 diff 第 1 行，改动约 187 行
file_read(path=/tmp/pr_59.diff, offset=1, max_lines=200)

# 文件 2 在 diff 第 432 行，改动约 167 行
file_read(path=/tmp/pr_59.diff, offset=432, max_lines=200)
```

读完立即在脑子里找问题，不要多读一轮。本批所有文件读完进入第 5 步。

**P0 — 必须修复（写行内评论）**
- 逻辑 bug：off-by-one、空指针/nil、并发竞态、类型错误
- 安全：SQL/命令注入、硬编码密钥、路径穿越
- 数据安全：静默丢数据、不可逆操作无保护
- 关键异常被吞掉

**P1 — 建议修复（写行内评论）**
- 性能：N+1 查询、热路径重复 IO
- 可靠性：缺超时/重试、资源未释放

**P2 — 不写评论，总结里一句带过**

### 第 5 步：验证（0 轮，在脑子里做）

每条 finding 必须能说出：「什么输入 → 走哪条路径 → 什么错误」。说不出来就删掉。P0 必须是 CONFIRMED。

### 第 6 步：发评论（1 轮）

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
