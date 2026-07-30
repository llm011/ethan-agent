# 小红书内容发现

详细的搜索和浏览操作指令。

## 核心路径（务必先读）

搜索卡片里藏着**带 `xsec_token` 的详情链接**，拿到它就能**直接打开详情页**——不需要点击卡片。

- 每张卡片 `<section class="note-item" data-note-id="...">` 里有两个 `<a>`：
  - `href="/explore/{id}"` 且 `style="display:none"` —— **不可点、不可用**（模型最容易踩的坑）
  - `class="cover ..."` `href="/search_result/{id}?xsec_token=...&xsec_source="` —— **这个带 token，是能用的**
- 把 `.cover` 那个 href 补成绝对地址后 `browser_tab` action=open **可以直接打开详情页**（实测 `is404:false`，正文/标题都能读到）。小红书归一化后 URL 会变成 `/explore/{id}?xsec_token=...`，属正常。
- **只要带上卡片里那个 `xsec_token`，直接 open 就行**；缺 token 才会 404。所以不要凭 note-id 自己拼无 token 的 URL。

> 旧做法「必须点击卡片进入」已废弃——卡片可见链接 display:none、靠自定义 handler，点击极不稳，会反复失败打转。**改用下面的「提取带 token 链接 → 直接 open」。**

## 搜索笔记

**URL 格式（搜索页可直接 URL 打开）：**
```
https://www.xiaohongshu.com/search_result?keyword={encodeURIComponent(关键词)}&source=web_search_source_normal
```

**排序参数**：追加 `&sort=time_descending` 取「最新」；综合排序不加。其余排序（点赞/评论/收藏）用页面筛选按钮。

**提取搜索结果 JS（含带 token 的详情链接，一次拿全）：**
```javascript
(() => {
  const cards = document.querySelectorAll('section.note-item');
  const origin = location.origin;
  return Array.from(cards).slice(0, 10).map((card, i) => {
    const noteId = card.getAttribute('data-note-id') || '';
    // 只取带 xsec_token 的 .cover 链接，忽略 display:none 的 /explore 裸链
    const cover = card.querySelector('a.cover[href*="xsec_token"]')
                  || card.querySelector('a[href*="xsec_token"]');
    let detailUrl = cover ? cover.getAttribute('href') : '';
    if (detailUrl && detailUrl.startsWith('/')) detailUrl = origin + detailUrl;
    const title = card.querySelector('.title')?.innerText?.trim() || '';
    const author = card.querySelector('.author .name, .author-wrapper .name')?.innerText?.trim() || '';
    const likes = card.querySelector('.like-wrapper .count, .count')?.innerText?.trim() || '0';
    return { index: i + 1, noteId, title, author, likes, detailUrl };
  }).filter(x => x.detailUrl);  // 没抓到带 token 链接的丢弃
})()
```

返回的 `detailUrl` 就是可直接打开的详情地址。

## 查看笔记详情（直接打开，不点击）

1. 从上一步结果里取目标笔记的 `detailUrl`
2. `browser_tab` action=open → `detailUrl`
3. `browser_page` action=wait, ms=3000
4. `browser_page` action=eval → 提取正文（下方 JS）
5. 看下一篇：`browser_tab` action=close 关掉这个详情 tab（或直接 open 下一个 detailUrl 覆盖），**不要 history.back 回搜索页再点**

> **失败兜底**：某篇打不开、或某字段抓不到，就把该字段/该篇标注 `N/A` 跳过，**不要在同一篇上反复换脚本重试**。宁可少一篇也不打转。

### 提取详情正文和图片

```javascript
(() => {
  const titleEl = document.querySelector('#detail-title') ||
                  document.querySelector('.title') ||
                  document.querySelector('[class*="title"]');
  const title = titleEl ? titleEl.innerText.trim() : '';

  const descEl = document.querySelector('#detail-desc') ||
                 document.querySelector('.note-text') ||
                 document.querySelector('[class*="desc"]');
  const desc = descEl ? descEl.innerText.trim() : '';

  const imgs = Array.from(document.querySelectorAll('.swiper-slide img, .carousel img, [class*="slide"] img'))
    .map(img => img.src || img.dataset?.src || '')
    .filter(src => src && !src.includes('avatar') && !src.includes('emoji'));

  const tags = Array.from(document.querySelectorAll('#hash-tag a, .tag a, [class*="tag"] a'))
    .map(a => a.innerText.trim())
    .filter(t => t.startsWith('#'));

  const author = document.querySelector('.author-container .username, [class*="author"] .name')?.innerText?.trim() || '';
  const publishTime = document.querySelector('.date, [class*="time"], [class*="date"]')?.innerText?.trim() || '';
  const likes = document.querySelector('.like-wrapper .count, [class*="like"] .count')?.innerText?.trim() || '';
  const collects = document.querySelector('.collect-wrapper .count, [class*="collect"] .count')?.innerText?.trim() || '';
  const comments = document.querySelector('.comment-wrapper .count, [class*="chat"] .count')?.innerText?.trim() || '';

  return { title, desc, images: imgs.slice(0, 9), tags, author, publishTime, likes, collects, comments };
})()
```

### 提取评论

```javascript
(() => {
  const comments = Array.from(document.querySelectorAll('.comment-item, [class*="comment-item"]'));
  return comments.slice(0, 5).map((el, i) => {
    const user = el.querySelector('.name, [class*="author"]')?.innerText?.trim() || '';
    const content = el.querySelector('.content, [class*="content"]')?.innerText?.trim() || '';
    const likes = el.querySelector('.like-count, [class*="like"]')?.innerText?.trim() || '0';
    return { index: i + 1, user, content, likes };
  });
})()
```

## 批量查看多篇详情的流程

1. 搜索 → eval 提取卡片列表（含 `detailUrl`）
2. 按需求排序/取前 N 篇
3. 循环每篇：`browser_tab` open `detailUrl` → wait 3s → eval 提取正文 → 关 tab
4. 每查看 3-4 篇后插入 10-20 秒长等待，避免风控
5. 某篇失败标 `N/A` 跳过，不反复重试
6. 出现 404 或验证码时停止，截图告知用户

## 筛选搜索（可选）

需要「最多点赞/评论/收藏」排序时，打开搜索页后 eval 点击筛选按钮：
```javascript
(() => {
  const sortBtn = document.querySelector('[class*="sort"] .filter-item, .search-filter .sort');
  if (sortBtn) sortBtn.click();
  return 'clicked sort';
})()
```
等待 1 秒后点击具体选项，再重新提取卡片列表。

## 首页推荐 Feed

```
https://www.xiaohongshu.com/explore
```
提取推荐内容的 JS 与搜索结果提取类似（同样从卡片取 `data-note-id` + 带 token 的 `.cover` 链接）。

## 用户主页

```
https://www.xiaohongshu.com/user/profile/{user_id}
```
提取用户信息和笔记列表；主页笔记卡片同样是「取带 token 链接直接打开」。

## 防风控策略

- 连续访问 3-4 篇详情后插入 10-20 秒等待
- 出现验证码用 `browser_page` action=screenshot 截图给用户
- 优先 `action=eval` 提取数据；`action=snapshot` 仅在需要看整页结构时用（DOM 大、ref 易 detach）
- 创建会话用 `browser_session` action=attach_current（复用已有 Chrome）
