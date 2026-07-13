---
name: flomo
trigger: flomo|浮墨|浮墨笔记|flomoapp|记灵感|灵感记录|卡片笔记|碎片笔记|快速记一下|随手记|闪念|闪念笔记
description: flomo 浮墨笔记助手 — 读取/搜索/写入/删除短笔记与灵感（浏览器 UI 自动化，无需 key）+ 写入备选 Webhook。适合碎片化快速记录；长笔记/知识管理用 getnote。
---

> **多副本同步提醒**：本文件改完后，必须同步到以下两份，否则线上 agent 读到的仍是旧版：
> - host：`~/.ethan/skills/flomo/SKILL.md`
> - 容器内 volume（运行中 agent 实际读取）：`/root/.ethan/skills/flomo/SKILL.md`，用 `docker cp` 推送
> 三份不一致会导致「改了不生效 / 重建镜像后和 volume 对不上」。

# flomo Skill

## 适用边界

**flomo（本技能）**：短笔记、灵感、闪念、碎片化快速记录。
**getnote**：长笔记、知识管理、笔记列表/详情/搜索/删除。

- 用户只说"记笔记/存笔记/我的笔记"等泛化词 → **走 getnote**
- 用户明确提到 flomo / 浮墨，或语境是"记个灵感/闪念/卡片" → **走本技能**

---

## 全局注意事项

### 浏览器前置条件（读取/写入/删除/搜索均需）
- Chrome 已安装 ethan 扩展，用 **Web UI Token**（`dev-ethan.sh` 启动日志里打印）连上服务（默认 8910）。连上后日志显示 `browser ws: extension connected`。
- 本机浏览器已登录 flomo —— 扩展复用你的登录会话，**所有浏览器操作均无需任何 api_key / token**。
- 若页面跳转到登录页：告知用户在浏览器重新登录 `https://v.flomoapp.com/mine/`，不要用 api_key 兜底。

### ⚠️ OOM 红线（所有 flomo 操作必须遵守）
flomo 首页 DOM 极重（侧边栏 400+ 标签），`browser_page snapshot` 或框架整页截图会把上下文/响应撑爆被 SIGKILL。**所有操作一律用 `browser_page eval` 跑紧凑 JS、只回传小 JSON，绝不 snapshot / 整页截图**。若单次调用仍 OOM，缩小返回内容后重试。

---

## 读取笔记

1. `browser_tab` 打开 `https://v.flomoapp.com/mine/`。
2. 用 `browser_page eval` 跑下面的脚本，取最新 N 条：

```javascript
(async () => {
  const N = 5;
  const cards = [...document.querySelectorAll('.display.showMemoInsight')];
  const data = cards.slice(0, N).map(card => ({
    text: (card.innerText || '').trim().slice(0, 2000),
    images: [...card.querySelectorAll('img[src*="static.flomoapp.com"]')].map(i => i.src)
  }));
  return JSON.stringify(data);
})()
```

返回数组，每项含 `text`（正文含时间/标签）与 `images`（OSS 预签名直链，可直接 `curl` 下载，无需鉴权）。

> **首页折叠提醒**：flomo 首页卡片默认折叠长文，DOM 拿到的 `innerText` 常是**片段而非全文**（验证时多次踩到）。若 `text` 明显被截断、或用户要的是某条笔记完整内容，需先点开该卡片展开全文，再取完整 `innerText`，不要自信地当成全文返回。

---

## 搜索笔记

1. `browser_tab` 打开/聚焦 `https://v.flomoapp.com/mine/`。
2. 定位搜索框 `INPUT.el-input__inner[placeholder="⌘+K"]`，用 `fill` 写入关键词，等 ~500ms 或 `press Enter`。
3. 搜索结果页 DOM 很轻（通常只有几条），用 `browser_page eval` 抽取：

```javascript
(() => {
  const cards = [...document.querySelectorAll('.display.showMemoInsight')];
  const data = cards.map(card => ({
    text: (card.innerText || '').trim().slice(0, 2000),
    images: [...card.querySelectorAll('img[src*="static.flomoapp.com"]')].map(i => i.src),
    tags: [...card.querySelectorAll('[tag]')].map(e => e.getAttribute('tag'))
  }));
  return JSON.stringify({ count: data.length, notes: data });
})()
```

> 比扫首页快很多；绝不 snapshot 整页（见全局 OOM 红线）。

---

## 读取标签列表

用户问「我有哪些标签 / 某标签下有哪些子标签」时走这里。

用 `browser_page eval` 跑下面脚本（先读 Vuex store 取速，取不到回退 DOM 扫描）：

> **实测注意**：`window.__INITIAL_STATE__` 在 flomo 根本不存在（`undefined`）。真实 store 是 `window.__flomoVuexStore`，但全量标签字段默认为空（需先开「标签管理」面板才填充）。**最稳路径是 DOM 扫描**（已验证可拿全量 417 个）。

```javascript
(async () => {
  const collectDOM = () => { const s = new Set(); document.querySelectorAll('[tag]').forEach(el => { const t = el.getAttribute('tag'); if (t) s.add(t); }); return s; };
  try {
    const st = window.__flomoVuexStore && window.__flomoVuexStore.state;
    const tm = st && st.tagManager && st.tagManager.tags;
    if (Array.isArray(tm) && tm.length) {
      const paths = tm.map(x => typeof x === 'string' ? x : (x.name || x.tag || x.path || '')).filter(Boolean);
      if (paths.length) return JSON.stringify({ route: 'store', tags: paths });
    }
  } catch (e) {}
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const sb = document.querySelector('.sidebar') || document.querySelector('#sidebar');
  const seen = collectDOM();
  let last = -1, stable = 0;
  for (let i = 0; i < 80; i++) {
    const closed = Array.from(document.querySelectorAll('.tag-expand-button:not(.expanded), button[aria-expanded="false"]'));
    if (closed.length) closed.forEach(b => b.click());
    await sleep(120);
    collectDOM().forEach(t => seen.add(t));
    const atBottom = sb ? (sb.scrollTop + sb.clientHeight >= sb.scrollHeight - 5) : true;
    if (seen.size === last && closed.length === 0 && atBottom) { if (++stable >= 4) break; } else stable = 0;
    last = seen.size;
    if (sb) sb.scrollTop += 800; else window.scrollBy(0, 800);
    await sleep(120);
  }
  collectDOM().forEach(t => seen.add(t));
  return JSON.stringify({ route: 'dom', tags: Array.from(seen) });
})()
```

返回 `{"route":"store"|"dom","tags":[...]}` —— `tags` 是完整路径字符串数组（如 `["领域/财富","work","mac",...]`）。

汇报：总数 + 顶层标签（不含 `/`）+ 用户问到的子树（按前缀 + `/` 层级匹配）。

---

## 写入笔记（浏览器 UI）⭐ 推荐

1. `browser_tab` 打开 `https://v.flomoapp.com/mine/`。
2. `browser_page fill` 把整段内容（含末尾 `#标签`）一次性写入 `div.tiptap.ProseMirror`（占位提示「现在的想法是...」）。
3. `browser_page click` 点提交按钮 `svg.saveBtn`（输入为空时是 `svg.disableSave`，不可点）。
4. 等 1~2 秒，确认内容已出现在首页列表顶部。

写入前务必遵守下方「标签规范」，**优先复用存量标签**。

---

## 写入笔记（Webhook，备选 · 需 key）

```
POST https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/
Content-Type: application/json
{"content": "笔记内容 #标签"}
```

**获取 key**：flomo App → 设置 → 「API 及第三方工具」→ Webhook URL 里提取 `<key>`。

**首次配置**：
```bash
file_write(path="$HOME/.ethan/.secrets/flomo.env", content='FLOMO_WEBHOOK_KEY="<webhook-key>"')
chmod 600 ~/.ethan/.secrets/flomo.env
```

**响应**：`{"code":0}` 成功；`{"code":-1}` key 失效或频率限制（引导用户重新获取 key）；其他 code 原样反馈。

写入频率：约 10 条/分钟，批量时间隔 ≥100ms。

---

## 删除笔记（浏览器 UI）

### 关键策略：先搜后删
首页 DOM 极重，直接在首页操作极易耗尽步数。**先在搜索框搜目标笔记唯一关键词，跳到搜索结果页再删**，结果页 DOM 很轻。

### 步骤
1. 搜索定位目标笔记（参见「搜索笔记」）。
2. 用 `browser_page eval` 跑下面脚本（把 `__目标文本__` 换成唯一片段）：

```javascript
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const vis = el => el && el.offsetParent !== null;
  const KEY = '__目标文本__';
  const cards = [...document.querySelectorAll('.display.showMemoInsight')];
  const target = cards.find(c => (c.innerText || '').includes(KEY));
  if (!target) return JSON.stringify({ok:false, step:'locate', msg:'未找到目标笔记'});
  const trigger = [...target.querySelectorAll('*')].find(b => {
    if (!vis(b)) return false;
    return /dropdown|more|operation|menu|ellipsis/i.test('' + b.className);
  });
  if (!trigger) return JSON.stringify({ok:false, step:'menu', msg:'没找到「...」菜单按钮'});
  trigger.click();
  await sleep(400);
  const items = [...document.querySelectorAll('li,div,[role=menuitem],.el-dropdown-menu__item')].filter(vis);
  const del = items.find(b => /删除/.test(b.innerText || ''));
  if (del) del.click();
  await sleep(500);
  const cfrms = [...document.querySelectorAll('button,.el-button')].filter(vis).filter(b => /确定|删除/.test(b.innerText || ''));
  const ok = cfrms.find(b => /确定/.test(b.innerText || '')) || cfrms[0];
  if (ok) ok.click();
  await sleep(800);
  const after = [...document.querySelectorAll('.display.showMemoInsight')];
  const gone = !after.some(c => (c.innerText || '').includes(KEY));
  return JSON.stringify({ok:true, deleted: gone});
})()
```

> **安全护栏**：
> 1. KEY 必须足够唯一（优先用完整标签如 `领域/思维模型`），绝不用宽泛词。
> 2. **删除前先只读 eval 找出笔记，把原文念给用户确认，用户明确确认后再点删除**。误删不可逆。

---

## 标签规范（重要）

> 用户 flomo 现有 417 个标签，加笔记时**优先复用存量标签**。

### 五大主框架类目

| 类目 | 含义 | 常见子标签 |
|------|------|-----------|
| `#领域` | 知识 / 认知领域 | 领域/财富、领域/成长、领域/思维模型、领域/心理学、领域/写作 |
| `#项目` | 进行中的项目 | 项目/AI、项目/写作、项目/时间管理、项目/如何阅读 |
| `#输入` | 外部输入源 / 素材 | 输入/书、输入/电影、输入/得到、输入/帆书、输入/网络 |
| `#闪念` | 突发灵感、临时收集 | 闪念/思考、闪念/收集、闪念/生活、闪念/微信文章 |
| `#永久` | 长期沉淀的精华笔记 | 永久/思考、永久/素材、永久/名词、永久/沟通 |

### 上下文 / 来源 / 状态标签（可与框架类目叠加）
- 来源/设备：`work`、`mac`、`code`
- 状态/动作：`todo`、`fix`、`checklist`、`daily`、`archived`
- 生活场景：`旅游`、`日记`、`权益`、`小创新`、`资源`、`临时`、`试试`

### 格式纪律
- 标签以 `#` 开头、紧跟文字、无空格（`#阅读` ✓，`# 阅读` ✗）
- 中文为主；标签内无空格，多词用 `-` 连接（如 `读书笔记-认知觉醒`）
- 多级用 `/`（`#阅读/认知觉醒`），深度以 2-3 层为主
- **标签置底**：统一放在 content 末尾，多标签空格分隔
- **不确定时先读取标签列表确认**，仅有真正新领域/新项目时才新建

---

## 本地标签索引

路径：`~/.ethan/.cache/flomo-tags.txt`，每行一个标签 + 简短说明。

维护：写入前 `file_read` 确认标签是否已存在；用到新标签后追加（去重）；用户问标签时优先走浏览器读取，浏览器不可用时回退本地索引。

---

## 后端接口（为何不用）

接口根 `https://flomoapp.com/api/v1` 存在，但：
1. 未对 `v.flomoapp.com` 开放 CORS，外部 `fetch` 直接失败；
2. 登录态 token 在 httpOnly cookie / 运行时内存中，外部脚本无法读取。

结论：**所有操作走浏览器自动化**，不要从服务端 `curl` flomo API。

activate_tools: shell, file_write, file_read, browser_page, browser_tab, browser_session
