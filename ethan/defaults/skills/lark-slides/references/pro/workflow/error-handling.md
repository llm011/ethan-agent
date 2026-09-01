# 排障

本文件覆盖 lark-slides 的 **XML 语法 / 接口调用 / 错误码** 排障与失败处理（`invalid param`、创建失败、空白页、3350001 等报错）。其它类别的问题请转对应文档：

- **XML 里的排版/布局/元素问题**（文本溢出、重叠、越界、空白/破损页等）→ [validation-xml.md](validation-xml.md)。
- **视觉问题**（对比度、图片裁切、间距、风格一致性等）→ [validation-visual.md](validation-visual.md)。

## 失败处理顺序

遇到 `invalid param`、某一页创建失败、页面空白或布局错乱时，按顺序排查；其中第 2–4 项也是创建或替换前应先自检的点：

1. **保住现场**：记录 `xml_presentation_id`，不要假设失败就代表什么都没创建；先用 `slides +xml-get --output <CWD 内相对路径>` 回读到本地文件（必须使用 `--output`），确认已有哪些页写入、问题出在哪一页。
2. **未转义字符**（`invalid param` / 3350001 最常见原因）：正文和标题里的 `&`、`<`、`>` 不能裸写（`Q&A -> Q&amp;A`，`<` / `>` 写成 `&lt;` / `&gt;`）；属性值里的裸 `&` 也要写成 `&amp;`（如 URL `a=1&b=2 -> a=1&amp;b=2`）。
3. **结构与引号**：标签闭合、属性引号安全（XML 属性、shell 引号、JSON 包装之间不互相打断）；`<slide>` 下只放 `<style>`、`<data>`、`<note>`，文本都在 `<content>` 内。
4. **图片路径**：`<img src="@...">` 占位符由 `+create` 和 `+add-slide` 处理，会自动上传并替换成 `file_token`。
5. **疑似 shell 截断**：用 `--slides '[...]'` 且内容缺失或异常时，切换两步创建——先 `slides +create`，再用 `slides +add-slide --slide @<文件>` 逐页添加。
6. **修复并复验**：局部问题用 `+replace-slide` 块级修正；整页结构要重做时用 `+delete-slide` 删旧页 + `+add-slide` 建新页。修复后重新回读或截图确认。

## 常见错误码

| 错误码 / 信号 | 含义 | 解决方案 |
|--------------|------|----------|
| 400 XML 格式错误 | XML 语法错误 | 检查标签闭合、属性引号、特殊字符转义 |
| 400 请求包装错误 | `--data` 未按 schema 包装 | 检查是否传入 `xml_presentation.content` 或 `slide.content` |
| 创建成功但页面空白 / 内容缺失 / 布局错乱 | 常见于 `--slides '[...]'` 的 shell 转义或长参数传递问题 | 改用两步创建，并在创建后立即读取 XML 验证 |
| 403 权限不足 | scope 或文档权限不匹配 | 确认 scope 和文档权限；无权限时根据错误响应引导用户解决 |
| 404 演示文稿不存在 | `xml_presentation_id` 不正确或无权限 | 检查 token；wiki URL 需先解析真实 `obj_token` |
| 404 幻灯片不存在 | `slide_id` 不正确 | 重新读取 presentation 或 slide，确认最新 ID |
| 400 无法删除唯一幻灯片 | 演示文稿至少保留一页 | 先创建新页，再删除旧页 |
| 1061002 媒体上传 params error | slides 媒体上传参数不符合约定 | 用 `slides +media-upload`，不要手拼原生 `medias/upload_all`；slides 唯一可用 `parent_type` 是 `slide_file` |
| 1061004 forbidden | 当前用户对演示文稿无编辑权限 | 确认当前用户对目标幻灯片有编辑权限 |
| 3350001 | XML 非 well-formed、XML 结构不符合服务端要求，或 replace 片段问题 | 优先检查未转义字符；replace 场景再看 `block_id` 和 `<content/>`；改写回读来的页时检查有没有 `<undefined>`，它只能导出不能写入 |
| 3350002 | `revision_id` 大于当前版本 | 用 `-1` 取当前版本；要取真实版本号从 CLI 响应里读（`+xml-get --json` 的返回，或单页读的 `data.revision_id`），回读落盘的 XML 文件里没有这个值 |
| validation: unsafe file path | `--file` 给了绝对路径或上层路径 | `--file` 必须是 CWD 内相对路径；先 `cd` 到素材目录再执行 |

## 命令专属参考

- 图片上传、`@path` 占位符、`file_token`：见 [lark-slides-media-upload.md](../cli/lark-slides-media-upload.md) 和 [lark-slides-create.md](../cli/lark-slides-create.md)。
- 块级替换、`block_id`、3350001 replace 细节：见 [lark-slides-replace-slide.md](../cli/lark-slides-replace-slide.md)。
- 追加/插入单页、`--before-slide-id` 和 `--slide @file`：见 [lark-slides-add-slide.md](../cli/lark-slides-add-slide.md)。
- 删除单页：见 [lark-slides-delete-slide.md](../cli/lark-slides-delete-slide.md)。

## 离线 HTML 渲染（从飞书 Slide 提取内容做本地展示）

当用户要「把飞书 Slide 的内容拿出来看 / 转成离线可浏览的 HTML / 不依赖登录态和 iframe」时，走服务端截图权限（`slides:presentation:screenshot`）通常拿不到（会提示未授权），更实用的是**把 XML 渲染成 HTML**。踩过的坑记在这里：

### 只读、不返回给用户的关键坐标
- **表格坐标**：`<table>` 自身的 `topLeftX/topLeftY/width/height` 必须读取并用于绝对定位。**漏读会让所有表格塌缩到 (0,0)，直接压住顶部标题，视觉上「标题盖住表格第一行」**。这是最常见也最隐蔽的坑。
- **表格列宽**：`<colgroup>` 里的 `<col width>` 是每列宽度，按占比分配列宽，否则列宽不均。
- **文字不要溢出**：`<div class="shape">` 绝对定位后，如果文字超出给定 `height` 会用默认行为向下溢出，压住相邻元素。给 `.shape` 加 `overflow:hidden`（或 `-webkit-line-clamp`），或按内容估算高度，避免「文字盖住下面元素」。

### 渲染正确性
- **验证要落到浏览器**：光改脚本坐标不代表渲染正确，必须 `python3 -m http.server` 起本地服务 + `browser_session/browser_page` 打开验证，`scroll_to_text` 定位到出问题那页再截图（`screenshot`）核对，确认元素真分开了才算修复。**不要凭脚本输出就宣布完成**。
- **图标是 emoji 占位**：飞书 Slide 的图标是 IconPark 资源，离线 HTML 拿不到真实图形，只能按 `iconType` 映射成 emoji（如 `brain->🧠`）。如果用户要原版图形，得从 IconPark 拉 svg 替换；不拉就说明这是占位。
- **标题字号异常偏大**：如果标题写得比正文夸张很多，检查是否单位或字号没换算（飞书 XML 里字号可能是 pt，渲染成 px 时要换算）。

### 权限与资源边界
- `slides:presentation:screenshot` scope 大概率未授权，skill 建议不申请。要像素级还原就得让用户补授权；**没有权限时用 HTML 渲染是唯一确定可行的路径**。
- 从飞书 Slide 拉内容用 lark-cli 的 user 凭证（`identity: user`）时，读授权范围内的 Presentation 通常 OK。

### 画廊式布局（可点击缩略图 + 大图预览 + 演讲者备注）

渲染脚本 `scripts/ppt_to_html.py` 已支持**画廊式布局**，用于生成方便预览的离线 HTML。布局分三区：

- **左侧缩略图导航**：12 页小图，可点击切换（`.thumb-wrap.active` 高亮当前页）。缩略图**不是截图/图片**，而是同一份 slide DOM 用 `transform: scale(0.20833)` 缩放到 200×112，保证文字可选中、离线可用。
- **右侧大图预览**：`960×540` 的完整 slide DOM，切换时 `preview.innerHTML = slides[idx-1]` 替换。
- **下方演讲者备注**：读 `<slide><note><content><p>...` 渲染成可读文本，切换页时同步更新。

**实现要点（踩坑沉淀）：**

1. **note 的 tag 是 `<note>` 不是 `<notes>`**：`slide.find(q('notes'))` 会找不到，必须用 `slide.find(q('note'))` 才读得到备注。

2. **JS 数组注入**：脚本把全部 `slides_html` 和 `escaped_notes` 用 `json.dumps(ensure_ascii=False)` 序列化后，作为 `const slides = [...]; const notes = [...];` 注入 `<script>`。**不要用字符串 replace 填占位符**——f-string 里就能直接注入，replace 容易漏掉 `{slides_js}` 导致 `NameError`。

3. **缩略图用 CSS scale 而非 img**：不依赖截图、无图片文件、文字可选中复制。`scale(0.20833)` 对应 200px 宽 / 960px 原宽。

4. **`overflow:hidden` 必须加在 `.slide` 上**：否则绝对定位元素会撑破 540px 高度，缩略图/预览区出现溢出滚动。

**入口命令**（脚本已支持 CLI 参数）：

```bash
python3 ppt_to_html.py <xml_path> <out_path>
```

**验证流程**：起本地 `http.server`（注意 pyenv 的 python3 可能起不来，用 `/usr/bin/python3`），`browser_session` 打开后 `snapshot` 确认缩略图/预览/备注三区都在，重点核对表格不再压标题、多行代码块逐行换行。
