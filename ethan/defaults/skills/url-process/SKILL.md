---
name: url-process
description: 链接处理入口。自动识别平台(飞书/微信/Notion/知乎/通用网页)，选择最快路径抓取内容，可选总结或原样存到 Get笔记。**所有链接第一次处理都应先调本技能判断平台**。
trigger: "文章总结|总结文章|解读文章|深度总结|这篇文章核心观点|article summarize|文章分析|文章解读|摘要这篇文章|抽取.*内容|抽取.*markdown|存.*笔记|抓取.*内容|这个文档|这个链接|链接|http://|https://|feishu.cn|larksuite.com|mp.weixin.qq.com|docx|wiki"
---

# URL 处理 — 链接处理入口

**核心纪律**：
1. **拿到链接先判断平台**，不要直接调 web_fetch 或读 skill
2. **判断后直接调对应工具**，不要 skill_read / skill_list
3. **能一步到位就别绕路**
4. **用户说"存笔记"/"抽取" → 原样存 markdown，不总结**
5. **用户说"总结"/"核心观点" → 只输总结（按「总结流程」格式），不存笔记**

---

## 第一步：识别平台

| URL 模式 | 平台 | 处理方式 |
|---------|------|---------|
| `*.feishu.cn/docx/*` `*.feishu.cn/wiki/*` | 飞书文档 | **lark-cli docs +fetch** |
| `*.larksuite.com/docx/*` `*.larksuite.com/wiki/*` | 飞书文档 | **lark-cli docs +fetch** |
| `*.larkoffice.com/docx/*` `*.larkoffice.com/wiki/*` | 飞书文档 | **lark-cli docs +fetch** |
| `mp.weixin.qq.com/s/*` | 微信公众号 | **web_fetch** |
| `*.notion.so/*` `notion.site/*` | Notion | **agent-browser** |
| `zhuanlan.zhihu.com/*` | 知乎专栏 | **agent-browser** |
| `medium.com/*` | Medium | **agent-browser** |
| 其他 URL | 通用网页 | **web_fetch 先试**，失败降级 agent-browser |

---

## 第二步：按平台执行

### 飞书文档（4 步，~10 秒）

```bash
# 步骤 1：token 提取 + lark-cli 导出 + JSON 解析 + 写 markdown
lark-cli docs +fetch --doc "TOKEN" --doc-format markdown --as user | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['data']['document']['content'])" > /tmp/lark_doc.md

# 步骤 2：读 markdown（完整内容，不截断）
file_read(path="/tmp/lark_doc.md")

# 步骤 3：写 JSON payload（用户要存笔记时）
file_write(path="/tmp/note_payload.json", content='{"type":"text","title":"文档标题","content":"完整markdown内容"}')

# 步骤 4：curl 存笔记
curl -s -X POST "https://openapi.biji.com/open/api/v1/resource/note/save" \
  -H "Authorization: $GETNOTE_API_KEY" \
  -H "X-Client-ID: $GETNOTE_CLIENT_ID" \
  -H "Content-Type: application/json" \
  -d @/tmp/note_payload.json
```

**要点**：
- 域名支持：feishu.cn / larksuite.com / larkoffice.com
- 路径支持：/docx/ 或 /wiki/
- Token = 最后一段路径
- 不检查凭证，不读 skill，不写 Python 脚本，不手拼 JSON

### 微信公众号

```bash
web_fetch(url="https://mp.weixin.qq.com/s/xxx")
# 拿到内容后：存笔记 → 见「存到 Get笔记」；总结 → 见「总结流程」
```

### Notion / 知乎专栏 / Medium

```bash
agent-browser open "https://xxx.notion.so/xxx"
agent-browser wait 3000
agent-browser get text
agent-browser close
```

### 通用网页

```bash
web_fetch(url="https://example.com/article")
# 失败则降级 agent-browser
```

---

## 第三步：存到 Get笔记

**拿到 markdown 后，不要读 getnote skill，直接执行：**

```bash
# 步骤 1：写 JSON（用 file_write，别手拼）
file_write(path="/tmp/note_payload.json", content='{"type":"text","title":"标题","content":"完整markdown内容"}')

# 步骤 2：curl（用 -d @文件，别手拼）
curl -s -X POST "https://openapi.biji.com/open/api/v1/resource/note/save" \
  -H "Authorization: $GETNOTE_API_KEY" \
  -H "X-Client-ID: $GETNOTE_CLIENT_ID" \
  -H "Content-Type: application/json" \
  -d @/tmp/note_payload.json
```

---

## 总结流程（用户说"总结"/"核心观点"时必看）

**只有用户明确说"总结"/"核心观点"/"解读"时才走这里，否则直接存原文 markdown。**

### 输出格式

```
# <文章标题>

## 背景
一句话概括文章背景/问题。

## 核心洞察
1. **[洞察名称]**
   - 关键词:短句1;短句2。
   - 数据:具体数字。
   - 证据:原文引用。

2. **[洞察名称]**（如有多个）
   - 关键词:短句1;短句2。
   - 链条:步骤1 → 步骤2。

## 子叙事
1. **[子视角]**
   - 详情
```

### 规则

1. **核心洞察最多 2 个**，不要列一堆
2. **短句为主**：50 字拆成 5-10 个短句，用分号分隔
3. **关键词前置**：最重要的词放每句开头
4. **数据要具体**："提升明显" ❌ → "76.2%→81.5%" ✅
5. **专业名词加括号**：第一次出现的术语用括号解释

---

## 错误示范 vs 正确示范

❌ **错误（废话多、无结构）**：
```
这篇文章主要讲述了企业在数字化转型过程中遇到的挑战。
作者认为数字化转型是一个复杂的过程，需要企业在多个方面进行调整。
文章提到了组织架构、技术投入、人才培养等方面的问题...
（继续流水账 500 字）
```

✅ **正确（树状结构、短句、关键词前置）**：
```
# 数字化转型的陷阱

## 背景
企业数字化失败率 70%；根因在组织，不在技术。

## 核心洞察
1. **组织阻力是主因**
   - 阻力来源:中层恐惧;部门墙;流程僵化。
   - 数据:失败案例 70% 源于组织问题。
   - 证据:"不是技术不行，是人不行"（原文）。

2. **速赢策略破局**
   - 关键词:选痛点;小闭环;扩战果。
   - 链条:找痛点 → 3 个月闭环 → 复制到其他部门。

## 子叙事
1. **中层恐惧如何化解**
   - 让中层当项目发起人，从"被改革"变成"推改革"。
```
