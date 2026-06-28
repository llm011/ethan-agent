# 对话模式（Mode）

「模式」是一个命名的人格 / 工作态。切到某模式后，Agent 的身份、可用技能、记忆抽取行为都会随之改变；切回默认（工作助手）则一切恢复常态。模式是数据驱动的——内核只认 [`ethan/core/modes.py`](../ethan/core/modes.py) 里的 `MODES` 表，不认任何具体人格，新增一个垂类模式 = 往表里加一条数据。

## 内置模式

| key | 别名 | 说明 |
|-----|------|------|
| （空） | — | 默认「工作助手」 |
| `陪伴` | counselor / 苏念 | 苏念 · 陪伴倾听（人格覆盖，熟读《臣服实验》） |
| `法律` | legal / 法律专家 / 法务 | 法律专家（依赖外部技能 `legal-assistant`，按需安装） |

## Mode 的字段（modes.py）

| 字段 | 作用 |
|------|------|
| `key` / `aliases` | 规范名 + 可解析别名（持久化用 key） |
| `label` / `icon` / `accent` / `blurb` | UI 展示（Web 下拉、胶囊配色、提示语） |
| `persona_skills` | 人格正文来自哪个 skill（如苏念）；扮演型模式用 |
| `identity` | **模式级身份覆盖**：进模式即注入，不依赖触发词。用于工具型模式声明专业身份（如法律模式声明「执业律师助手」），避免被默认人设/记忆带偏 |
| `requires_skill` / `install_source` / `install_alias` | 该模式依赖的技能、安装来源、`ethan skill add` 友好别名 |
| `extract_psych` | 记忆抽取时是否额外抽心理画像 |

## 怎么切换

- **Web**：输入框旁的模式下拉，选「⚖️ 法律专家」等即可；切换即持久化到当前会话，刷新/重进保持。
- **CLI / 飞书等渠道**：`/mode 法律` 切入、`/mode default` 切回默认。模式名无法识别时**保持当前模式不变**（不会误切回默认）。
- 模式存在会话上（`sessions.mode`），`/resume`、新建会话、跨渠道都会还原。

## 技能与模式的关系（零污染）

Skill 的 frontmatter 可声明 `modes: [法律]`：

- **模式专属**（modes 非空）：只在所列模式生效，且**一旦处于该模式就无条件命中**（用户显式切模式即最强意图信号，不再卡触发词）；其它模式完全不出现。
- **通用**（modes 为空）：所有模式可用，按触发词关键词匹配。
- `modes` 里写规范 key（`法律`）或别名（`legal`）都行——匹配时会归一化。

## 依赖外部技能的模式：按需安装体验

法律模式依赖的 `legal-assistant` 技能**不随主仓库分发**（改写自第三方 CC-BY-NC 内容），托管在独立公开仓库 [`llm011/ethan-legal-skill`](https://github.com/llm011/ethan-legal-skill)。接入体验遵循「自动安装 + 可见反馈 + 失败兜底」：

1. **自动安装**：首次切到法律模式（强意图）就自动 `install_skill` 拉取，不再先问一轮。
2. **可见反馈**：安装前先告知「正在为法律模式安装技能…」，不静默联网（符合「副作用可见」原则）。
3. **失败兜底**：离线 / 代理不通装失败时，提示手动 `ethan skill add legal` 后重试。

> 手动安装：`ethan skill add legal`（= `llm011/ethan-legal-skill/skills/legal-assistant`）。docker 下可设 `ETHAN_INSTALL_SKILLS=legal` 在 `docker compose up` 时自动装。

## 新增一个垂类模式（给开发者）

1. 在 `MODES` 加一条 `Mode(...)`，填 key / aliases / label / icon / accent / blurb。
2. 扮演型 → 配 `persona_skills` 指向人格 skill；工具型 → 配 `identity` 声明专业身份。
3. 若依赖外部技能 → 配 `requires_skill` + `install_source` + `install_alias`，按需安装链路自动生效。
4. 技能本体若含第三方内容，托管到独立公开仓库，**不要内置进主仓库**。

这样 Web 下拉、`/mode` 命令、技能过滤、按需安装全都自动适配，无需改 agent / 前端。
