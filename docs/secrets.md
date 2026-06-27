# 密钥管理设计文档

## 概述

Ethan 需要调用各种外部服务（Home Assistant、Get笔记、图片生成等），这些都要 API key / token / 密码。本文档说明这些密钥**存在哪、怎么取用、怎么防止泄漏给模型或被套出来**。

核心原则：

1. **密钥永不进代码仓库** —— 一律放在 `~/.ethan/.secrets/`，该目录不在仓库工作区内。
2. **密钥尽量不进模型上下文** —— 首选让模型"用得到但看不到"：值注入到 shell 子进程环境，模型只写 `$KEY`。
3. **多一层安全网** —— 即便密钥因 `echo $KEY` 等回流进工具输出，也会在进入模型上下文前被掩码。

---

## 存储：`~/.ethan/.secrets/`

| 项 | 说明 |
|----|------|
| 目录 | `~/.ethan/.secrets/`，权限 `0700` |
| 文件权限 | `0600`（仅本人可读写） |
| 是否进仓库 | 否。位于用户配置目录，与代码仓库（`ethan/`）物理隔离 |

支持两种文件格式：

### 1. `*.env` 文件（推荐，会注入 shell 子进程）

形如 `~/.ethan/.secrets/getnote.env`：

```
GETNOTE_API_KEY="gk_live_xxx"
GETNOTE_CLIENT_ID="cli_xxx"
```

- 每行 `KEY="value"`（引号可选）。`#` 开头是注释。
- 运行 `shell` 工具时，所有 `*.env` 的键值对会被合并注入到子进程环境（见下）。

### 2. 单值文件（用 `get_secret` 取）

形如 `~/.ethan/.secrets/ha.env`、`image_generate_token`。整个文件内容就是密钥值，模型通过 `get_secret` 工具按名读取（需用户授权）。

---

## 取用方式

### 方式一：env 注入子进程（推荐，最快）

`shell` 工具在执行命令前，会把 `.secrets/*.env` 的键值对注入子进程环境（`ethan/tools/builtin/shell.py` → `ethan/core/secrets_store.py::load_secret_env`）。

所以脚本 / curl 命令里**直接用 `$KEY`**：

```bash
curl https://openapi.biji.com/open/api/v1/note/list \
  -H "Authorization: $GETNOTE_API_KEY" \
  -H "X-Client-ID: $GETNOTE_CLIENT_ID"
```

模型从头到尾**不持有密钥明文**，无需调用任何工具去取，省一步、也无从泄漏。

### 方式二：`get_secret` / `set_secret`（模型直接拿值的场景）

- `set_secret(name, value)` —— 把一个密钥存进 `.secrets/<name>`（`0600`）。
- `get_secret(name)` —— 按名读取，**需要用户授权确认**。极少数模型确实要拿到值（而非交给 shell）时用。
- `list_secrets()` —— 只列名称，不显示值，无需授权。

实现见 `ethan/tools/builtin/secrets.py`。

---

## 防泄漏机制

三道防线，从根到补：

1. **不进 prompt**：env 注入的是 shell 子进程，不是模型上下文。模型"没有"的东西就无法被套出来——这是主防线。
2. **工具输出 masking（安全网）**：`shell` 能被诱导跑 `echo $KEY`，值会进工具输出并回流上下文。因此在工具输出回流的唯一咽喉（`ethan/tools/registry.py::ToolExecutor._run_one`）调 `secrets_store.mask_text()`：扫描所有已知密钥真值，命中替换成 `<前4字符>****`（如 `gk_l****`）。`get_secret` 是授权取值路径，**放行原文**（否则失去意义）。
3. **get_secret 授权**：模型主动读密钥值要经用户确认。

> 为什么不对最终回复再做一遍流式 masking？因为工具输出已在咽喉处脱敏、env 又不进 prompt，模型上下文里本就不该有真值；且流式分块会把密钥切碎、难以匹配。所以脱敏只做在"工具输出回流"这一处咽喉，简单且充分。

`mask_text` 只对长度 ≥ 8 的值生效，避免误伤普通短文本/数字。

---

## 给 Skill 作者的约定

- **不要**把密钥硬编码或明文写进 `SKILL.md` / references / scripts。
- 认证一律用 `$ENV_VAR` 占位（如 `Authorization: $GETNOTE_API_KEY`）。
- 让用户把 key 写进 `~/.ethan/.secrets/<skill>.env`（`KEY="value"`），shell 自动注入，脚本里用 `$KEY`。
- 这样 skill 可以安全开源——仓库里只有占位符，真实 key 永远只在用户本地 `.secrets/`。

参考实现：`ethan/defaults/skills/getnote/`（SKILL.md 认证段 + `references/oauth.md`）。

---

## 相关文件

- `ethan/core/secrets_store.py` —— `load_secret_env()` / `all_secret_values()` / `mask_text()`
- `ethan/tools/builtin/secrets.py` —— `set_secret` / `get_secret` / `list_secrets`
- `ethan/tools/builtin/shell.py` —— 子进程 env 注入
- `ethan/tools/registry.py` —— 工具输出 masking
