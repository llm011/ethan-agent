# 分档推理引擎（Tiered Inference Engine）

## 核心洞察

并非所有请求都需要相同的计算资源。

向助手发出的指令天然分层：一类是极简问题（"3+5"、"现在几点"、"你好"），连工具都不需要；一类是高频、模式固定的执行性指令（"关客厅灯"、"发消息给 Alice"）；另一类是开放性的认知任务（"帮我分析这段代码"、"总结今天的会议"）。Ethan 受认知科学中**双进程理论**启发，把推理拆成几条独立轨道：

- **instant**：零工具、零记忆召回直答（算术/时间/打招呼），部分情况连 LLM 都不调
- **快轨（fast）**：低延迟、精简工具集、可选 lite 模型
- **慢轨（full）**：完整 ReAct 循环、全量工具、按需记忆召回

> **术语区分**：本文的"路由（routing）"指的是**分档推理引擎**——决定一条请求走哪条轨。它与 [Skill 系统](skills.md) 里的**语义路由器（EmbeddingRouter）**是两回事：后者决定该**注入哪个 Skill**（关键词之上的语义补召回），不决定走哪档轨。两者独立工作、互不影响。

> **历史变更**：早期版本有 `medium` 中轨（按字数分档 + 限制迭代次数）。**该档位已移除**——字数与任务复杂度不相关（"帮我搜索最新 AI 新闻" 很短但要多轮工具调用），分档只按意图信号判定。迭代上限现在统一由 `defaults.max_tool_iterations` 控制，不再分档，真正的兜底是 stuck detection。`medium_max_length` / `medium_max_iters` / `fast_max_iters` 三个配置项都已不存在。

---

## 路由决策

每轮对话开始时先做 instant 预判（`classify_instant`），未命中再由 `_get_route()` 分 fast/full。

```
输入文本
   │
   ▼
[0] instant 预判（classify_instant）
    ├─ 命中 FORCE_FULL 信号 / 需要上下文的短指令（"继续"/"重试"）→ 不走 instant
    ├─ 已命中 fast_rule（需要工具）→ 不走 instant
    ├─ 纯算术表达式 → 安全 eval 直答（零 LLM 调用）
    ├─ 时间查询 → 系统时间直答（零 LLM 调用）
    └─ 打招呼（精确匹配）→ LLM 裸答（无工具、无记忆召回、极简 system）
   │ 未命中
   ▼
[1] 是否命中强制慢轨信号？
    （"帮我写"、"分析"、"解释"、"总结"、"重构"…）
    → Yes → full（最高优先，不可绕过）
   │
   ▼
[2] 是否命中 fast_path Skill 的 trigger？（SKILL.md frontmatter fast_path: true，自动注册）
    → Yes → fast + 关联 Skill
   │
   ▼
[3] 是否命中某条 fast_rule 的关键字？（config.routing.fast_rules，纯关键字驱动，不看字数）
    → Yes → fast + 该规则声明的工具/技能
   │
   ▼
[4] 默认 → full（兜底档）
```

`_get_route()` 的值域只有 `'fast' | 'full'`。

**为什么不按字数判定**：早期版本用「命中关键词且长度 ≤ 阈值」判档，字数误杀严重——稍完整一点的指令（如"客厅的灯帮我关一下"）就掉档。现在 fast 完全由关键字/trigger 驱动，命中即视为意图明确；没有任何信号时保守走 full。

---

## instant 档

**目标：零工具、最低延迟；算术与时间类连 LLM 都不调**

| kind | 行为 | LLM 调用 |
|------|------|---------|
| `math` | AST 白名单安全 eval 直接回结果 | ❌ 无 |
| `time` | 按本地时区取系统时间直接回 | ❌ 无 |
| `greeting` | 极简 system 裸答（无工具、无记忆召回） | ✅ 有 |

安全细节：算术走 AST 节点白名单（禁函数调用/属性访问），幂运算指数上限 `10000` 且右操作数必须是字面常量，防 `2**(2**20)` 类嵌套幂 DoS；纯数字（`8080`）和数字序列（电话号码）不进 math 通道。

**不走 instant 的例外**：含 FORCE_FULL 信号、含需要上下文的短指令（"继续"/"重试"/"刚才"）、已命中 fast_rule 的（如"查天气"需要真调工具）。确认词（"好的"/"收到"）也不走 —— 它们可能是对上文动作的确认。

---

## fast 轨

**目标延迟：≤ 2 秒 TTFT（首字延迟）**

| 维度 | 配置 |
|------|------|
| 系统提示词 | soul + identity + 当前时间 + user_profile + behavioral_guidelines + 匹配到的 Skill |
| 工具集 | `fast_base_tools` + 命中规则声明的额外工具 |
| 记忆召回 | 按需 —— owner 可用 `recall_memory` 工具自行判断是否召回（见 [memory.md](memory.md)） |
| Skill 注入 | 仅注入匹配的相关 Skill |
| 推理轮次 | `defaults.max_tool_iterations`（不分档） |
| 模型 | `fast_use_lite_model: true` 时用 lite 模型；但复杂 skill（use-browser / agent-browser / computer-use）命中时仍用主模型 |
| Prompt Caching | 稳定层命中率更高，边际成本极低 |

**典型场景**：智能家居控制、快速发送飞书消息、读取配置文件、简单状态查询。

> fast 档只广播精简工具集，模型发现不够用时可调 `find_tools` 激活全部进阶工具兜底。注意：非 fast 工具若被写进 Skill 正文，会被自动激活 —— 但该机制取的是 `content[:3000]`，正文过长时工具名会滑出窗口导致静默失效，所以硬依赖的工具应直接进 `base_tools`。

### Skill 确定性管道

当 Skill 的 frontmatter 包含 `fast_path: true` 时，快轨与该 Skill 深度绑定。Agent 在极简上下文下，精确按照 Skill 中定义的操作流程执行，几乎不存在歧义和"幻觉"风险。这是最接近**确定性管道（Deterministic Pipeline）**的运行模式。

```yaml
# ~/.ethan/skills/home-assistant/SKILL.md
---
name: home-assistant
fast_path: true
trigger: "开灯|关灯|开空调|关空调|关*灯|开*灯"
---
```

---

## full 轨

**目标延迟：完整推理，不设硬性上限**

| 维度 | 配置 |
|------|------|
| 系统提示词 | 完整版：identity + soul + tools_reference + 全量 Skill 列表 |
| 工具集 | `base_tools`（full 档初始广播集）+ `find_tools` 按需激活的长尾工具 |
| 记忆召回 | 按需 `recall_memory`（工具入口，`max_items` 固定 15 条）；另有 `_build_extended_memory`（agent.py，注入增强上下文时拉最多 30 条）——两者是不同入口，30 条那条不是调 `recall_memory` 得到的 |
| 推理轮次 | `defaults.max_tool_iterations`；真正的兜底是 stuck detection |

**典型场景**：代码编写、调试、重构、长文档分析、多步骤任务规划、定时任务创建、PPT 生成。

---

## Prompt Caching 与分档的协同

系统提示词按内容变化频率分为两段：
- **稳定层**（identity + soul + tools_reference）：几乎不变，打上 `cache_control: ephemeral`，5 分钟内重复使用按 **0.1x** 价格计费
- **动态层**（当前时间 + Skill 匹配结果）：每轮更新，按正常价格计费

在高频使用场景下，每轮对话的有效输入 token 本可降低 **70-80%**。

---

## 配置

### 通过 Web 设置页

设置 → 快捷路由：管理「关键字 → 工具/技能」规则。每条规则可填触发关键字（支持通配 *）、勾选额外挂载的工具、勾选命中时强制注入的技能；顶部统一管理 Fast 档始终挂载的基础系统工具。

### 通过 config.yaml

```yaml
defaults:
  max_tool_iterations: 100       # 迭代上限，不分档（stuck detection 才是真正兜底）
  routing:
    fast_use_lite_model: true    # fast 轨用 lite 模型（省钱提速）
    fast_base_tools:             # fast 档始终挂载的基础系统工具
      - shell
      - file_read
      - file_write
      - skill_read
      - skill_list
      - find_tools
      - ui_card
    base_tools:                  # full 档初始广播集（长尾工具靠 find_tools 按需激活）
      - web_search
      - web_fetch
      - file_read
      # …（deliver_file 不在默认 base_tools 集：由 agent_factory 单独注册）
    fast_rules:                  # 关键字 → 工具/技能；命中任一关键字即走 fast（不看字数）
      - name: 智能家居控制
        keywords: ["关*灯", "开*灯", "播放音乐"]
        tools: ["shell"]                    # 在 fast_base_tools 之上额外挂载
        skills: ["home-assistant-control"]  # 命中即强制注入 prompt
```

> 配置项以 `RoutingConfig` / `DefaultsConfig`（`ethan/core/config.py`）为准。`save_config` 用 `exclude_defaults=True`，等于默认值的字段不落盘 —— 升级后自动拿到新的默认列表，无需迁移。

> 规则未命中时，模型仍可在 fast 档内调 `find_tools` 激活全部进阶工具兜底——所以规则配置只需覆盖高频确定性场景，不必穷举。

### Skill 层配置

在任意 Skill 的 `SKILL.md` frontmatter 中加入 `fast_path: true`，该 Skill 的所有 trigger 关键词同时成为快轨入口。

---

## 设计原则

1. **路由透明**：用户不需要感知走了哪条轨道，结果决定体验
2. **保守升级**：不确定时走 full；宁可慢也不能错
3. **可观测**：快轨的 TTFT 明显低于慢轨，用户可通过消息气泡底部的耗时数据感知差异
4. **渐进增强**：添加 Skill 并标记 `fast_path: true` 即可把更多场景纳入快轨，无需修改代码
5. **分档只按意图信号，不按字数**：字数与复杂度无关，误判代价高于省下的延迟
