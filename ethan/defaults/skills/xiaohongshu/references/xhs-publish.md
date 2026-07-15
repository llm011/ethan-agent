# 小红书内容发布

通过浏览器工具在小红书发布内容。

## 发布入口

```
https://creator.xiaohongshu.com/publish/publish
```

## 图文发布流程

### 第一步：打开发布页
```
browser_tab action=open → https://creator.xiaohongshu.com/publish/publish
browser_page action=wait, ms=3000
```

### 第二步：上传图片
用 eval JS 触发文件上传（需要用户本地图片路径）：
```javascript
(() => {
  const input = document.querySelector('input[type="file"][accept*="image"]');
  if (input) {
    input.style.display = 'block';
    return { found: true, accept: input.accept };
  }
  return { found: false };
})()
```
> 注意：浏览器安全限制可能阻止直接设置文件。如果无法自动上传，提示用户手动拖入图片，然后继续后续步骤。

### 第三步：填写标题
```javascript
(() => {
  const titleInput = document.querySelector('#composerTitleInput, [placeholder*="标题"], input[class*="title"]');
  if (titleInput) {
    titleInput.focus();
    titleInput.value = '';
    document.execCommand('insertText', false, '标题内容');
    titleInput.dispatchEvent(new Event('input', { bubbles: true }));
    return { success: true };
  }
  return { success: false, hint: 'title input not found' };
})()
```

**标题限制**：≤20 字符（UTF-16 计算：汉字=1，两个 ASCII=1）

### 第四步：填写正文
```javascript
(() => {
  const editor = document.querySelector('#post-textarea, [contenteditable="true"][class*="content"], .ql-editor');
  if (editor) {
    editor.focus();
    editor.innerHTML = '';
    document.execCommand('insertText', false, '正文内容');
    editor.dispatchEvent(new Event('input', { bubbles: true }));
    return { success: true };
  }
  return { success: false };
})()
```

### 第五步：添加话题标签
```javascript
(() => {
  const tagInput = document.querySelector('[placeholder*="话题"], [placeholder*="标签"], input[class*="tag"]');
  if (tagInput) {
    tagInput.focus();
    document.execCommand('insertText', false, '#标签名');
    return { success: true };
  }
  return { success: false };
})()
```

### 第六步：确认发布
**必须先让用户确认内容**，确认后：
```javascript
(() => {
  const btn = document.querySelector('button[class*="publish"], .publishBtn, button:has(span:contains("发布"))');
  if (!btn) {
    const buttons = Array.from(document.querySelectorAll('button'));
    const publishBtn = buttons.find(b => b.textContent.includes('发布'));
    if (publishBtn) { publishBtn.click(); return { clicked: true }; }
    return { clicked: false };
  }
  btn.click();
  return { clicked: true };
})()
```

## 关键约束

- **发布前必须让用户确认最终标题、正文和图片**
- 标题超长时智能缩短而非机械截断
- 正文段落用双换行分隔，话题标签放最后一行
- 图片至少 1 张，发布才能成功
