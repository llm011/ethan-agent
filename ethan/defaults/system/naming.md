# 对话命名规则

标题 ≤ 20 字，只输出标题本身，不加引号、标点或 emoji。
命中下表任一类型时，**按模板原样套用**，不要自行发挥。

## 按类型套用（命中即用，优先级从高到低）

| 场景 | 触发特征 | 标题模板 | 示例 |
|------|----------|----------|------|
| Review PR | 出现 GitHub PR 链接 `github.com/<owner>/<repo>/pull/<n>` 或 `/review` | `#<编号> <owner>/<repo> code review` | `#100 llm011/ethan-agent code review` |
| Review MR | 出现 GitLab MR 链接 `.../-/merge_requests/<n>` | `!<编号> <owner>/<repo> code review` | `!42 larksuite/cli code review` |
| Review 本地/分支 | `/review` + 分支名或无链接 | `<分支名> code review` | `feature/login code review` |
| 修 bug | 用户描述报错/异常/不生效 | `fix: <问题一句话>` | `fix: 侧边栏标题不更新` |
| 新功能/需求 | 用户要做某个功能 | `<需求一句话>` | `支持会话标题规则` |
| 排查/调研 | 只问为什么怎么工作 | `<问题一句话>` | `watchdog 如何重启服务` |
| 其余 | 以上都不匹配 | 概括用户核心诉求 | — |

`<owner>/<repo>` 取 PR/MR 地址的**最后两段**（如 `github.com/llm011/ethan-agent/pull/100` → `llm011/ethan-agent`）。
`<编号>` 只保留数字（`#100`，不要 `#pull/100`）。

## 通用要求

1. 用中文概括，技术名词（PR/review/fix/分支名/仓库名）保留原文。
2. 不要照抄用户首句、不要用"关于/讨论/聊天/求助"这类空词。
3. 同一会话后续补充的信息，若标题已符合规则则不必改动。
