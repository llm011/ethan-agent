# 字体配对指南（Step 2 定 design system 时必读）

> 渲染器只把字体名写进 pptx，**字体解析发生在打开文件的机器上**——渲染机不需要装字体。
> 选字体的第一性问题永远是：**观众用什么机器打开？** 先定平台，再定气质。

## 机制：中西文分离

主题里两个字段分开设：

- `fontName`：中文（ea/cs）字体
- `latinFontName`：西文（latin）字体，省略时与 fontName 相同

典型效果：中文正文用黑体保证屏显清晰，西文/数字用另一款字体撑气质（如「中文 MiSans + 西文 Georgia」）。
run 级显式 `fontName` 会同时覆盖中西文——想混排就在主题层设，不要在 run 里逐条写。

## 按查看平台选

| 查看端 | 中文安全字体 | 西文安全字体 | 说明 |
|---|---|---|---|
| Windows（Office/WPS） | Microsoft YaHei（微软雅黑） | Arial / Georgia / Verdana | 雅黑是 Windows 中文事实标准 |
| macOS（Keynote/Office） | PingFang SC（苹方） | Helvetica / Georgia | 苹果系打开最稳 |
| Linux（WPS/LibreOffice） | Noto Sans CJK SC / WenQuanYi Micro Hei | DejaVu Sans / Liberation Sans | 雅黑/苹方都没有，必被替换 |
| 不确定 / 跨平台分发 | Microsoft YaHei | Arial | 最大公约数；或让用户自报平台 |

拿不准就先问一句「这个 PPT 主要在什么设备上放映/查看」，比猜错了返工便宜。

## 按 deck 气质配对

同一平台内，按内容气质选配对（中文 + 西文）：

| 气质 | 中文 | 西文 | 适用 |
|---|---|---|---|
| 商务汇报（默认） | Microsoft YaHei | Arial / Verdana | 年报、总结、通用汇报 |
| 学术/课件 | Microsoft YaHei（正文）+ 标题可用思源宋体/SimSun 类 | Georgia / Times New Roman | 课件、论文答辩——衬线西文带书卷气 |
| 科技/发布会 | PingFang SC / Microsoft YaHei | Helvetica / Futura 类 | AI 分享、产品发布，配深色主题 |
| 营销/路演 | Microsoft YaHei（粗字重撑标题） | Arial Black / Verdana | 活动、融资路演 |

- 西文衬线（Georgia/Times）适合学术与「地图/图鉴」式设计语言；西文无衬线（Arial/Helvetica）适合商务与科技。
- 标题与正文可用不同字重（bold）区分，**不要**在一个 deck 里混用两款以上中文字体。

## 字号阶梯（写进 theme.typography 的参考值）

| textType | fontSize(px) | 说明 |
|---|---|---|
| title | 24-28 bold | action title，允许 2 行 |
| subtitle | 15-16 | 封面副标题/过渡页 |
| itemTitle | 15-16 bold | 卡片/条目小标题 |
| content / item | 13-14 | 正文与 bullet |
| notes / footer / header | 9-10 | 来源行、页码、页眉 |
| partNumber | 56-64 bold | 过渡页大编号 |
| itemNumber | 15-16 bold | 条目编号 |

封面主标题单独在 run 级给 40-48。latex 公式元素默认 20px，公式页给 24-32。

## 常见坑

- **Linux/WPS 打开字体被替换、版式跑偏**：雅黑/Verdana 在 Linux 不存在，替换成默认字体后字宽变化导致溢出。预先知道查看端是 Linux 就用上表 Linux 行重新渲染。
- **中文变方框/宋体**：查看机没装指定字体。换安全字体重新渲染即可（改 theme 一处，不必动页面）。
- **想用的字体不在安全列表**（如 MiSans、思源黑体）：可以写进主题，但要确认查看机装了这个字体，否则按「中文变方框」处理。
