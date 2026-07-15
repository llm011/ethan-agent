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
6. **🚫 视频链接（YouTube/Bilibili/抖音）禁止 web_search / web_fetch** → 必须走 getnote link 存笔记（见「视频链接」章节）

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
| `youtube.com/watch?v=` `youtu.be/*` | YouTube 视频 | **getnote link 存笔记**（异步提取）⚠️ 可能失败需降级 | 最高 |
| `bilibili.com/video/*` `b23.tv/*` | Bilibili 视频 | **getnote link 存笔记**（异步提取） | 最高 |
| `douyin.com/video/*` `douyin.com/jingxuan?modal_id=` `iesdouyin.com/share/video/*` | 抖音视频 | **getnote link 存笔记**（异步提取）✅ 实测成功 | 最高 |
| 其他 URL | 通用网页 | **web_fetch 先试**，失败降级 agent-browser | 先高后中 |

**判断逻辑**：
```python
# ⚠️ 视频链接必须最先判断，走 getnote 异步提取，禁止 web_search/web_fetch
# 实测：douyin.com/video/ 和 douyin.com/jingxuan?modal_id= 均兼容
video_patterns = ["youtube.com/watch", "youtu.be/", "bilibili.com/video", "b23.tv/", "douyin.com/video", "douyin.com/jingxuan", "iesdouyin.com/share/video"]
if any(p in url for p in video_patterns):
    return "getnote-link"  # → 调 Get笔记 save API (type=link)，绝不走 web_search

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

### 飞书文档（最快路径 — 4 步完成）

**直接调 lark-cli，不检查凭证，不读 skill，不写 python 脚本**：

```bash
# 步骤 1（shell）：提取 token + lark-cli 导出 + 解析 JSON + 写 markdown（一条命令完成）
# URL 格式（三种域名都支持）：
#   https://xxx.feishu.cn/docx/OIXGdEBR2o2PrNxRUuVcSQaznEg
#   https://xxx.larksuite.com/wiki/TbB6w6MlSiXZD5k3kwkc4PRpnxd
#   https://bytedance.larkoffice.com/wiki/TbB6w6MlSiXZD5k3kwkc4PRpnxd
# Token = 最后一段路径（去掉 /docx/ 或 /wiki/ 后的部分）
# 导出后顺手把分栏 <grid><column> 转成 markdown 表格，否则分栏内容会挤成一坨。
lark-cli docs +fetch --doc "TOKEN" --doc-format markdown --as user | python3 -c "
import sys, json, re
raw = json.load(sys.stdin)['data']['document']['content']
def _grid(m):
    cols = [c.strip() for c in re.findall(r'<column[^>]*>(.*?)</column>', m.group(1), re.S)]
    if not cols: return ''
    if len(cols) == 1: return cols[0]
    h = '| ' + ' | '.join(' ' for _ in cols) + ' |'
    s = '| ' + ' | '.join('---' for _ in cols) + ' |'
    b = '| ' + ' | '.join(c.replace('\n', '<br>') for c in cols) + ' |'
    return '\n' + h + '\n' + s + '\n' + b + '\n'
print(re.sub(r'<grid>(.*?)</grid>', _grid, raw, flags=re.S), end='')
" > /tmp/lark_doc.md

# 步骤 2（file_read）：读 markdown → 内容进 agent context
file_read(path="/tmp/lark_doc.md")

# 步骤 3（file_write）：写 JSON payload（用户要存笔记时）
file_write(path="/tmp/note_payload.json", content='{"type":"text","title":"文档标题","content":"完整markdown内容"}')

# 步骤 4（shell）：curl 存笔记
curl -s -X POST "https://openapi.biji.com/open/api/v1/resource/note/save" \
  -H "Authorization: $GETNOTE_API_KEY" \
  -H "X-Client-ID: $GETNOTE_CLIENT_ID" \
  -H "Content-Type: application/json" \
  -d @/tmp/note_payload.json
```

**4 步，每步 2-3 秒，总耗时 ~10 秒。**

**铁律**：
- ✅ 一条 shell 命令完成导出+解析+写文件
- ✅ 用 `file_write` 写 JSON payload，再 `curl -d @文件`

### 微信公众号（必须处理图片）

**⚠️ 微信图片在 `data-src` 属性。`web_fetch` 已自动提取图片 URL 列表（优先 data-src），附在正文末尾。**

**执行流程**：

```bash
# 步骤 1：web_fetch 拿正文 + 图片列表
web_fetch(url="https://mp.weixin.qq.com/s/xxx")
# 输出格式：
#   ...正文内容...
#   ---图片列表---
#   1. https://mmbiz.qpic.cn/.../640?wx_fmt=jpeg
#   2. https://mmbiz.qpic.cn/.../640?wx_fmt=png

# 步骤 2：如果有图片列表，下载并上传到 CDN
mkdir -p /tmp/wx_imgs
# 从输出中提取图片 URL（用 shell 写脚本或手动逐个处理）
i=1
for url in $(grep -oP 'https://mmbiz\.qpic\.cn[^ \n]+' <<< "$web_fetch_output"); do
  curl -sL -A "Mozilla/5.0" "$url" -o "/tmp/wx_imgs/img_${i}.jpg"
  python ~/.ethan/skills/upload-cdn/scripts/upload_cdn.py "/tmp/wx_imgs/img_${i}.jpg" "wx/img_${i}.jpg"
  i=$((i+1))
done

# 步骤 3：构建完整 markdown（正文 + CDN 图片链接）
# 将正文中的原图片链接替换为 CDN URL，或直接在 markdown 里用 CDN URL 插入图片

# 步骤 4：存笔记（调用 Get笔记 API）
file_write(path="/tmp/note_payload.json", content='{"type":"text","title":"标题","content":"完整markdown"}')
curl -s -X POST "https://openapi.biji.com/open/api/v1/resource/note/save" \
  -H "Authorization: $GETNOTE_API_KEY" \
  -H "X-Client-ID: $GETNOTE_CLIENT_ID" \
  -H "Content-Type: application/json" \
  -d @/tmp/note_payload.json
```

**铁律**：
- ✅ `web_fetch` 已提取图片 URL 列表（data-src 优先），附在正文末尾
- ✅ 看到"---图片列表---"就说明有图片，必须下载并上传 CDN
- ✅ upload-cdn 有缓存，同 hash 直接返回
- ✅ 如果图片列表为空（没有"---图片列表---"），直接存正文即可

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

### 视频链接（YouTube / Bilibili / 抖音）— getnote 异步提取

**视频页面 JS 渲染重、反爬强，web_fetch / agent-browser 都拿不到有用内容。交给 Get笔记服务端异步提取。**

```bash
# 步骤 1：写 JSON payload
file_write(path="/tmp/note_payload.json", content='{"note_type":"link","link_url":"视频URL"}')

# 步骤 2：curl 调 Get笔记 save API（link 模式）
curl -s -X POST "https://openapi.biji.com/open/api/v1/resource/note/save" \
  -H "Authorization: $GETNOTE_API_KEY" \
  -H "X-Client-ID: $GETNOTE_CLIENT_ID" \
  -H "Content-Type: application/json" \
  -d @/tmp/note_payload.json

# 步骤 3：解析响应（普通链接是异步的）
# 成功 → {"success":true,"data":{"tasks":[{"task_id":"xxx","url":"..."}],"created_count":1}}
# 失败 → {"success":false,"error":{"code":10001,"message":"unauthorized"}}
# ⚠️ task_id 在 data.tasks[0].task_id，需要轮询 /task/progress
```

**回复用户**：
> ✅ 已把这个视频存到 Get笔记了，服务端正在提取内容（task_id: `xxx`）。
> 过几分钟你再来问我「那个视频讲了什么」，我就能查到笔记内容了。

**⚠️ 不要用 web_fetch 或 agent-browser 抓视频页面**，直接走 getnote link 存笔记。
**⚠️ 用户回来问视频内容时** → 调 `GET /open/api/v1/resource/note/detail?note_id=xxx` 查详情。

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
