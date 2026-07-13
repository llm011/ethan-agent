---
name: jd-shopping
description: "京东购物操作：订单查询导出、商品搜索比价、购物车管理。通过浏览器工具操作京东网站，支持批量提取订单记录、搜索商品、查看物流等。当用户提到「京东」「JD」「订单」「购物」「买东西」「搜商品」「查快递」时触发。"
trigger: "京东|JD|jd|订单|购物|买东西|搜商品|查快递|jd.com|京东订单"
fast_path: true
---

# 京东购物操作

通过 `browser_session` / `browser_tab` / `browser_page` 操作用户本机 Chrome 中已登录的京东账号。

## 核心原则

1. **优先 attach_current**——用户 Chrome 已登录京东，用 `browser_session(action="attach_current")` 接管当前标签页拿到登录态。不要用 `create` 开无 cookie 新窗口
2. **导航后先 wait**——京东 JS 渲染慢，每次 navigate 后必须 `browser_page(action="wait", ms=2000)`（详情页 ms=3000），等页面就绪再操作
3. **分层获取：snapshot 做概览，eval 做精确提取**——两者配合，不是非此即彼：
   - `snapshot(interactive=true)`：只拿可交互元素（link/button/text），token 可控（~5-15k），免疫 CSS class 改版。适合找链接、验证重定向、读评价标签、读颜色选项、读服务保障
   - `eval`：执行 JS 返回结构化数据。适合精确提取 SKU、价格、参数表
   - ❌ 不要用 `snapshot`（不带 interactive）读整页 DOM——会生成 30k+ 文本耗尽 token
4. **直接导航到目标 URL**——不要通过菜单一层层点进去，浪费步骤
5. **增量保存结果**——大量数据提取时用 `file_write`（append 模式）逐页保存，防止超时丢数据
6. **任务结束/失败都要 release session**——不管成功还是失败，最后都要 `browser_session(action="release")`。别留一堆 tab 开着
7. **选择器不依赖 CSS class**——京东用 CSS Modules hash 类名（如 `_card_1n6pm_83`），每次构建会变。优先用 `[data-sku]`、`[title]` 等属性选择器 + 文本内容匹配（`textContent.includes()`），不写 `.p-name`/`.gl-item` 这类 class 选择器
8. **eval 返回空 → 先排查 DOM**——不要反复换选择器试错。先 eval 排查脚本（`document.querySelectorAll("[data-sku]").length`、`document.title`、遍历文本节点），搞清真实结构再写提取脚本。最多排查 1 次
9. **流行度分析 + 同款兜底**——搜索后从 snapshot 的 link 节点统计品牌/型号反复出现频次，频次高的优先选为 top 候选。若某款详情页信息太少（如参数缺失），在列表中找同品牌/同系列另一款点进去补充
10. **过程透明 + 断连降级**——每步工具调用都要说明在做什么、为什么（让用户知道 agent 的思路）。浏览器断连时不要死等，用 `web_search` + `web_fetch` 补充参数信息作为降级路径，并告知用户数据来源
11. **并行打开详情页**——提取多个商品参数时，不要串行"导航→wait→提取"逐个来（5 个商品 = 5×(3s wait + 提取) ≈ 30s+）。应该用 `browser_tab(action="open", url=...)` 一次性打开多个 tab，并行 `eval` 提取，最后聚合。**但单次工具调用只能操作一个 tab**，所以并行是指"先批量 open 所有 tab（不用 wait），再用一个 eval 脚本遍历所有 tab 提取"

---

## ⚡ 订单查询导出（最常用）

### 步骤 1：接管浏览器（优先 attach_current）

```
browser_session(action="attach_current", title="京东订单")
browser_page(action="navigate", session=SID, url="https://order.jd.com/center/list.action")
browser_page(action="wait", session=SID, ms=2000)
```

如果 attach_current 失败（浏览器没打开或扩展未连接），才用 create：
```
browser_session(action="create", url="https://order.jd.com/center/list.action", title="京东订单")
browser_page(action="wait", session=SID, ms=2000)
```

### 步骤 2：用 eval 提取当前页订单数据

```
browser_page(action="eval", session=SID, script="""
(function() {
  const orders = [];
  document.querySelectorAll('.order-tb').forEach(tb => {
    const header = tb.querySelector('.dealtime, .tr-th');
    const dateEl = tb.querySelector('.dealtime');
    const orderIdEl = tb.querySelector('.order-num a, .number a');
    const statusEl = tb.querySelector('.order-status, .status span');
    const amountEl = tb.querySelector('.amount span, .sum-price');
    const nameEl = tb.querySelector('.p-name a, .goods-item a');
    orders.push({
      订单号: orderIdEl ? orderIdEl.textContent.trim() : '',
      日期: dateEl ? dateEl.textContent.trim() : '',
      状态: statusEl ? statusEl.textContent.trim() : '',
      金额: amountEl ? amountEl.textContent.trim() : '',
      商品名: nameEl ? nameEl.textContent.trim().substring(0, 50) : ''
    });
  });
  return JSON.stringify(orders);
})()
""")
```

### 步骤 3：翻页并继续提取

```
browser_page(action="eval", session=SID, script="""
(function() {
  const nextBtn = document.querySelector('.page-next, a:has(> .arrow-next)');
  if (nextBtn && !nextBtn.classList.contains('disabled')) {
    nextBtn.click();
    return 'navigated';
  }
  return 'last_page';
})()
""")
```

翻页后等待加载再提取：

```
browser_page(action="wait", session=SID, ms=2000)
// 重复步骤 2 的 eval 提取
```

### 步骤 4：保存结果 + 关闭 session

每提取一页就追加写入文件，防止中途超时丢数据：

```
file_write(path="~/Downloads/jd_orders.csv", content="订单号,日期,状态,金额,商品名\n...", mode="append")
```

**最后一定要关**：
```
browser_session(action="release")
```

### 大批量提取策略（100+ 订单）

对于跨年大量订单，分批进行避免单次超时：

1. 第一轮：提取第 1-5 页，保存
2. 第二轮：提取第 6-10 页，追加
3. 每轮结束告知用户进度，询问是否继续

也可以通过 URL 参数切换时间范围：
- 近三个月：`https://order.jd.com/center/list.action`
- 今年内：`https://order.jd.com/center/list.action?d=4`
- 去年：通过页面筛选器选择

---

## 商品搜索

### 步骤 1：接管浏览器 + 导航 + wait

```
browser_session(action="attach_current", title="京东搜索")
browser_page(action="navigate", session=SID, url="https://search.jd.com/Search?keyword={关键词URL编码}")
browser_page(action="wait", session=SID, ms=2000)
```

### 步骤 2：snapshot 概览 + 流行度分析（top N 选品）

先用 `snapshot(interactive=true)` 拿列表页的可交互元素（链接、按钮），token 可控且免疫 CSS 改版：

```
browser_page(action="snapshot", session=SID, interactive=true)
```

从返回的 link 节点统计品牌/型号反复出现频次——同款在多页/多位置出现，通常是热销款。频次高的优先纳入 top N 候选。

### 步骤 3：eval 精确提取列表项字段

> **京东已改版**（2025+）：旧选择器 `.gl-item`/`.p-name`/`.p-price` 全部失效。
> 新 DOM 用 CSS Modules hash 类名，唯一稳定容器是 `[data-sku]`。

```
browser_page(action="eval", session=SID, script="""
(function() {
  const items = [];
  document.querySelectorAll('[data-sku]').forEach(el => {
    const sku = el.getAttribute('data-sku');
    const titled = el.querySelector('[title]');
    const texts = Array.from(el.querySelectorAll('*'))
      .filter(e => e.children.length === 0)
      .map(e => e.textContent.trim())
      .filter(t => t && t.length > 1 && t.length < 100);
    const price = texts.find(t => /^\d+$/.test(t)) || '';
    const sales = texts.find(t => t.includes('已售')) || '';
    const shop = texts.find(t => t.includes('自营') || t.includes('旗舰') || t.includes('专卖')) || '';
    items.push({
      商品名: titled ? titled.getAttribute('title').substring(0, 80) : '',
      价格: price ? ('¥' + price) : '',
      销量: sales,
      店铺: shop,
      SKU: sku,
      链接: 'https://item.jd.com/' + sku + '.html'
    });
  });
  return JSON.stringify(items.slice(0, 20));
})()
""")
```

**最后**：`browser_session(action="release")`

### 图书搜索

图书搜索可直接用分类 URL：

```
https://search.jd.com/Search?keyword={关键词}&enc=utf-8&wq={关键词}&cat=1713,3258,3297
```

---

## 订单搜索（按关键词查找历史订单）

京东订单页支持按商品名/订单号搜索，比逐页翻找高效得多：

### 方式 1：URL 参数搜索

```
browser_page(action="navigate", session=SID, url="https://order.jd.com/center/list.action?search=0&keyword={关键词URL编码}&d=1")
browser_page(action="wait", session=SID, ms=2000)
```

参数说明：
- `keyword`：搜索关键词（商品名、订单号等），需 URL 编码
- `d=1`（近三个月）/ `d=2`（今年内）/ `d=3`（去年）/ `d=4`（更早）

### 方式 2：eval 操作搜索框

```
browser_page(action="eval", session=SID, script="""
(function() {
  const input = document.querySelector('#search-keyword, .search-box input');
  if (!input) return 'no_search_input';
  input.value = '搜索关键词';
  input.dispatchEvent(new Event('input', {bubbles: true}));
  const btn = document.querySelector('.search-box .btn, .btn-search');
  if (btn) btn.click();
  return 'searching';
})()
""")
```

搜索后等待 2 秒再用提取脚本获取结果。

---

## 商品详情页

从搜索结果获取 SKU 后直接导航到详情页提取参数。

> **京东详情页已改版**（2025+）：旧选择器 `.sku-name`/`.itemInfo-wrap`/`.p-price`/`.Ptable-item` 全部失效。
> 新 DOM 用 CSS Modules hash 类名，商品名在 `<title>` 标签，参数在 `[class*=parameter]` 容器中。

### 导航 + 验证

```
browser_page(action="eval", session=SID, script="window.location.href = \"https://item.jd.com/{SKU}.html\"; \"navigating\"")
browser_page(action="wait", session=SID, ms=3000)
```

验证是否被重定向（旧 `.sku-name` 已失效，改用 title 检查）：
```
browser_page(action="eval", session=SID, script="(function(){return document.title.includes('京东') && !document.title.includes('欢迎登录') ? 'ok' : 'redirected'})()")
```
如果返回 "redirected"，说明登录态丢失，**立刻告诉用户需要去 Chrome 登录京东**。

### 分层提取：先 snapshot 概览，再 eval 精确取参

**Step 1：snapshot(interactive=true) 概览**——读评价标签、颜色选项、服务保障、物流等可交互区域信息（~5-15k token，免疫 CSS 改版）：

```
browser_page(action="snapshot", session=SID, interactive=true)
```

**Step 2：eval 精确提取参数表 + 价格 + 店铺**（通用版，不依赖 CSS class，不绑定品类）：

```
browser_page(action="eval", session=SID, script="""
(function(){
  const r = {};
  // 商品名：从 title 提取，去掉京东后缀
  r.title = document.title.replace(/【.*?】/g, "").replace(/-京东$/, "").trim();

  // 价格：找页面中带 ¥ 的叶子节点
  r.prices = [];
  for (const el of document.querySelectorAll("*")) {
    if (el.children.length === 0 && el.textContent.includes("¥")) {
      const t = el.textContent.trim();
      if (t.length < 20) r.prices.push(t);
      if (r.prices.length >= 3) break;
    }
  }

  // 店铺
  r.shop = "";
  for (const el of document.querySelectorAll("*")) {
    if (el.children.length === 0) {
      const t = el.textContent.trim();
      if (t.includes("自营") || t.includes("旗舰") || t.includes("专卖")) {
        r.shop = t.substring(0, 50); break;
      }
    }
  }

  // 规格选项（颜色/尺码/型号等）
  r.options = Array.from(document.querySelectorAll("[class*=series-item], [class*=sku-item], [class*=item-selected]"))
    .map(e => e.textContent.trim()).filter(t => t && t.length < 40).slice(0, 10);

  // 参数表：通用提取，找 [class*=parameter] 或 [class*=Param] 容器
  r.params = [];
  const paramContainer = document.querySelector("[class*=parameter], [class*=Param], [class*=detail-spec]");
  if (paramContainer) {
    const leaves = Array.from(paramContainer.querySelectorAll("*"))
      .filter(e => e.children.length === 0)
      .map(e => e.textContent.trim())
      .filter(t => t && t.length > 1 && t.length < 80);
    r.params = leaves.slice(0, 30);
  }

  return JSON.stringify(r, null, 2);
})()
""")
```

**Step 3：同款兜底**——若 eval 返回的 params 为空或信息明显缺失，回到搜索列表找同品牌/同系列另一款 SKU，重复 Step 1-2 补充。

### 批量详情页提取（5+ 个商品）—— 并行策略

**❌ 旧方式（串行，慢）**：逐个导航 → wait → 提取，5 个商品需要 20+ 步、30s+
**✅ 新方式（并行，快）**：先批量打开 tab，再逐个 eval 提取，省去重复 wait

#### Step 1：批量打开 tab（不用 wait）

一次工具调用打开一个 tab，连续调用 5 次（不需要中间 wait，浏览器自己会加载）：

```
// 对每个 SKU：
browser_tab(action="open", url="https://item.jd.com/{SKU}.html")
```

> 也可以用 `browser_session(action="create", url="https://item.jd.com/{SKU}.html")` 创建多个独立会话，
> 但 tab 方式更轻量。打开后统一等 3 秒让所有页面加载完成：
> `browser_page(action="wait", ms=3000)`

#### Step 2：逐个 tab 提取参数

用 `browser_page(session=SID, tab=TAB_ID, action="eval", ...)` 指定 tab 提取。每个 tab 只需 1 次 eval（合并 snapshot + eval 为单次提取）：

```
browser_page(action="eval", session=SID, tab=TAB_ID, script="""
(function(){
  const r = {};
  r.title = document.title.replace(/【.*?】/g, "").replace(/-京东$/, "").trim().substring(0, 60);
  r.sku = (location.href.match(/item\\.jd\\.com\\/(\\d+)/) || [])[1] || '';

  // 价格：只找带 ¥ 的短文本叶子节点
  r.prices = [];
  for (const el of document.querySelectorAll("*")) {
    if (el.children.length === 0 && el.textContent.includes("¥")) {
      const t = el.textContent.trim();
      if (t.length < 15 && /^\\¥?\\d+/.test(t.replace("¥",""))) { r.prices.push(t); if (r.prices.length>=2) break; }
    }
  }

  // 店铺
  r.shop = "";
  for (const el of document.querySelectorAll("*")) {
    if (el.children.length === 0) {
      const t = el.textContent.trim();
      if ((t.includes("自营") || t.includes("旗舰")) && t.length < 30) { r.shop = t; break; }
    }
  }

  // 参数表：只提取 [class*=parameter] 容器内的键值对，不返回整页 DOM
  r.params = {};
  const paramContainer = document.querySelector("[class*=parameter], [class*=Param], [class*=detail-spec]");
  if (paramContainer) {
    // 找键值对：通常是 dt/dd 或相邻的文本节点
    const dts = paramContainer.querySelectorAll("dt, [class*=param-name], [class*=item-name]");
    const dds = paramContainer.querySelectorAll("dd, [class*=param-value], [class*=item-value]");
    for (let i = 0; i < Math.min(dts.length, dds.length); i++) {
      const k = dts[i].textContent.trim();
      const v = dds[i].textContent.trim();
      if (k && v && k.length < 20 && v.length < 50) r.params[k] = v;
    }
    // 兜底：如果没有 dt/dd，提取叶子节点文本列表（限 15 个，每个限 40 字）
    if (Object.keys(r.params).length === 0) {
      const leaves = Array.from(paramContainer.querySelectorAll("*"))
        .filter(e => e.children.length === 0)
        .map(e => e.textContent.trim())
        .filter(t => t && t.length > 1 && t.length < 40);
      r.params._leaves = leaves.slice(0, 15);
    }
  }

  // 销量/评价数
  r.sales = "";
  for (const el of document.querySelectorAll("*")) {
    if (el.children.length === 0) {
      const t = el.textContent.trim();
      if (t.includes("万+") && t.includes("评价")) { r.sales = t.substring(0, 30); break; }
      if (/\\d+\\+?评价/.test(t) && t.length < 20) { r.sales = t; break; }
    }
  }

  return JSON.stringify(r);
})()
""")
```

#### Step 3：关闭 tab + 聚合

提取完所有 tab 后，逐个关闭：
```
browser_tab(action="close", tab_id=TAB_ID)
```

最后汇总成对比表格。**断连降级**：若中途 extension_not_connected，已提取的数据保留，未提取的用 `web_search` + `web_fetch` 补充。

**最后**：`browser_session(action="release")`

### 提取商品评价

```
browser_page(action="eval", session=SID, script="document.querySelector('[class*=comment]')?.scrollIntoView()")
browser_page(action="wait", session=SID, ms=2000)
```

```
browser_page(action="eval", session=SID, script="""
(function(){
  const reviews = [];
  const items = document.querySelectorAll("[class*=comment-item], [class*=Comment]");
  items.forEach((el, i) => {
    if (i >= 10) return;
    const texts = Array.from(el.querySelectorAll("*")).filter(e => e.children.length === 0).map(e => e.textContent.trim());
    const content = texts.find(t => t.length > 20 && t.length < 200) || "";
    const time = texts.find(t => /\d{4}-\d{2}-\d{2}/.test(t)) || "";
    if (content) reviews.push({ 内容: content.substring(0, 100), 时间: time });
  });
  return JSON.stringify(reviews);
})()
""")
```

---

## 路由逻辑

| 用户意图 | 做什么 |
|---------|--------|
| 查京东订单/导出订单 | attach_current → 导航订单页 → wait → eval 提取 → release |
| 搜索订单（找某个商品的订单） | 用 keyword 参数导航订单搜索 → wait → eval 提取结果 → release |
| 搜索商品/比价 | attach_current → 导航搜索页 → wait → snapshot 概览 + 流行度分析 → eval 提取列表 → 表格呈现 → release |
| 查商品详情/评价 | 导航 item.jd.com/{sku}.html → wait → 验证未重定向 → snapshot 概览 + eval 精确提取 → release |
| 查物流/快递 | 订单页找到对应订单 → 点击"查看物流" |
| 查购物车 | 导航 `https://cart.jd.com/cart_index/` → wait → eval 提取 → release |

---

## 输出格式

默认输出 CSV，表头：

```
订单号,日期,状态,金额,商品名
```

用户要求其他格式（Markdown 表格、JSON）时按需调整。商品详情对比通常用 Markdown 表格呈现。

---

## 关键纪律

```
✅ 正确做法：
1. browser_session attach_current（拿登录态）→ navigate → wait → snapshot 概览 → eval 精确提取
2. nav 后先 wait 再操作，京东页面 JS 渲染需要时间
3. 数据提取分层：snapshot(interactive=true) 看概览，eval 取精确字段
4. file_write 增量保存（大批量时逐页追加）
5. 翻页用 eval 点击下一页按钮
6. 搜索后做流行度分析，频次高的优先选为候选
7. 详情页信息不足时找同品牌另一款补充
8. 每步工具调用说明在做什么、为什么（过程透明）
9. 浏览器断连立即降级到 web_search + web_fetch，告知用户数据来源
10. 任务完成/失败都 browser_session release
11. 批量详情页用并行策略：先批量 browser_tab open，再逐个 eval 提取，不要串行 navigate+wait+extract

❌ 禁止做法：
1. 用 snapshot（不带 interactive）读取整页 DOM（30k+ token 浪费）
2. 通过菜单层层导航到目标页（浪费步骤）
3. 不 wait 就 eval（页面还没渲染完，选择器找不到元素）
4. 一次性提取所有页面不保存中间结果（超时丢数据）
5. 用 web_fetch 访问京东（需要登录态，拿不到数据）
6. 写 Python/Playwright 脚本操作京东（直接用 browser 工具）
7. 任务结束不 release session（留一堆 tab 开着）
8. 浏览器断连后死等或反复重试同一操作（应立即降级到 web_search）
9. eval 返回空时反复换选择器试错（应先排查 DOM，最多 1 次）
```

---

## 常见问题处理

| 问题 | 解决 |
|------|------|
| 页面要求登录 | 提示用户在 Chrome 中登录京东，登录后告诉我继续 |
| eval 返回空数组 | **先排查 DOM**：eval `document.querySelectorAll('[data-sku]').length` 等探查脚本搞清结构，不要反复换选择器试错。最多排查 1 次 |
| 商品详情被重定向到首页 | eval 先检查商品名是否存在；不存在说明要登录，告诉用户去 Chrome 里登录 |
| 翻页后数据没变 | 加 wait(ms=2000) 等待 AJAX 加载完成 |
| 订单跨度大提取慢 | 分批提取，每 5 页保存一次，告知用户进度 |
| attach_current 失败 | 改用 browser_session(action="create", url="...") 作为兜底 |
| 浏览器插件断连（extension_not_connected） | 立即停止 browser 操作，改用 web_search + web_fetch 降级获取参数，告知用户数据来源 |
| 某款详情页参数缺失 | 回搜索列表找同品牌/同系列另一款 SKU，重新导航 + snapshot + eval 补充 |

---

## 工具速查

- `browser_session`：attach_current / create / release / close
- `browser_tab`：open / list / activate / close
- `browser_page`：navigate / snapshot / click / fill / type / eval / screenshot / wait
- `web_search` / `web_fetch`：浏览器断连时的降级路径

activate_tools: browser_session, browser_tab, browser_page, file_write
