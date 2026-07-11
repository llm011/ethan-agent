---
name: jd-shopping
description: "京东购物操作：订单查询导出、商品搜索比价、购物车管理。通过浏览器工具操作京东网站，支持批量提取订单记录、搜索商品、查看物流等。当用户提到「京东」「JD」「订单」「购物」「买东西」「搜商品」「查快递」时触发。"
trigger: "京东|JD|jd|订单|购物|买东西|搜商品|查快递|jd.com|京东订单"
fast_path: true
---

# 京东购物操作

通过 `browser_session` / `browser_tab` / `browser_page` 操作用户本机 Chrome 中已登录的京东账号。

## 核心原则

1. **必须使用用户真实 Chrome**——京东需要登录态，用 `browser_session` 接管已登录的浏览器
2. **数据提取用 `eval`，不用 `snapshot`**——snapshot 会生成巨量 DOM 文本耗尽输出 token，eval 执行 JS 直接返回结构化数据
3. **直接导航到目标 URL**——不要通过菜单一层层点进去，浪费步骤
4. **增量保存结果**——大量数据提取时用 `file_write`（append 模式）逐页保存，防止超时丢数据

---

## ⚡ 订单查询导出（最常用）

### 步骤 1：创建浏览器会话

```
browser_session(action="create", url="https://order.jd.com/center/list.action", title="京东订单")
```

如果用户已经打开京东：

```
browser_session(action="attach_current", title="京东订单")
browser_page(action="navigate", session=SID, url="https://order.jd.com/center/list.action")
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

### 步骤 4：保存结果

每提取一页就追加写入文件，防止中途超时丢数据：

```
file_write(path="~/Downloads/jd_orders.csv", content="订单号,日期,状态,金额,商品名\n...", mode="append")
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

### 基础搜索

```
browser_session(action="create", url="https://search.jd.com/Search?keyword={关键词URL编码}", title="京东搜索")
```

### 提取搜索结果

```
browser_page(action="eval", session=SID, script="""
(function() {
  const items = [];
  document.querySelectorAll('.gl-item, .J_goodsList li').forEach(li => {
    const name = li.querySelector('.p-name em, .p-name a');
    const price = li.querySelector('.p-price strong i, .p-price span');
    const shop = li.querySelector('.p-shop a, .curr-shop a');
    const comments = li.querySelector('.p-commit a');
    const link = li.querySelector('.p-name a');
    items.push({
      商品名: name ? name.textContent.trim().substring(0, 60) : '',
      价格: price ? price.textContent.trim() : '',
      店铺: shop ? shop.textContent.trim() : '',
      评论数: comments ? comments.textContent.trim() : '',
      链接: link ? 'https://item.jd.com/' + (link.getAttribute('href') || '').match(/\\d+/)?.[0] + '.html' : ''
    });
  });
  return JSON.stringify(items.slice(0, 20));
})()
""")
```

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

从搜索结果或订单中获取某个商品的详细信息：

### 导航到商品页

```
browser_page(action="navigate", session=SID, url="https://item.jd.com/{sku_id}.html")
```

SKU ID 来源：搜索结果中提取的链接、订单中的商品链接、或用户直接给出。

### 提取商品详情

```
browser_page(action="eval", session=SID, script="""
(function() {
  const info = {};
  // 商品名
  const nameEl = document.querySelector('.sku-name, .itemInfo-wrap .sku-name');
  info.商品名 = nameEl ? nameEl.textContent.trim() : '';
  // 价格
  const priceEl = document.querySelector('.p-price .price, .summary-price .price');
  info.价格 = priceEl ? '¥' + priceEl.textContent.trim() : '';
  // 促销价
  const promoEl = document.querySelector('.J-summary-down .price, .promo-price .price');
  if (promoEl) info.促销价 = '¥' + promoEl.textContent.trim();
  // 评价数
  const commentCount = document.querySelector('#comment-count a, .J-comment-count');
  info.评论数 = commentCount ? commentCount.textContent.trim() : '';
  // 好评率
  const goodRate = document.querySelector('.percent-con, .comment-percent');
  info.好评率 = goodRate ? goodRate.textContent.trim() : '';
  // 店铺
  const shopEl = document.querySelector('.J-hove-wrap .name a, .shop-name a');
  info.店铺 = shopEl ? shopEl.textContent.trim() : '';
  // 是否自营
  info.自营 = !!document.querySelector('.u-jd, .jd-icon, [class*="self-icon"]');
  // 库存状态
  const stockEl = document.querySelector('#store-prompt, .stock-wrap .status');
  info.库存 = stockEl ? stockEl.textContent.trim() : '';
  // 规格/参数（取前 10 条）
  const specs = [];
  document.querySelectorAll('.Ptable-item dl, .p-parameter-list li').forEach((el, i) => {
    if (i < 10) specs.push(el.textContent.trim().replace(/\\s+/g, ' '));
  });
  info.规格参数 = specs;
  return JSON.stringify(info);
})()
""")
```

### 提取商品评价

```
browser_page(action="eval", session=SID, script="""
(function() {
  const reviews = [];
  document.querySelectorAll('.comment-item, .J-comment-item').forEach((el, i) => {
    if (i >= 10) return;
    const content = el.querySelector('.comment-con, .comment-content');
    const star = el.querySelector('.comment-star, .star');
    const time = el.querySelector('.comment-date, .order-info span');
    reviews.push({
      内容: content ? content.textContent.trim().substring(0, 100) : '',
      星级: star ? star.className.match(/\\d/)?.[0] || '' : '',
      时间: time ? time.textContent.trim() : ''
    });
  });
  return JSON.stringify(reviews);
})()
""")
```

注意：评价区域可能需要滚动加载，先 eval 滚动到评价区域：
```
browser_page(action="eval", session=SID, script="document.querySelector('#comment, .tab-con').scrollIntoView()")
```
等待 2 秒后再提取。

---

## 路由逻辑

| 用户意图 | 做什么 |
|---------|--------|
| 查京东订单/导出订单 | 直接导航订单页 → eval 提取 → 保存 CSV |
| 搜索订单（找某个商品的订单） | 用 keyword 参数导航订单搜索 → eval 提取结果 |
| 搜索商品/比价 | 导航搜索页 → eval 提取列表 → 表格呈现 |
| 查商品详情/评价 | 导航 item.jd.com/{sku}.html → eval 提取详情+评价 |
| 查物流/快递 | 订单页找到对应订单 → 点击"查看物流" |
| 查购物车 | 导航 `https://cart.jd.com/cart_index/` → eval 提取 |

---

## 输出格式

默认输出 CSV，表头：

```
订单号,日期,状态,金额,商品名
```

用户要求其他格式（Markdown 表格、JSON）时按需调整。

---

## 关键纪律

```
✅ 正确做法：
1. browser_session 创建/接管 → 直接导航目标 URL
2. browser_page eval 执行 JS 提取数据（一次拿到结构化结果）
3. file_write 增量保存（大批量时逐页追加）
4. 翻页用 eval 点击下一页按钮

❌ 禁止做法：
1. 用 snapshot 读取订单页面（DOM 太大，浪费 token）
2. 通过菜单层层导航到订单页（浪费步骤）
3. 一次性提取所有页面不保存中间结果（超时丢数据）
4. 用 web_fetch 访问京东（需要登录态，拿不到数据）
5. 写 Python/Playwright 脚本操作京东（直接用 browser 工具）
```

---

## 常见问题处理

| 问题 | 解决 |
|------|------|
| 页面要求登录 | 提示用户先在 Chrome 中登录京东，再重试 |
| eval 返回空数组 | 页面结构可能更新，先用 snapshot(selector=".order-tb", depth=2) 看一眼当前结构，调整选择器 |
| 翻页后数据没变 | 加 wait(ms=2000) 等待 AJAX 加载完成 |
| 订单跨度大提取慢 | 分批提取，每 5 页保存一次，告知用户进度 |

---

## 工具速查

- `browser_session`：create / attach_current / release / close
- `browser_tab`：open / list / activate / close
- `browser_page`：navigate / snapshot / click / fill / type / eval / screenshot / wait

activate_tools: browser_session, browser_tab, browser_page, file_write
