# Web 搜索（SearXNG 集成）

Ethan Agent 内置 `web_search` 工具，默认用 DuckDGo（无需配置）。本文档介绍如何接入自建 **SearXNG** 实例——这是一大亮点：**免费、无 API Key、聚合 70+ 搜索引擎、隐私友好、国内外网络自适应**。

## 为什么选 SearXNG

| 维度 | DuckDuckGo（默认） | Tavily | SearXNG |
|------|-------------------|--------|---------|
| 费用 | 免费 | 付费（有免费额度） | 免费 |
| API Key | 不需要 | 需要 | 不需要 |
| 引擎数 | 1 个 | 1 个（自身聚合） | 70+（Google/Bing/arXiv/PubMed/GitHub...） |
| 国内可用 | 需代理 | 需代理 | 可直连（bing/baidu）或走代理（全引擎） |
| 隐私 | 好 | 一般 | 好（自建） |
| 可控性 | 低 | 低 | 高（自建、配置透明） |

**核心优势**：一次搜索请求并行调用多个引擎，SearXNG 聚合去重后返回——相当于一次拿到 Google + Bing + arXiv + GitHub 等多个源的结果。

## 快速开始

### 一键启动（推荐）

```bash
# 1. 启动 SearXNG 容器（监听 8888 端口）
docker compose -f deploy/docker-compose.searxng.yml up -d

# 2. 给 ethan 设置环境变量
export SEARXNG_BASE_URL=http://localhost:8888
# 容器内运行 ethan 则用：SEARXNG_BASE_URL=http://searxng:8080（需同网络）

# 3. 启动 ethan，web_search 工具会自动切到 SearXNG
uv run ethan serve
```

完成。`web_search` 工具会自动检测到 `SEARXNG_BASE_URL` 并切换 provider，无需改 `config.yaml`。

### 验证

```bash
curl "http://localhost:8888/search?q=fastapi&format=json" | python3 -m json.tool | head -20
```

返回 JSON 结果即正常。ethan 的 `web_search` 工具依赖 JSON 输出格式（`deploy/searxng/settings.yml` 已配置 `search.formats: [html, json]`）。

## 代理配置（亮点：国内外自适应）

SearXNG 实例支持通过环境变量 `SEARXNG_PROXY_URL` 一键切换代理 / 直连模式：

| 场景 | 配置 | 可用引擎 |
|------|------|---------|
| **直连模式**（国内无代理） | `SEARXNG_PROXY_URL=`（空） | bing + baidu（仅国内可直连的引擎） |
| **代理模式**（开 Clash 等） | `SEARXNG_PROXY_URL=http://host.docker.internal:7890` | bing + google + startpage + arxiv + pubmed + youtube + github + stackoverflow + ...（70+ 引擎全放开） |

### 配置方法

**方式 1：`.env` 文件（推荐，持久化）**

在 `.local/` 目录创建 `.env`（docker compose 自动读取，已 gitignore）：

```bash
# .local/.env
SEARXNG_PROXY_URL=http://host.docker.internal:7890   # 代理模式
# SEARXNG_PROXY_URL=                                  # 直连模式（留空）
```

然后 `docker compose up -d` 即可。

**方式 2：命令行临时指定**

```bash
# 代理模式
SEARXNG_PROXY_URL=http://host.docker.internal:7890 docker compose -f deploy/docker-compose.searxng.yml up -d

# 直连模式
SEARXNG_PROXY_URL= docker compose -f deploy/docker-compose.searxng.yml up -d
```

### 工作原理

容器启动时执行 [deploy/searxng/entrypoint-wrapper.sh](../deploy/searxng/entrypoint-wrapper.sh)，根据 `SEARXNG_PROXY_URL`：

1. **复制模板**：把只读的 `settings.yml` 复制为可写副本
2. **代理模式**：在 `outgoing.proxies` 注入代理 URL，并放开国外引擎（google/arxiv/youtube 等）
3. **直连模式**：不注入代理，保持 `settings.yml` 中的禁用列表（只留 bing/baidu）
4. **始终禁用**的引擎（代理也用不了）：brave（反爬 403）、baidu（CAPTCHA）、duckduckgo（CAPTCHA）、vimeo、google news、wikidata、ahmia、torch

切换模式后**必须重启容器**（`docker restart` 或 `docker compose up -d --force-recreate`）。

## 引擎策略

### 市场评价与选择依据

**通用搜索**（general 分类）：

| 引擎 | 公认排名 | 优势 | 劣势 | Ethan 状态 |
|------|---------|------|------|-----------|
| **Google** | 第 1 | 结果最相关 | 需代理；SearXNG 用 google cse（自定义搜索，非原生） | ✅ 代理模式主力 |
| **Bing** | 第 2 | 中文覆盖好；国内可直连 | 中文语义理解差（关键词匹配粗暴） | ✅ 直连/代理均启用 |
| **Startpage** | 第 3 | Google 结果的隐私代理，质量接近 Google | 需代理 | ✅ 代理模式主力 |
| DuckDuckGo | 第 4 | 隐私好 | cn-zh region 触发 CAPTCHA | ❌ 禁用 |
| Brave | 第 5 | 独立索引 | 反爬严，SearXNG 调用 403 | ❌ 禁用 |
| Baidu | 中文第 1 | 中文最相关 | 服务器 IP 100% CAPTCHA | ❌ 禁用 |

**学术搜索**（science 分类，代理模式）：

| 引擎 | 公认排名 | 领域 | Ethan 状态 |
|------|---------|------|-----------|
| **Google Scholar** | 第 1 | 全领域 | ✅ |
| **arXiv** | CS/物理第 1 | 预印本 | ✅ |
| **PubMed** | 医学第 1 | 生物医学 | ✅ |
| **Semantic Scholar** | 第 2 | AI 驱动 | ✅ |

**IT/代码搜索**（it 分类，代理模式）：github、stackoverflow、mdn、askubuntu、superuser、docker hub、pypi 均可用。

### 当前调用机制

```
web_search(query="fastapi")
  → category='auto'（默认）→ 路由到 'it' 分类（匹配 "fastapi"）
  → SearXNG /search?q=fastapi&format=json&categories=it
  → 并行调用 github + stackoverflow + mdn + ...
  → SearXNG 聚合 + 去重 + 排序
  → 返回 Top N 给 LLM
  → 若空结果 → 降级到 general（bing + google cse + startpage）
```

**特点**：
- 默认 `category='auto'`，按 query 意图自动选分类（详见下方"搜索分类与自动路由"）
- 一次并行调多个引擎，SearXNG 自动聚合去重
- 主力分类空结果时自动降级到 general（引擎质量分级）
- 模型可显式指定 `category=science|it|news|general`

### 优化方向（TODO）

1. **暴露 engines 给模型**：当前 schema 只暴露 `category`，模型无法选具体引擎（如 `engines=arxiv,google scholar`）。需要时可扩展 schema
2. **图片搜索图标过滤**：devicons/lucide 引擎会返回 SVG 图标，对"找真实图片"的场景是噪音。可加 query 意图判断（query 含 logo/icon 时保留，否则跳过）
3. **学术搜索时间范围过滤**：science 分类暂不支持 `time_range`，无法只看近 1 年的论文

## 搜索分类与自动路由

`web_search` 工具支持 5 种 category，覆盖不同搜索意图：

| category | 说明 | 可用引擎（代理模式） | 典型场景 |
|----------|------|---------------------|---------|
| `auto`（默认） | 自动路由：按 query 意图选分类 | 路由到下列分类之一 | 大多数场景 |
| `general` | 通用 Web 搜索 | bing + google cse + startpage | 日常查询 |
| `science` | 学术论文 | arxiv + pubmed + google scholar + semantic scholar | 论文/研究/医学 |
| `it` | 代码/技术 | github + stackoverflow + mdn + docker hub + askubuntu | 编程问题 |
| `news` | 新闻 | bing news + google news + baidu news | 时事/财经 |

**图片搜索**请使用独立的 `image_search` 工具（见下方"图片搜索工具"章节）。

### 兼容性（不配置 SearXNG 的场景）

不配置 SearXNG 时（默认 DuckDuckGo），web_search 仍完全可用：

| category | 行为 |
|----------|------|
| `general` / `news` | 正常走 DDG/bing/google_news_rss 兜底链 |
| `science` / `it` | 自动降级到 `general`（DDG/bing 兜底） |
| `auto` | 路由到 science/it 时也会降级到 general |

**设计原则**：science/it 的专属引擎（arxiv/github 等）只在 SearXNG 配置时启用；未配置时不影响核心搜索能力，模型仍能通过 DDG/bing 获得结果。

### 自动路由（category='auto'）

默认行为。按 query 关键词匹配自动选择分类，**匹配优先级：science > it > news > general**（最具体的关键词优先）：

```python
# ethan/tools/builtin/web_search.py
_SCIENCE_KEYWORDS = ("论文", "算法", "模型", "transformer", "arxiv", "RLHF", ...)  # 52 个
_IT_KEYWORDS = ("python", "docker", "git", "asyncio", "代码", "函数", "报错", ...)  # 77 个
_NEWS_KEYWORDS = ("今日", "最新", "新闻", "行情", "财报", "发布", "today", "news", ...)  # 35 个
```

**路由示例**：
- `transformer attention mechanism` → science（匹配 "transformer"/"attention"）
- `python asyncio gather 用法` → it（匹配 "python"/"asyncio"）
- `A股今日行情` → news（匹配 "今日"/"行情"）
- `红烧肉做法` → general（无匹配）

### 引擎质量分级（降级策略）

science/it 分类内置"主力→备用→兜底"三级降级：

```
[science 分类请求]
  ↓
主力：SearXNG science 分类（arxiv/pubmed/google scholar）
  ↓ 空结果或异常，或未配置 SearXNG
备用：SearXNG general 分类（bing/google cse/startpage）
  ↓ 空结果或异常
兜底：tavily → duckduckgo → bing（通用 provider 链）
```

主力分类返回空结果时自动降级到 general，保证搜索总有结果返回。

## 图片搜索工具（独立工具）

图片搜索是独立的 `image_search` 工具，不在 `web_search` 的 category 里。**仅在配置了 SearXNG 且开启时启用**。

### 启用条件

```yaml
# config.yaml
tools:
  web_search:
    base_url: http://localhost:8888              # 必须配置 SearXNG
    image_search_enabled: true                   # 默认 true，可关闭
```

未配置 SearXNG 时，工具不会被注册（模型看不到它）；配置后自动注册，通过 `find_tools` 激活使用。

### 工具参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | string | （必填） | 搜索词 |
| `max_results` | integer | 5 | 返回条数 |
| `download` | boolean | false | 是否下载到本地 `/tmp/ethan_images/` |
| `language` | string | `zh-CN` | 语言/地区 |

### 两种模式

**模式 1：URL 模式（`download=false`，默认）**

只返回图片 URL + 元数据，不下载：

```
**6,214 項Cute Cat高解像度插圖- Getty Images**
URL: https://media.gettyimages.com/id/1832715013/zh/...
来源: google cse images | 尺寸: 612x612
```

**模式 2：下载模式（`download=true`）**

下载图片到 `/tmp/ethan_images/`，返回本地路径。**下载时会用真实浏览器 UA + Referer 绕过防盗链，并验证文件确实是图片（content-type 检查 + 大小检查 + `file` 命令验证）**，失败的 URL 自动过滤：

```
**Python Logo, symbol, meaning, history, PNG, brand**
本地路径: /tmp/ethan_images/img_96e570e53e85.png
来源: bing images | 大小: 59KB | 原始 URL: https://logos-world.net/...
```

### 下载验证

测试 6 个 query，每个下载 3 张，**18/18 全部成功**，`file` 命令验证均为真实图片：

| Query | 下载成功 | 格式 |
|-------|---------|------|
| 猫 | 3/3 ✅ | JPEG (42-258KB) |
| 红烧肉 | 3/3 ✅ | JPEG (76-796KB) |
| Elon Musk | 3/3 ✅ | JPEG + WebP (134-194KB) |
| Python logo | 3/3 ✅ | JPEG + SVG (3-113KB) |
| 苹果手机 | 3/3 ✅ | JPEG + WebP (31-182KB) |
| cute cat | 3/3 ✅ | JPEG + SVG (1-162KB) |

### 设计考量

- **为什么需要下载模式？** 部分图片 URL 在浏览器里打不开（防盗链、地区限制、临时 URL 过期）。下载模式在服务端用真实 UA + Referer 获取，过滤掉不可访问的，保证返回的路径都能用。
- **流量消耗**：单张图片平均 100-300KB，5 张约 1-1.5MB。建议用户在确实需要本地文件时才用 `download=true`，否则用 URL 模式。
- **文件清理**：下载的图片存在 `/tmp/ethan_images/`，系统重启自动清理。如需手动清理：`rm -rf /tmp/ethan_images/`。
- **并发限制**：同时最多下载 5 张，避免阻塞。



### 评测方法

- **端点**：`http://localhost:8888/search`（本地 SearXNG 实例）
- **调用方式**：模拟 `web_search` 工具（只传 `q` + `format=json`，不指定 engines）
- **模式**：代理模式（`SEARXNG_PROXY_URL=http://host.docker.internal:7890`）
- **并发**：26 个 case 全部并发执行
- **领域**：10 个领域（生活/学术/工作/股市/科技/互联网/健康/法律/教育/文化）

### 总体指标

| 指标 | 数值 |
|------|------|
| 成功率 | **26/26（100%）** |
| 平均耗时 | 3.93s |
| 中位数耗时 | 4.66s |
| 最小/最大耗时 | 1.30s / 6.25s |
| 平均结果数 | 37 条 |
| 总结果数 | 962 条 |
| 平均引擎数 | 3.0（bing + google cse + startpage） |

### 引擎可用性

| 引擎 | 出现频率 | 失败频率 | 说明 |
|------|---------|---------|------|
| bing | 26/26（100%） | 0 | 主力，稳定 |
| startpage | 26/26（100%） | 0 | 主力，稳定 |
| google cse | 25/26（96%） | 0 | 主力，1 个 case 无结果 |
| baidu | — | 26/26（100%） | CAPTCHA，已禁用 |
| duckduckgo | — | 26/26（100%） | CAPTCHA，已禁用 |

### 各领域表现

| 领域 | case 数 | 平均耗时 | 平均结果数 | 质量评估 |
|------|---------|---------|-----------|---------|
| 生活 | 3 | 2.75s | 39 | ✅ 天气/菜谱好；商品推荐有噪音 |
| 学术 | 3 | 5.54s | 34 | ✅ 论文/概念准确；混合中英文 query 略差 |
| 工作 | 3 | 2.61s | 29 | ✅ 编程问题精准（asyncio/git/docker） |
| 股市 | 3 | 1.89s | 39 | ✅ 行情/财报准确，速度快 |
| 科技 | 3 | 4.22s | 40 | ✅ 产品/发布新闻覆盖全 |
| 互联网 | 3 | 5.53s | 34 | ⚠️ 部分结果相关度低（雪球讨论帖） |
| 健康 | 2 | 4.95s | 39 | ⚠️ 个别结果跑题（"高德地图"出现在高血压查询） |
| 法律 | 2 | 4.09s | 40 | ✅ 法规/政策准确 |
| 教育 | 2 | 4.69s | 40 | ✅ 报名/教程准确 |
| 文化 | 2 | 3.58s | 40 | ✅ 票房/演出信息准确 |

### 典型案例

**好的 case**：
```
[股市] 'A股 北证50 今日行情' → 1.30s, 39 条
  Top 1: [google cse] 北证50(BJ899050)股票股价 - 雪球
  Top 2: [google cse] 北证50(BJ899050) - 最新资讯 - 雪球

[工作] 'python asyncio gather 用法' → 1.98s, 18 条
  Top 1: [bing] asyncio.gather() 函数：并发运行多个异步任务
  Top 2: [startpage] asyncio gather函数的用法 - CSDN博客

[法律] '民法典 婚姻法 离婚 新规' → 5.25s, 40 条
  Top 1: [bing] 中华人民共和国民法典 - 最高人民法院
  Top 2: [startpage] 2025年婚姻法新规解读
```

**有噪音的 case**：
```
[生活] '家常红烧肉做法' → 1.49s, 40 条
  Top 1: [bing] 福克蘭群島 - 維基百科   ← 不相关（bing 中文关键词匹配问题）
  Top 2: [google cse] 秘制红烧肉的做法 - 美食天下   ✅

[健康] '高血压 饮食注意事项' → 5.20s, 40 条
  Top 1: [bing] 高（汉语文字）_百度百科   ← 不相关
  Top 2: [startpage] 要想控制好高血压...饮食、运动要注意什么   ✅
```

**结论**：bing 的中文关键词匹配较粗暴（单字匹配导致跑题），但 google cse + startpage 能补位，Top 3 内必有相关结果。多引擎聚合的价值正在于此——单引擎的弱点被其他引擎覆盖。

### 新功能端到端测试

对 `WebSearchTool` 直接调用测试（10 个 case 覆盖所有 category + 自动路由）：

| Case | Category | 路由 | 耗时 | 结果数 | Top 1 |
|------|----------|------|------|-------|-------|
| transformer attention mechanism | science | science | 3.44s | 3 | arxiv: Transformer-based Personalized Attention... |
| 大语言模型幻觉 mitigation | science | science | 2.29s | 3 | sciengine: 大语言模型的幻觉问题研究综述 |
| python asyncio gather 用法 | it | it | 2.09s | 3 | MDN: Python |
| docker compose healthcheck | it | it | 1.32s | 3 | superuser: Restart of docker-compose... |
| A股今日行情 | auto | news | 3.59s | 3 | Google News: A股今日突然拉升... |
| 红烧肉做法 | auto | general | 1.25s | 3 | 百度百科: 红烧肉 |
| RLHF 强化学习 | auto | science | 2.66s | 3 | arxiv: Iterative Preference Learning... |
| git rebase 冲突 | auto | it | 1.32s | 3 | MDN: Git |

**8/8 全部成功**。自动路由准确识别了所有 query 的意图（学术→science、编程→it、行情→news、菜谱→general）。

### DDG 兼容性测试（不配置 SearXNG）

模拟未配置 SearXNG 的场景，验证 web_search 仍完全可用：

| Query | 路由 | 结果 | 说明 |
|-------|------|------|------|
| python asyncio 用法 | auto→it | ✅ 2 条 | it 无专属引擎，降级到 general→DDG |
| transformer attention | science | ✅ 2 条 | science 无专属引擎，降级到 general→DDG |
| 红烧肉做法 | auto→general | ✅ 2 条 | 直接走 general→DDG |

**3/3 全部成功**。未配置 SearXNG 时所有分类都能正常工作（自动降级到 DDG/bing 兜底）。


### 文件结构

```
deploy/searxng/
├── settings.yml              # SearXNG 配置模板（直连模式的引擎禁用列表）
└── entrypoint-wrapper.sh     # 启动脚本（根据 SEARXNG_PROXY_URL 动态切换模式）

deploy/
└── docker-compose.searxng.yml  # 独立 add-on 部署用

.local/
├── docker-compose.yml        # dev 环境（含 searxng 服务）
└── .env                      # 环境变量（SEARXNG_PROXY_URL 等，已 gitignore）
```

### settings.yml 关键配置

```yaml
use_default_settings: true    # 加载 SearXNG 内置 70+ 默认引擎

server:
  secret_key: "please-change-this-searxng-secret-key"  # 单机自用；公网部署请换随机值
  limiter: false              # 单机自用关闭限流

search:
  default_lang: zh-CN         # 关键！Bing 国际版页面结构已改（无 b_algo class），
                              # SearXNG XPath 解析不到结果；中文 region 下正常
  formats: [html, json]       # JSON 必须显式开启，web_search 依赖

outgoing:
  request_timeout: 12.0       # 默认 3s 太短
  max_request_timeout: 20.0
  # proxies 段由 wrapper 动态注入，这里不写

engines:
  # 直连模式下显式禁用国外引擎（代理模式由 wrapper 自动放开）
  - name: brave
    disabled: true
  # ... 完整列表见 settings.yml
```

### docker-compose 关键配置

```yaml
services:
  searxng:
    image: searxng/searxng:latest
    volumes:
      # settings.yml 作为只读模板挂载，wrapper 每次启动复制可写副本
      - ./deploy/searxng/settings.yml:/etc/searxng/settings.template.yml:ro
      - ./deploy/searxng/entrypoint-wrapper.sh:/usr/local/searxng/entrypoint-wrapper.sh:ro
    environment:
      - SEARXNG_PROXY_URL=${SEARXNG_PROXY_URL:-}  # 代理开关
    extra_hosts:
      - "host.docker.internal:host-gateway"       # Linux 也支持 host.docker.internal
    entrypoint: /usr/local/searxng/entrypoint-wrapper.sh
    dns:
      - 223.5.5.5    # 阿里 DNS，避免路由器 DNS 污染
      - 1.1.1.1      # Cloudflare 备用
```

## 故障排查

### wikidata: engine INIT failed

**原因**：SearXNG 启动时会 init wikidata 引擎（查询 SPARQL endpoint），国内访问 `query.wikidata.org` 失败（DNS 污染或 IP 阻断）。

**影响**：无。wikidata 被禁用后不参与搜索，只是启动日志有 ERROR。

**处理**：已在 `settings.yml` 中 `disabled: true`，无需处理。SearXNG 的设计是 `disabled` 的引擎仍会执行 init（init 失败不影响搜索），这是固有行为。

### 所有引擎 timeout / 0 结果

**原因**：代理配置错误或代理未启动。

**排查**：
```bash
# 1. 检查代理是否在监听
lsof -nP -iTCP:7890 -sTCP:LISTEN

# 2. 检查 .env 是否设置了 SEARXNG_PROXY_URL
cat .local/.env

# 3. 检查容器内能否访问代理
docker exec ethan-dev-searxng /usr/local/searxng/.venv/bin/python3 -c "
import httpx
r = httpx.get('https://www.google.com', proxy='http://host.docker.internal:7890', timeout=8)
print(r.status_code)
"

# 4. 检查容器 DNS（避免路由器 DNS 污染）
docker exec ethan-dev-searxng cat /etc/resolv.conf
```

### bing 返回 0 结果但无报错

**原因**：Bing 国际版（www.bing.com）页面结构已改，HTML 里没有 `b_algo` class，SearXNG 的 XPath 解析不到。

**解决**：确保 `settings.yml` 中 `search.default_lang: zh-CN`（已配置）。中文 region 下 Bing 返回的页面结构正常。

### baidu: CAPTCHA

**原因**：百度对服务器 IP 一律弹验证码（无浏览器指纹）。

**处理**：已加入 `ALWAYS_DISABLED`，代理模式也禁用。bing 已能覆盖中文搜索需求。

### duckduckgo: CAPTCHA (cn-zh)

**原因**：`default_lang=zh-CN` 导致 SearXNG 用 cn-zh region 请求 DDG，触发 CAPTCHA。

**处理**：已加入 `ALWAYS_DISABLED`。startpage 已能返回 Google 结果，无需 DDG。

## 性能数据

| 指标 | 直连模式 | 代理模式 |
|------|---------|---------|
| 可用引擎数 | 2（bing + baidu*） | 70+ |
| 平均耗时 | 1-2s | 2-6s |
| 平均结果数 | 9-18 | 30-40 |
| 主力引擎 | bing | bing + google cse + startpage |

*baidu 在直连模式下也会被 CAPTCHA，实际只有 bing 出力。

## 与 ethan web_search 工具的关系

`web_search` 工具（[ethan/tools/builtin/web_search.py](../ethan/tools/builtin/web_search.py)）的调用链：

```
LLM 调用 web_search(query="...", max_results=5, category="general")
  → WebSearchTool.run()
  → 检测到 config.tools.web_search.base_url（即 SEARXNG_BASE_URL）
  → 走 _searxng_search() 分支
  → GET {base_url}/search?q={query}&format=json
  → SearXNG 并行调用所有 enabled 的 general 引擎
  → 聚合去重后返回 JSON
  → ethan 提取 Top N 条结果的 title + url + content
  → 格式化为字符串返回给 LLM
```

**Provider 优先级**：`searxng`（配了 base_url 时）→ `tavily`（配了 api_key 时）→ `duckduckgo`（兜底）→ `bing`（最后兜底）。每个 provider 有熔断机制：连续 2 轮失败熔断 300s。

**环境变量自动启用**：设置 `SEARXNG_BASE_URL` 后，`config.tools.web_search.provider` 自动切到 `searxng`，无需改 `config.yaml`（见 [ethan/core/config.py](../ethan/core/config.py) 的 `apply_env_overrides`）。
