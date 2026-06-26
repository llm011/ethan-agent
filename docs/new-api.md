# 自建 new-api 网关 + 接入各类大模型

本篇讲两件事：

1. 在 NAS（绿联 / 通用 Linux）上用 Docker 跑起 **new-api** 网关
2. 在 new-api 的 Web UI 里把各家大模型（OpenAI / Anthropic / Gemini / DeepSeek / 智谱 GLM / 火山 / Ollama / 中转站）配成【渠道】，再让 **ethan-agent** 指向这个自建网关

> 为什么要自建？目前 ethan 直连第三方中转（如 yuntoken），中转站常有限流 / 封号 / 偷换模型的风险。自建 new-api 后，你把各家官方 Key 集中托管，对外只暴露一个自建地址和一个令牌，还能按模型分组、设优先级、看用量。

---

## 一、跑起 new-api

镜像：[`calciumion/new-api`](https://github.com/Calcium-Ion/new-api)（one-api 的增强分支）。

### 方式 A：一键合并栈部署（推荐）

把 new-api 和 ethan-agent 一起部署，ethan 经 Docker 内网直连 new-api，单栈一条命令全拉起。

#### 1. 准备文件

NAS 上建个目录，放进去：

```
nas-newapi/
├── docker-compose.nas-newapi.yml   # 仓库 deploy/ 下有
└── .env                             # 从 deploy/.env.nas-newapi.example 复制改
```

```bash
mkdir -p ~/nas-newapi && cd ~/nas-newapi
cp /path/to/ethan-agent/deploy/docker-compose.nas-newapi.yml .
cp /path/to/ethan-agent/deploy/.env.nas-newapi.example .env
# 编辑 .env：重点是 RELAY_PROXY（出网代理）、ETHAN_AUTH_TOKEN（登录密码）
# NEW_API_TOKEN 先留空，后面去 Web UI 生成
```

#### 2. 启动

```bash
docker compose -f docker-compose.nas-newapi.yml pull
docker compose -f docker-compose.nas-newapi.yml up -d
docker compose -f docker-compose.nas-newapi.yml logs -f   # 看启动日志
```

启动顺序：new-api 先起，ethan 等它 healthy 后才启动。首次 new-api 还没渠道/令牌，ethan 会启动失败 → 正常。

#### 3. 首次登录 new-api & 改密码

浏览器开 `http://<nas-ip>:3000`：

- 默认账号：`root`
- 默认密码：`123456`
- **登录后立刻去【个人设置】改密码**

#### 4. 配渠道 + 发令牌

在 new-api Web UI 里：

1. 左侧【**渠道**】→ 添加各家上游（见第二节【配渠道】）
2. 左侧【**令牌**】→ 生成一个 `sk-xxxx`
3. 把这个令牌填回 `.env` 的 `NEW_API_TOKEN`

#### 5. 重启 ethan

```bash
docker compose -f docker-compose.nas-newapi.yml restart ethan
# 看日志确认 ethan 正常启动
docker compose -f docker-compose.nas-newapi.yml logs -f ethan
```

#### 6. 访问 ethan Web UI

浏览器开 `http://<nas-ip>:8900`，用 `.env` 里的 `ETHAN_AUTH_TOKEN` 登录。

数据持久化：
- new-api 数据在 named volume `new-api-data` → 容器内 `/data`
- ethan 数据在 named volume `ethan-data` → 容器内 `/root/.ethan`
重建容器不丢配置。

### 方式 B：分开部署（备选）

如果你已经有 new-api 在跑，或者想分开管理，可以用原有的单独 compose 文件：

```bash
mkdir -p ~/new-api && cd ~/new-api
cp /path/to/ethan-agent/deploy/docker-compose.new-api.yml .
cp /path/to/ethan-agent/deploy/.env.new-api.example .env
docker compose -f docker-compose.new-api.yml up -d
```

然后按第二节配渠道、第三节发令牌，第四节把 ethan 指向自建网关。

分开部署时，ethan 的 `.env` 要手动填 `OPENAI_BASE_URL=http://<nas-ip>:3000/v1`（局域网地址）。

---

## 二、配渠道（Channel）：把各家模型接进来

在 Web UI 左侧【**渠道**】→【**添加渠道**】。每个渠道 = 一个上游厂商的一份 Key。

> 关键参数对照：
> - **类型**：决定走哪个协议适配器（选错会报错）
> - **名称**：自己起的标签，随便填
> - **Base URL / 代理**：多数官方渠道留空即可；第三方/自建才填
> - **模型**：勾选/填入该渠道支持的模型 ID 列表
> - **密钥**：上游厂商的真实 Key

下面按厂商给出推荐配置。

### 1. OpenAI 官方

| 字段 | 值 |
|------|----|
| 类型 | `OpenAI` |
| Base URL | （留空） |
| 密钥 | `sk-proj-xxxx` |
| 模型 | `gpt-4o`, `gpt-4o-mini`, `o1`, `o3-mini`, `gpt-4.1` … |

### 2. Anthropic 官方（Claude）

| 字段 | 值 |
|------|----|
| 类型 | `Claude` |
| Base URL | （留空） |
| 密钥 | `sk-ant-xxxx` |
| 模型 | `claude-opus-4.8`, `claude-sonnet-4.6`, `claude-haiku-4.5` … |

> new-api 的 Claude 渠道会把 Claude 转成 OpenAI 格式对外；ethan 若要用 Anthropic 原生协议（含 Prompt Caching），见第四节【两种接入姿势】。

### 3. Google Gemini

| 字段 | 值 |
|------|----|
| 类型 | `Gemini` |
| Base URL | （留空，用官方） |
| 密钥 | `AIzaSyxxxx`（Google AI Studio 申请） |
| 模型 | `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.0-flash` |

### 4. DeepSeek

| 字段 | 值 |
|------|----|
| 类型 | `OpenAI`（DeepSeek 兼容 OpenAI 协议） |
| Base URL | `https://api.deepseek.com` |
| 密钥 | `sk-xxxx` |
| 模型 | `deepseek-chat`, `deepseek-reasoner` |

### 5. 智谱 GLM（BigModel）

| 字段 | 值 |
|------|----|
| 类型 | `OpenAI`（new-api 内置 GLM 适配，选 `智谱 GLM` 也行） |
| Base URL | `https://open.bigmodel.cn/api/paas/v4` |
| 密钥 | `xxxx.xxxx` |
| 模型 | `glm-5.2`, `glm-4.6`, `glm-4.5` |

> ⚠️ 模型 ID 用 `glm-5.2` / `glm-4.6`，**不要带 `[1m]`** 后缀（那是 Claude Code 的 1M 上下文别名，网关不认）。

### 6. 火山引擎（字节 ARK / 豆包）

| 字段 | 值 |
|------|----|
| 类型 | `OpenAI`（火山只兼容 OpenAI 协议，**千万别选 Claude**） |
| Base URL | `https://ark.cn-beijing.volces.com/api/v3` |
| 密钥 | `ark-xxxx-xxxx` |
| 模型 | `ep-20251218165528-tt2hm`（**必须填推理接入点 ID，不能填模型原名**） |

> 避坑：火山要把"在线推理 → 创建推理接入点"得到的 `ep-xxx` 当模型 ID 填，而不是 `claude-sonnet` / `doubao-pro`。

### 7. 阿里通义千问（DashScope）

| 字段 | 值 |
|------|----|
| 类型 | `通义千问 Qwen`（或 `OpenAI`） |
| Base URL | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 密钥 | `sk-xxxx` |
| 模型 | `qwen-max`, `qwen-plus`, `qwen-turbo`, `qwen3-coder-plus` |

### 8. 本地 Ollama（NAS 上跑的本地模型）

| 字段 | 值 |
|------|----|
| 类型 | `Ollama` |
| Base URL | `http://<nas-ip>:11434`（注意用宿主机 IP，不是 `localhost`） |
| 密钥 | （留空或随便填） |
| 模型 | `llama3`, `qwen2.5`, `deepseek-r1` … |

> Ollama 不需要代理（本地）。ethan 想直连 Ollama 也可以不走 new-api。

### 9. 第三方中转（OpenRouter / yuntoken 等）

| 字段 | 值 |
|------|----|
| 类型 | 按中转商协议选（多数是 `OpenAI`；号称原生 Anthropic 的选 `Claude`） |
| Base URL | 中转商给的地址（如 `https://openrouter.ai/api/v1`） |
| 密钥 | 中转商给的 `sk-xxx` |
| 模型 | 按中转商文档填 |

> 自建 new-api 的意义正是**逐步替代**这类第三方中转——上游换成各家官方渠道更稳。

---

## 三、发令牌（Token）：ethan 用来访问网关

左侧【**令牌**】→【**添加令牌**】：

- 名称：`ethan`
- 额度：不限量 / 或设月度额度
- 模型范围：可勾选只允许用哪些模型（留空=全部）
- 保存后会得到一个 `sk-xxxx` ← **这个就是 ethan 的 API Key**

### 令牌对应的 Base URL

ethan 访问 new-api 的统一入口：

```
http://<nas-ip>:3000      # OpenAI 兼容协议
http://<nas-ip>:3000/v1   # 等价（OpenAI SDK 习惯带 /v1）
```

---

## 四、把 ethan 指向自建 new-api

### 合并栈部署（方式 A）

如果用的是 `docker-compose.nas-newapi.yml` 一键合并栈，ethan 已经通过 Docker 内网 `http://new-api:3000` 直连 new-api，只需在 `.env` 里填 `NEW_API_TOKEN` 然后重启 ethan 即可，无需额外配置。

### 分开部署（方式 B）

如果 new-api 和 ethan 是分开部署的，手动改 ethan 的 `.env`：

#### 两种姿势

ethan 支持 Anthropic 原生协议（享 Prompt Caching）和 OpenAI 兼容协议两种。new-api 两种都对外提供，按你想要的特性选：

##### 姿势 A：走 OpenAI 兼容协议（最简单，模型都能用）

改 ethan 的 `.env`：

```bash
OPENAI_API_KEY=sk-xxxx        # 第三节里 new-api 发的令牌
OPENAI_BASE_URL=http://10.0.0.75:3000/v1
AGENT_DEFAULT_MODEL=claude-sonnet-4.6   # 或 gpt-4o / glm-5.2 / 任意
```

#### 姿势 B：走 Anthropic 原生协议（享 Prompt Caching，仅 Claude 系）

```bash
ANTHROPIC_API_KEY=sk-xxxx
ANTHROPIC_BASE_URL=http://10.0.0.75:3000
AGENT_DEFAULT_MODEL=claude-sonnet-4.6
```

> 注意：new-api 的 Anthropic 入口默认路径是根 `/`（部分版本需 `/v1`）。若报 404/路径错误，把 `ANTHROPIC_BASE_URL` 在 `http://10.0.0.75:3000` 和 `http://10.0.0.75:3000/v1` 之间切换试一下。

#### 姿势 A & B 使用 ethan 分开部署的 compose 文件（见 deploy/docker-compose.nas.yml）

### 配完重启 ethan

```bash
docker compose -f docker-compose.nas.yml restart ethan
```

---

## 五、运维常用命令

### 合并栈部署

```bash
# 看日志
docker compose -f docker-compose.nas-newapi.yml logs -f

# 只看 new-api 日志
docker compose -f docker-compose.nas-newapi.yml logs -f new-api

# 只看 ethan 日志
docker compose -f docker-compose.nas-newapi.yml logs -f ethan

# 重启全部
docker compose -f docker-compose.nas-newapi.yml restart

# 只重启 ethan（改了 NEW_API_TOKEN 后）
docker compose -f docker-compose.nas-newapi.yml restart ethan

# 升级到最新版本
docker compose -f docker-compose.nas-newapi.yml pull
docker compose -f docker-compose.nas-newapi.yml up -d

# 停掉
docker compose -f docker-compose.nas-newapi.yml down
```

### 分开部署

```bash
# 看日志
docker compose -f docker-compose.new-api.yml logs -f

# 重启
docker compose -f docker-compose.new-api.yml restart

# 升级到最新 new-api
docker compose -f docker-compose.new-api.yml pull
docker compose -f docker-compose.new-api.yml up -d

# 停掉
docker compose -f docker-compose.new-api.yml down
```

数据都在 volume `new-api-data` / `ethan-data`，升级/重建不丢渠道和令牌配置。

---

## 六、排错速查

| 现象 | 原因 / 处理 |
|------|------------|
| 渠道【测试】报超时 | 没配 `RELAY_PROXY` 或代理地址写成了 `127.0.0.1`（应是 NAS 局域网 IP） |
| 调 Claude 渠道报 `unknown provider` | 把火山/中转误选成了 `Claude` 类型，改成 `OpenAI` |
| 火山报模型不存在 | 填了模型原名，改成 `ep-xxx` 接入点 ID |
| GLM 报模型不存在 | model id 带了 `[1m]`，去掉后缀 |
| ethan 报 `PermissionDenied: blocked` | 中转商不支持 `cache_control`，在 new-api 渠道里关掉该模型的 prompt cache，或 ethan 侧 `disable_prompt_cache: true` |
| 令牌 401 | Base URL 漏了 `/v1` 或令牌模型范围没勾上当前模型 |
