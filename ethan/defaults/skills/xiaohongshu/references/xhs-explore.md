# 小红书内容发现

详细的搜索和浏览操作指令。

## 搜索笔记

**URL 格式（搜索页可直接 URL 打开）：**
```
https://www.xiaohongshu.com/search_result?keyword={encodeURIComponent(关键词)}&source=web_search_source_normal
```

**提取搜索结果 JS：**
```javascript
(() => {
  const cards = document.querySelectorAll('.note-item');
  return Array.from(cards).slice(0, 10).map((card, i) => {
    const title = card.querySelector('.title')?.innerText || card.querySelector('a')?.innerText || '';
    const link = card.querySelector('a')?.href || '';
    const author = card.querySelector('.author-wrapper .name')?.innerText || '';
    const likes = card.querySelector('.like-wrapper .count')?.innerText || '0';
    return { index: i + 1, title: title.trim(), link, author, likes };
  });
})()
```

**筛选搜索（通过 URL 参数或页面操作）：**
- 排序：综合、最新、最多点赞、最多评论、最多收藏
- 类型：不限、视频、图文
- 时间：不限、一天内、一周内、半年内

若需筛选，打开搜索页后用 eval JS 点击对应筛选按钮：
```javascript
(() => {
  // 点击排序下拉
  const sortBtn = document.querySelector('[class*="sort"] .filter-item, .search-filter .sort');
  if (sortBtn) sortBtn.click();
  return 'clicked sort';
})()
```
等待 1 秒后点击具体选项。

## 查看笔记详情

⚠️ **重要：不能直接用 browser_tab open 打开帖子 URL！**
小红书对帖子详情页有 `xsec_token` 反爬保护，直接打开 URL 会被 redirect 到 404 页面。
必须在搜索结果页通过 JS 点击卡片进入。

### 点击进入详情（按索引）

```javascript
(() => {
  const cards = document.querySelectorAll('.note-item');
  const targetIndex = 0; // 第 N 个，从 0 开始
  const card = cards[targetIndex];
  if (!card) return { error: 'card not found', total: cards.length };
  const link = card.querySelector('a');
  const title = card.querySelector('.title')?.innerText || link?.innerText || '';
  if (link) link.click();
  return { status: 'clicked', index: targetIndex, title: title.trim() };
})()
```

### 点击进入详情（按标题匹配）

```javascript
(() => {
  const keyword = '目标标题关键词';
  const cards = document.querySelectorAll('.note-item');
  for (const card of cards) {
    const title = card.querySelector('.title')?.innerText || card.querySelector('a')?.innerText || '';
    if (title.includes(keyword)) {
      const link = card.querySelector('a');
      if (link) link.click();
      return { status: 'clicked', title: title.trim() };
    }
  }
  return { error: 'not found', keyword, total: cards.length };
})()
```

点击后 wait 3000ms，然后提取内容。

### 提取详情正文和图片

```javascript
(() => {
  const titleEl = document.querySelector('.title') || document.querySelector('[class*="title"]');
  const title = titleEl ? titleEl.innerText.trim() : '';

  const descEl = document.querySelector('#detail-desc') ||
                 document.querySelector('.note-text') ||
                 document.querySelector('[class*="desc"]');
  const desc = descEl ? descEl.innerText : '';
  
  const imgs = Array.from(document.querySelectorAll('.swiper-slide img, .carousel img, [class*="slide"] img'))
    .map(img => img.src || img.dataset?.src || '')
    .filter(src => src && !src.includes('avatar') && !src.includes('emoji'));
  
  const tags = Array.from(document.querySelectorAll('#hash-tag a, .tag a, [class*="tag"] a'))
    .map(a => a.innerText.trim())
    .filter(t => t.startsWith('#'));
  
  const author = document.querySelector('.author-container .username, [class*="author"] .name')?.innerText || '';
  const publishTime = document.querySelector('.date, [class*="time"], [class*="date"]')?.innerText || '';
  
  return { title, desc, images: imgs.slice(0, 9), tags, author, publishTime };
})()
```

### 提取第一条评论

```javascript
(() => {
  const comments = Array.from(document.querySelectorAll('.comment-item, [class*="comment-item"]'));
  return comments.slice(0, 5).map((el, i) => {
    const user = el.querySelector('.name, [class*="author"]')?.innerText || '';
    const content = el.querySelector('.content, [class*="content"]')?.innerText || '';
    const likes = el.querySelector('.like-count, [class*="like"]')?.innerText || '0';
    return { index: i + 1, user, content, likes };
  });
})()
```

### 返回搜索页

查看完一篇后，用 `history.back()` 返回搜索页，再点击下一篇：
```javascript
(() => { window.history.back(); return 'back'; })()
```
返回后 wait 2000ms 再进行下一步操作。

## 批量查看多篇详情的流程

1. 搜索 → 提取卡片列表
2. 循环：点击第 N 个卡片 → wait 3s → 提取内容 → back → wait 2s
3. 每查看 3-4 篇后插入 10-20 秒长等待
4. 出现 404 或验证码时停止，截图告知用户

## 获取更多评论

在详情页执行展开：
```javascript
(() => {
  const moreBtn = document.querySelector('[class*="show-more"], .show-more-comment');
  if (moreBtn) moreBtn.click();
  return 'expanded';
})()
```
等待 2 秒后再提取评论列表。

## 首页推荐 Feed

```
https://www.xiaohongshu.com/explore
```
提取推荐内容的 JS 类似搜索结果提取。

## 用户主页

```
https://www.xiaohongshu.com/user/profile/{user_id}
```
提取用户信息和笔记列表。

## 防风控策略

- 连续访问 3-4 篇详情后插入 10-20 秒等待
- 出现验证码用 `browser_page` action=screenshot 截图给用户
- 不要用 `action=snapshot`，只用 `action=eval`
- 创建会话用 `browser_session` action=attach_current（复用已有 Chrome）
