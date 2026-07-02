---
name: code-review
version: 1.0.0
trigger: "code review|代码审查|review代码|review一下|帮我看看代码|看下代码|审查代码|pr review|diff review|检查代码|代码质量"
description: "对代码变更做系统性审查：识别 bug、安全漏洞、性能问题。P0 必须修复写评论，P1 建议性评论，P2 只在总结里一句带过。评论定位到具体行，语气友好协作。支持 GitHub/GitLab/纯本地 diff。"
---

# code-review

系统性代码审查方法论：评级、语气、评论格式。**本 skill 不绑定任何平台**——它教你"怎么审"，而"从哪拿 diff"按平台选对应工具。

## ⚠️ 第一步：按平台拿 diff，不要 clone 整个仓库

看到 PR/MR 链接，先识别平台，用对应 CLI **直接拉 diff 和文件列表**。**绝不要 `git clone` / 在本地找仓库 / 跑测试**——那既慢又跑错目录。

> **本 skill 不绑定具体平台**。下面按「公开平台（GitHub/GitLab）/ 本地 / 公司内网代码平台」给思路，原理一致：拿元信息 → 拿 file list → 拿 diff → 按需拉上下文。

| 平台 | 链接特征 | 用什么 |
|------|---------|--------|
| GitHub | `github.com` | `gh pr diff <N>` / `gh api`（注意账号，见下方"GitHub 账号分工"） |
| GitLab | `*.gitlab.*` 或私有 GitLab | `glab mr diff <N>` |
| 公司内网代码平台 | 内网域名 | 该平台官方 CLI（先 `skill_list` 看有没有装对应技能，有就 `skill_read` 拿具体命令；没有就查 CLI 的 `--help`） |
| 纯本地改动 | 无链接，说"review 当前改动" | `git diff` / `git diff main...HEAD` |

**按场景取元信息 + 文件列表 + diff**（任选一个匹配的场景，不碰本地仓库）：

```bash
# GitHub
gh pr view <N> --repo <owner/repo> --json title,body,headRefOid           # 元信息 + head SHA
gh pr diff <N> --repo <owner/repo> > /tmp/pr_<N>.diff                     # 完整 diff
gh api repos/<owner/repo>/pulls/<N>/files > /tmp/pr_<N>_files.json       # 文件列表

# GitLab
glab mr view <N> -R "<owner/repo>"
glab mr diff <N> -R "<owner/repo>" > /tmp/mr_<N>.diff

# 公司内网代码平台：先 skill_list 找对应技能 → skill_read 拿命令；没装技能就直接用该平台 CLI（查 --help）
# 本地改动
git diff main...HEAD > /tmp/local.diff
git diff --name-only main...HEAD > /tmp/local_files.txt
```

**GitHub 账号分工（重要，别弄错身份）**：本机的 `gh` 登了两个账号，分工固定——
- **`jsongo`**：用来**提新 PR / push**（owner 身份）。开 PR、推分支前先 `gh auth status` 确认 active 是它，不是就 `gh auth switch --user jsongo`。
- **`ethanlyn011`**：用来 **review 和发评论**。要给别人的 PR 写评论时切到这个账号。
- gh active 账号是全局状态，切过之后记得切回，别让下一步动作用错身份。详见 memory `feedback-github-account-roles`。

## ⚠️ 大型 MR / 大 diff 的处理方式

**直接在 shell 里调 API 会被截断（shell 工具输出上限 8000 字符）。超过这个量的响应必须重定向写文件，再用 `file_read` 读。**

```bash
# 文件列表 / 完整 diff → 写临时文件 → file_read（offset + limit 分段读）
<平台命令> > /tmp/mr_<N>_files.json
<平台命令> > /tmp/mr_<N>.diff
```

**分批 review 策略**（**实质改动量**超过阈值时才分批，不是看原始文件数）：

> 触发分批的判据是**去掉噪音后的实质改动**——先按 large-diff 第 3、4 步剥掉生成物/lockfile/格式化/批量重命名，剩下「需要逐行细看的文件」若 > 10 个或累计 > 几百行才分批。原始文件数 200 但实质改动只有 8 个文件，**不分批**，直接看。

1. 先读文件列表，跳过噪音后，按**依赖顺序**排优先级（与 large-diff 第 5 步一致）：
   - 第一批：核心抽象 / 接口 / 数据模型（被别人依赖的底层改动，先读它后面才看得懂）
   - 第二批：直接调用方 / 业务逻辑（依赖第一批的改动）
   - 第三批：外围（工具函数、测试、配置、文档）
2. 每批 **3-5 个文件**，用平台命令拉单文件 diff 或 `file_read` 临时文件
3. 每批 review 完输出结论，再继续下一批
4. 最后汇总所有批次的发现，给出整体总结

> **改动量大时（diff > 几百行 / 文件 > 10 个）先读 [`references/large-diff.md`](references/large-diff.md)**：抓意图、跳噪音、机械改动只审一次、按依赖顺序读、查遗漏——大幅提效的核心方法。

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

> 下面 8 步是主流程，**第 1-7 步与 [`references/large-diff.md`](references/large-diff.md) 的 7 步方法论完全对齐**（抓意图 → 看形状 → 跳噪音 → 二分 → 按依赖读 → 外置清单 → 查遗漏），第 8 步加机器自检。小 diff 也走这套，只是每步很快过完；大 diff 时这套是提效核心。

1. **第一步：先抓意图（必做，优先级最高）**
   - 读 MR/PR 标题、描述、关联 issue、commit message，搞清楚「这个改动想干什么」
   - 这一步是后面所有判断的锚点，没有意图框架，看 diff 就是盲人摸象

2. **第二步：看 file list / stat，建立改动「形状」印象**
   - 拿到改动的「形状」：哪些文件大、哪些是重命名/移动、哪些是生成物
   - 根据文件列表决定：哪些必须看、哪些可以跳（噪音）

3. **第三步：凶狠跳过噪音**
   - 生成代码、lockfile（pnpm-lock/package-lock/go.sum）、snapshot、vendored 依赖
   - 纯格式化 / import 排序 / 自动 lint 修复
   - 数据迁移脚本里的样板
   - 区分「50 个有意义的文件」和「200 个文件」全靠这步

4. **第四步：机械改动 vs 实质改动分开（最关键）**
   - 批量替换、函数签名变更传导、API 改名 → 只审「那个模式」本身一次，再**抽查** 2-3 个调用点确认传导正确，其余同模式的不再逐个看
   - 实质逻辑改动（新算法、新分支、新状态）→ 才逐行细看
   - 先用这把尺子把改动二分，能省掉绝大部分时间

5. **第五步：按依赖顺序读核心文件**
   - 先读核心抽象/接口/数据模型的改动，再读它的调用方
   - 理解了新模型，调用点的改动一眼就懂

6. **第六步：边读边把发现外置成清单（可写到 /tmp）**
   - 维护一个「确认的问题 + 待确认疑点」清单：`file:line | P级 | 问题 | 待确认?`
   - 遇到看不懂的先记成疑点、**不停下来**——往往后面的文件就解答了，回头再划掉

7. **第七步：专门看「缺了什么」**
   - 新增代码路径没加测试
   - 该同步改的调用方漏改了（搜一下旧符号还有没有残留引用）
   - 行为变了但文档/注释没更新
   - 错误处理、边界 case 在新路径上缺失

8. **第八步：机器自检（可选但强烈推荐）**
   - **搜旧符号名残留**：重命名/API 改名后，确认没有调用方还用旧名。本地仓库：`grep -rn 'OldSymbolName' --include='*.go' .`（按语言改 include）；远程仓库用平台代码搜索（GitHub `gh api search/code -f q='OldSymbolName repo:owner/repo'`；GitLab `glab api ...`；内网代码平台用自己的搜索命令）。残留 = 该改的调用方漏改了。
   - **新分支有没有测试**：新增的入口函数/接口，确认存在对应的 `*_test.go` / `test_*.py` / `*.test.ts`；只看 diff 的话，新加的 `.go` 文件旁边有没有同名 `_test.go`。

9. **输出：先写总体评价，再逐条列评论，最后总结**

## ⚠️ 渠道适配（重要）

**在飞书 / 微信 / 聊天等即时通讯渠道里，绝不要把完整结构化报告吐进聊天框。** 那会变成一张超长卡片，又乱又难读。聊天渠道的正确做法：

1. **审查过程不要碎碎念**：不要一步步播报"我先加载规范""我这就拉 diff""正在分析…"。安静地把活干完。
2. **评论发到代码平台的具体行上**（见下方评论发布方式），不堆在聊天里。
3. **聊天里只回一条简短总结**，例如：
   > 看完了 MR 6353，发现 2 个 P0（已评论到对应代码行）：① 并发写缺锁 ② SQL 拼接有注入风险。其余没大问题，建议改完这俩再合。

**只有在桌面端 / Web / 用户明确要"完整报告"时**，才输出"整体评价 + 逐条评论 + 总结"的完整结构。

## 评论语言

- 优先**跟仓库语言一致**：代码注释、commit message 用中文 → 评论用中文；用英文 → 用英文
- 不确定时看 README 或已有 PR 评论的语言风格
- 用户明确要求某种语言时以用户为准

## 评论发布方式

**评论必须真的发到代码平台上，不要只在聊天里"口头"说哪里能优化。** 用户让你 review，默认就是要你把意见写成 MR/PR 评论。**只有用户明确说"先说给我听""别发评论"时才只在对话里讲。**

**评论以用户身份发出**（平台 CLI 默认走用户 auth）。**优先 inline 评论**（定位到具体代码行），不用笼统的整体评论。

各平台行内评论的**通用要素**都是三件：文件路径（仓库相对路径）+ 行号（diff 新文件里的行号）+ commit SHA（head）。参数名因平台而异，务必查对应技能或 `--help`，不要照搬别的平台经验。

### GitHub

```bash
gh api repos/{owner}/{repo}/pulls/{N} --jq '.head.sha'   # 拿 commit sha
# 单条行内评论
gh api repos/{owner}/{repo}/pulls/{N}/comments --method POST \
  --field commit_id="<sha>" --field path="src/foo.py" \
  --field line=42 --field side="RIGHT" \
  --field body="这里在并发场景下可能 race，考虑加个锁？"
```

**批量行内评论（推荐）**：GitHub 一次 `POST pulls/{N}/reviews` 带 `comments[]` 数组，能把多条行内评论聚成**一条 review**发出（作者只收到一个通知）。先把所有评论攒成 JSON，再一次性提交：

```bash
# 1. 把所有评论写进一个 JSON payload（用 file_write 写，别手拼）
#    每个 comment 的 line 是 diff 新文件行号，side="RIGHT"，path 仓库相对路径
cat > /tmp/pr_<N>_review.json <<'EOF'
{
  "commit_id": "<sha>",
  "body": "整体看完了，有几点值得留意（见行内评论）。",
  "event": "COMMENT",
  "comments": [
    {"path":"src/foo.py","line":42,"side":"RIGHT","body":"这里 race，考虑加个锁？"},
    {"path":"src/bar.py","line":88,"side":"RIGHT","body":"这里 N+1 查询，可以批量取。"}
  ]
}
EOF
# 2. 一次提交全部行内评论
gh api repos/{owner}/{repo}/pulls/{N}/reviews --method POST --input /tmp/pr_<N>_review.json
```

### GitLab

`glab mr note <N> -m "..."` 发整体评论；行内评论走 API 的 discussions（绑定 file path + line + commit SHA），参数名和 GitHub 不同，先查 `glab api --help` 或 GitLab 文档。

### 公司内网代码平台

各公司有自己的代码平台 CLI。**先 `skill_list` 看本机有没有装对应平台的技能**：
- 有 → `skill_read(name="<技能名>")` 读具体命令、行内评论的参数名和已知坑（内网平台常有自己的 draft/publish 两步流程、特定的 position 字段名，这些细节写在该技能里，不在这里重复）
- 没有 → 直接用该平台 CLI，查 `--help`，按「文件路径 + 行号 + commit SHA」三要素找对应参数

内网平台行内评论最容易踩的坑是**字段名**：同是「文件路径」，GitHub 叫 `path`、GitLab 叫 `new_path`、内网平台可能叫别的名字。传错字段通常**不会报错而是静默降级**成普通评论（不挂行）。所以发完一定要用 list 命令回查「评论有没有真挂到行上」，别发完就走。

### 纯本地 diff（无代码平台）

才在对话里按"📍 文件:行号"格式输出评论列表。

## 注意事项

- **不要改你没把握的东西**：看不懂业务背景时，用问句（"这里是不是假设了 X？"）而不是断言
- **不要重复 diff 已有内容**：不需要复述"这里改了 foo 函数"
- **测试代码放宽要求**：测试里的 hardcode、简化的 error handling 一般不是 P0
- **生成代码/迁移文件**：通常跳过，不做 review
