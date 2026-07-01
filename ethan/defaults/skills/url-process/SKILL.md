---
name: url-process
description: 链接处理入口。自动识别平台(飞书/微信/Notion/知乎/通用网页)，选择最快路径抓取内容，可选总结或原样存到 Get笔记。**所有链接第一次处理都应先调本技能判断平台**。
trigger: "文章总结|总结文章|解读文章|深度总结|这篇文章核心观点|article summarize|文章分析|文章解读|摘要这篇文章|抽取.*内容|抽取.*markdown|存.*笔记|抓取.*内容|这个文档|这个链接|链接|http://|https://|feishu.cn|larksuite.com|mp.weixin.qq.com|docx|wiki"
---

# URL 处理 — 链接处理入口

**定位**：所有链接的统一入口。先判断平台，再选最快路径。

**核心纪律**：
1. **拿到链接先判断平台**，不要直接调 web_fetch 或读 skill
2. **判断后直接调对应工具**，不要 skill_read / skill_list
3. **能一步到位就别绕路**
4. **用户说"存笔记"/"抽取" → 原样存 markdown，不总结**
5. **用户说"总结"/"核心观点" → 只输总结（按「总结流程」格式），不存笔记**

---

## 第一步：识别平台（必做）

**看到链接，先判断平台，然后直接走对应流程：**

| URL 模式 | 平台 | 处理方式 | 优先级 |
|---------|------|---------|--------|
| `*.feishu.cn/docx/*` `*.feishu.cn/wiki/*` | 飞书文档 | **lark-cli docs +fetch**（API 直调） | 最高 |
| `*.larksuite.com/docx/*` `*.larksuite.com/wiki/*` | 飞书文档 | **lark-cli docs +fetch**（API 直调） | 最高 |
| `*.larkoffice.com/docx/*` `*.larkoffice.com/wiki/*` | 飞书文档 | **lark-cli docs +fetch**（API 直调） | 最高 |
| `mp.weixin.qq.com/s/*` | 微信公众号 | **web_fetch**（静态页面） | 高 |
| `*.notion.so/*` `notion.site/*` | Notion | **agent-browser**（JS 渲染） | 中 |
| `zhuanlan.zhihu.com/*` | 知乎专栏 | **agent-browser**（JS 渲染） | 中 |
| `medium.com/*` | Medium | **agent-browser**（JS 渲染） | 中 |
| 其他 URL | 通用网页 | **web_fetch 先试**，失败降级 agent-browser | 先高后中 |

**判断逻辑**：
```python
# 飞书文档域名：feishu.cn / larksuite.com / larkoffice.com
# 路径：/docx/ 或 /wiki/
feishu_domains = ["feishu.cn", "larksuite.com", "larkoffice.com"]
if any(d in url for d in feishu_domains):
    if "/docx/" in url or "/wiki/" in url:
        return "lark-doc"
elif "mp.weixin.qq.com" in url:
    return "web-fetch"
elif "notion.so" in url or "notion.site" in url:
    return "agent-browser"
elif "zhuanlan.zhihu.com" in url:
    return "agent-browser"
elif "medium.com" in url:
    return "agent-browser"
else:
    return "web-fetch-first"
```

---

## 第二步：按平台执行（直接调工具，不读 skill）

### 飞书文档（最快路径）

**直接调 lark-cli，不读 skill，不写 python 脚本**：

```bash
# 1. 提取 token（从 URL 或用户直接给的 token）
# URL 格式（三种域名都支持）：
#   https://xxx.feishu.cn/docx/OIXGdEBR2o2PrNxRUuVcSQaznEg
#   https://xxx.larksuite.com/wiki/TbB6w6MlSiXZD5k3kwkc4PRpnxd
#   https://bytedance.larkoffice.com/wiki/TbB6w6MlSiXZD5k3kwkc4PRpnxd
# Token = 最后一段路径（去掉 /docx/ 或 /wiki/ 后的部分）

# 2. 直接调 lark-cli 导出 markdown（输出是 JSON，包含 data.document.content 字段）
lark-cli docs +fetch --doc "OIXGdEBR2o2PrNxRUuVcSQaznEg" --doc-format markdown --as user > /tmp/lark_doc.json

# 3. 从 JSON 里提取 markdown 内容并写入文件
cat /tmp/lark_doc.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['document']['content'])" > /tmp/lark_doc.md

# 4. 读提取后的 markdown 文件
file_read(path="/tmp/lark_doc.md")

# 5. 拿到内容后分支处理：
#    - 用户说"存笔记/抽取" → 原样存 markdown（见「存到 Get笔记」章节）
#    - 用户说"总结/核心观点" → 只输总结（见「总结流程」章节）
```

**铁律**：
- ❌ 不要 `skill_list`（浪费时间）
- ❌ 不要 `skill_read(name="lark-doc")`（不用读整个 skill）
- ❌ 不要 `python ~/.ethan/skills/lark-doc/scripts/fetch_doc.py`（python 命令常找不到，直接 lark-cli 更稳）
- ✅ 直接 `lark-cli docs +fetch`（一步到位）

### 微信公众号（最快路径）

```bash
# 直接 web_fetch，不要读 skill
web_fetch(url="https://mp.weixin.qq.com/s/xxx")

# 拿到内容后分支处理：
#    - 用户说"存笔记/抽取" → 原样存 markdown（见「存到 Get笔记」章节）
#    - 用户说"总结/核心观点" → 只输总结（见「总结流程」章节）
```

### Notion / 知乎专栏 / Medium（最快路径）

```bash
# 1. 检查 agent-browser
agent-browser --version || echo "需要安装"

# 2. 打开页面
agent-browser open "https://xxx.notion.so/xxx"

# 3. 等待加载
agent-browser wait 3000

# 4. 读正文
agent-browser get text

# 5. 关闭
agent-browser close

# 6. 拿到内容后分支处理：
#    - 用户说"存笔记/抽取" → 原样存 markdown（见「存到 Get笔记」章节）
#    - 用户说"总结/核心观点" → 只输总结（见「总结流程」章节）
```

### 通用网页（最快路径）

```bash
# 1. web_fetch 先试
web_fetch(url="https://example.com/article")

# 2. 如果成功 → 拿到内容后分支处理（同上）
# 3. 如果失败（status_code 错误 / 内容过短）→ 降级 agent-browser
```

---

## 第三步：存到 Get笔记（直接执行以下命令）

**拿到 markdown 内容后，不要读 getnote skill，直接执行以下 3 步：**

```bash
# 步骤 1：写 JSON payload（用 file_write，别手拼）
# 注意：content 字段填入刚才读到的 markdown 内容（完整内容，不要截断）
file_write(path="/tmp/note_payload.json", content='{"type":"text","title":"文档标题","content":"这里填入完整 markdown 内容"}')

# 步骤 2：curl 调 API（用 -d @文件，别手拼 JSON）
curl -s -X POST "https://openapi.biji.com/open/api/v1/resource/note/save" \
  -H "Authorization: $GETNOTE_API_KEY" \
  -H "X-Client-ID: $GETNOTE_CLIENT_ID" \
  -H "Content-Type: application/json" \
  -d @/tmp/note_payload.json

# 步骤 3：解析响应，告诉用户结果
# 成功：{"success":true,"result":{"note_id":"xxx"}}
# 失败：{"success":false,"error":{"message":"content is required"}}
```

**铁律**：
- ❌ 不要 `skill_read(name="getnote")`
- ❌ 不要 `skill_read(file="references/save.md", name="getnote")`
- ❌ 不要手拼 JSON 字符串（`curl -d '{"type":...}'` ❌ → `curl -d @/tmp/note_payload.json` ✅）
- ✅ 用 `file_write` 写完整 JSON，再 `curl -d @文件`

**失败常见原因**：
- `"content is required"` → JSON 里 content 字段为空或缺失
- `"unauthorized"` → API Key / Client ID 错误
- `"not_member"` → 需开通会员

---

## 总结流程（用户说"总结"/"核心观点"时必看）

**只有用户明确说"总结"/"核心观点"/"解读"时才走这里，否则直接存原文 markdown。**

### 输出格式（必须严格遵循）

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

---
用最直白的话，把最重要的抓出来，不讲废话。
```

### 规则

1. **核心洞察最多 2 个**，不要列一堆
2. **短句为主**：50 字拆成 5-10 个短句，用分号分隔
3. **关键词前置**：最重要的词放每句开头
4. **数据要具体**："提升明显" ❌ → "76.2%→81.5%" ✅
5. **专业名词加括号**：第一次出现的术语用括号解释

### 错误示范 vs 正确示范

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

---

## ⚠️ 关键纪律（避免绕路）

**用户给链接时，正确流程**：

```
✅ 正确：
1. 判断平台（飞书/微信/Notion/通用）
2. 直接调对应工具（lark-cli / web_fetch / agent-browser）
3. 拿到内容后：
   - 用户说"总结" → 按「总结流程」章节输出
   - 用户说"存笔记" → file_write JSON + curl 存笔记
4. 输出结果

❌ 绕路（禁止）：
1. skill_list（浪费时间）
2. skill_read(name="lark-doc")（不用读整个 skill）
3. skill_read(name="getnote")（不用读整个 skill）
4. python ~/.ethan/skills/lark-doc/scripts/fetch_doc.py（python 常找不到，直接 lark-cli）
5. write_file(path="./save_note.py", content=...)（写脚本保存，绕路）
6. 手拼 JSON 字符串（易出错）
```

**铁律**：
1. **拿到链接先判断平台**
2. **判断后直接调工具，不读 skill**
3. **能一步到位就别绕路**
4. **lark-cli > python 脚本**（命令更稳）
5. **file_write JSON payload > 手拼 JSON**

---

## 完整示例

### 微信公众号（用户要总结）

**用户输入**：
```
https://mp.weixin.qq.com/s/dMAPeqDszlY0eDopwPAu0w 总结这篇文章
```

**正确执行**：
```
1. 识别平台：微信公众号 → web_fetch
2. web_fetch(url="https://mp.weixin.qq.com/s/dMAPeqDszlY0eDopwPAu0w") → 拿到 7134 字
3. 按「总结流程」章节输出：
   - 抓 1-2 个核心洞察
   - 拆树状结构（背景/核心洞察/子叙事）
   - 短句、关键词前置、数据具体
4. file_write(path="/tmp/note_payload.json", content=总结内容)
5. curl -d @/tmp/note_payload.json → 保存成功
6. 输出总结（按树状结构格式）
```

### 飞书文档（用户要存笔记）

**用户输入**：
```
https://xxx.feishu.cn/docx/OIXGdEBR2o2PrNxRUuVcSQaznEg 抽取成 markdown 存笔记
```

**正确执行**：
```
1. 识别平台：飞书文档 → lark-cli
2. 提取 token: OIXGdEBR2o2PrNxRUuVcSQaznEg
3. lark-cli docs +fetch --doc "OIXGdEBR2o2PrNxRUuVcSQaznEg" --doc-format markdown --as user > /tmp/lark_doc.json
4. cat /tmp/lark_doc.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['document']['content'])" > /tmp/lark_doc.md
5. file_read(path="/tmp/lark_doc.md") → 拿到 markdown 内容
6. file_write(path="/tmp/note_payload.json", content='{"type":"text","title":"文档标题","content":"...完整markdown内容..."}')
7. curl -d @/tmp/note_payload.json → 保存成功
8. 输出：✅ 已保存到 Get笔记（note_id: xxx）
```

---

## 质量检验清单

- [ ] 是否先判断平台？
- [ ] 是否直接调工具（没读 skill）？
- [ ] 是否用 file_write 写 JSON（没手拼）？
- [ ] 是否一步到位（没绕路）？
- [ ] 如果是"存笔记"，是否原样存 markdown（没总结）？
- [ ] 如果是"总结"，是否严格按树状结构输出？
- [ ] 如果是"总结"，核心洞察是否不超过 2 个？