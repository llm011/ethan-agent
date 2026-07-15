# 小红书社交互动

在笔记详情页进行点赞、收藏、评论。

## 点赞

在详情页执行：
```javascript
(() => {
  const likeBtn = document.querySelector('.like-wrapper .like-icon, [class*="like"] svg, .engage-bar .like');
  if (likeBtn) {
    likeBtn.closest('button, [role="button"], .like-wrapper')?.click() || likeBtn.click();
    return { action: 'liked' };
  }
  // 备选：找所有按钮中含❤️或"赞"的
  const btns = Array.from(document.querySelectorAll('.engage-bar button, .engage-bar [role="button"]'));
  const likeEl = btns[0]; // 通常第一个是点赞
  if (likeEl) { likeEl.click(); return { action: 'liked', method: 'fallback' }; }
  return { action: 'failed', hint: 'like button not found' };
})()
```

## 收藏

```javascript
(() => {
  const btns = Array.from(document.querySelectorAll('.engage-bar button, .engage-bar [role="button"]'));
  // 收藏通常是第二个按钮
  const favEl = btns[1];
  if (favEl) { favEl.click(); return { action: 'favorited' }; }
  
  const favBtn = document.querySelector('[class*="collect"], [class*="favorite"]');
  if (favBtn) { favBtn.click(); return { action: 'favorited', method: 'class' }; }
  return { action: 'failed' };
})()
```

## 发表评论

**必须先让用户确认评论内容。**

```javascript
(() => {
  // 点击评论输入框激活
  const commentInput = document.querySelector('#comment-textarea, [placeholder*="评论"], [contenteditable][class*="comment"]');
  if (commentInput) {
    commentInput.focus();
    commentInput.click();
    return { step: 'focused' };
  }
  return { step: 'not_found' };
})()
```

等待 1 秒后输入内容：
```javascript
((content) => {
  const input = document.querySelector('#comment-textarea, [placeholder*="评论"], [contenteditable][class*="comment"]');
  if (input) {
    input.focus();
    if (input.contentEditable === 'true') {
      input.textContent = content;
    } else {
      input.value = content;
    }
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return { step: 'typed' };
  }
  return { step: 'failed' };
})('评论内容')
```

等待 500ms 后点击发送：
```javascript
(() => {
  const sendBtn = document.querySelector('button[class*="submit"], .comment-submit, button:has(span)');
  const buttons = Array.from(document.querySelectorAll('button'));
  const send = buttons.find(b => b.textContent.includes('发送') || b.textContent.includes('发布'));
  if (send) { send.click(); return { step: 'sent' }; }
  return { step: 'send_btn_not_found' };
})()
```

## 频率控制

- 每次互动间隔 2-3 秒
- 每天评论不超过 20 条
- 点赞/收藏可稍频繁但也需间隔
- 批量互动每 5 次暂停 10-20 秒
