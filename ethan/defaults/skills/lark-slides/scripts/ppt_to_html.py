#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将飞书 Slide XML 渲染为可离线浏览的 HTML 幻灯片（画廊式布局）

布局：
- 左侧：12 页缩略图导航（可点击切换）
- 右侧：当前页大图预览（真实 DOM 渲染，非截图，文字可选中）
- 下方：当前页演讲者备注

用法：
  python3 ppt_to_html.py <xml_path> <out_path>

注意：
  - 元素坐标必须读 topLeftX/topLeftY/width/height，否则塌缩到 (0,0) 压住标题
  - 预览缩略图用 CSS transform: scale() 对同一 DOM 缩放，保证文字可选中且离线
"""
import re
import html
import sys
import xml.etree.ElementTree as ET

NS = "https://www.larkoffice.com/sml/2.0"

def q(tag):
    return f"{{{NS}}}{tag}"

def rgba_to_css(rgba_str, default="#fff"):
    if not rgba_str:
        return default
    m = re.match(r'rgba?\(([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,/\s]+([\d.]+))?\)', rgba_str)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = m.group(4)
        if a is None:
            return f"rgb({r},{g},{b})"
        a = float(a)
        return f"rgba({r},{g},{b},{a})"
    return rgba_str

def parse_fill(style_elem):
    fill = style_elem.find(q('fill')) if style_elem is not None else None
    if fill is None:
        return None
    fc = fill.find(q('fillColor'))
    if fc is not None:
        return rgba_to_css(fc.get('color'))
    return None

def render_inline(elem):
    out = []
    if elem.text:
        out.append(html.escape(elem.text))
    for c in elem:
        if c.tag == q('strong'):
            out.append(f"<strong>{render_inline(c)}</strong>")
        elif c.tag == q('span'):
            color = c.get('color')
            inner = render_inline(c)
            if color:
                out.append(f'<span style="color:{rgba_to_css(color)}">{inner}</span>')
            else:
                out.append(inner)
        elif c.tag == q('br'):
            out.append("<br>")
        elif c.text:
            out.append(html.escape(c.text))
        if c.tail:
            out.append(html.escape(c.tail))
    return "".join(out)

def parse_content(shape):
    content = shape.find(q('content'))
    if content is None:
        return "", {}
    attrs = {
        'fontSize': content.get('fontSize'),
        'fontFamily': content.get('fontFamily'),
        'color': content.get('color'),
        'bold': content.get('bold'),
        'textAlign': content.get('textAlign'),
        'textType': content.get('textType'),
    }
    parts = []
    for child in content:
        tag = child.tag
        if tag == q('p'):
            parts.append(render_inline(child) + "<br>")
        elif tag == q('br'):
            parts.append("<br>")
        elif tag == q('ul'):
            items = []
            for li in child:
                if li.tag == q('li'):
                    inner = []
                    for c2 in li:
                        if c2.tag == q('p'):
                            inner.append(render_inline(c2))
                        else:
                            inner.append(render_inline(c2))
                    items.append("<li>" + "".join(inner) + "</li>")
            parts.append("<ul>" + "".join(items) + "</ul>")
    return "".join(parts), attrs

def icon_emoji(icon_type):
    if not icon_type:
        return "⬜"
    t = icon_type.lower()
    mapping = {
        'brain': '🧠', 'aiming': '🎯', 'setting': '⚙️', 'data-all': '📊',
        'protect': '🛡️', 'monitor': '🖥️', 'cycle': '🔄', 'chart': '📈',
        'search': '🔍', 'book': '📖', 'link': '🔗', 'shield': '🛡️',
        'code': '💻', 'cpu': '🧩', 'robot': '🤖', 'tool': '🔧',
        'doc': '📄', 'file': '📁', 'time': '⏱️', 'warning': '⚠️',
        'check': '✅', 'x': '❌', 'plus': '➕', 'arrow': '➡️',
        'user': '👤', 'team': '👥', 'star': '⭐', 'flag': '🚩',
        'lock': '🔒', 'key': '🔑', 'refresh': '🔄', 'play': '▶️',
    }
    for k, v in mapping.items():
        if k in t:
            return v
    return "🔹"

def render_table(table):
    tx = float(table.get('topLeftX', 0))
    ty = float(table.get('topLeftY', 0))
    tw = float(table.get('width', 840))
    th = float(table.get('height', 320))
    colgroup = table.find(q('colgroup'))
    col_widths = []
    if colgroup is not None:
        for col in colgroup:
            col_widths.append(float(col.get('width', 100)))
    total_cw = sum(col_widths) if col_widths else 0
    html_rows = []
    for tr in table:
        if tr.tag != q('tr'):
            continue
        cells = []
        for td in tr:
            if td.tag != q('td'):
                continue
            fill = td.find(q('fill'))
            bg = None
            if fill is not None:
                fc = fill.find(q('fillColor'))
                if fc is not None:
                    bg = rgba_to_css(fc.get('color'))
            content, attrs = parse_content(td)
            style = f"background:{bg};" if bg else ""
            color = attrs.get('color')
            if color:
                style += f"color:{rgba_to_css(color)};"
            bold = attrs.get('bold')
            if bold and bold != 'false':
                style += "font-weight:bold;"
            fs = attrs.get('fontSize')
            if fs:
                style += f"font-size:{fs}px;"
            cells.append(f"<td style='{style}'>{content}</td>")
        html_rows.append("<tr>" + "".join(cells) + "</tr>")
    table_style = f"position:absolute;left:{tx}px;top:{ty}px;width:{tw}px;height:{th}px;"
    return f"<table style='{table_style}'>" + "".join(html_rows) + "</table>"

def render_icon(elem):
    x = float(elem.get('topLeftX', 0)); y = float(elem.get('topLeftY', 0))
    w = float(elem.get('width', 40)); h = float(elem.get('height', 40))
    fill = elem.find(q('fill'))
    fg = "rgba(37,99,235,1)"
    if fill is not None:
        fc = fill.find(q('fillColor'))
        if fc is not None:
            fg = fc.get('color')
    emo = icon_emoji(elem.get('iconType'))
    return (f"<div class='icon' style='left:{x}px;top:{y}px;width:{w}px;height:{h}px;"
            f"background:{rgba_to_css(fg)};'>"
            f"<span style='color:rgba(255,255,255,.92);font-size:{int(h)*0.6}px;'>{emo}</span></div>")

def render_line(elem):
    x1 = float(elem.get('startX', 0)); y1 = float(elem.get('startY', 0))
    x2 = float(elem.get('endX', 0)); y2 = float(elem.get('endY', 0))
    border = elem.find(q('border'))
    color = "rgba(83,97,116,.3)"
    if border is not None:
        bc = border.get('color')
        if bc:
            color = rgba_to_css(bc)
    has_arrow = elem.find(q('endArrow')) is not None
    marker = ""
    if has_arrow:
        marker = ' marker-end="url(#arrowhead)"'
    return (f"<svg class='line' style='position:absolute;left:0;top:0;width:960px;height:540px;pointer-events:none;' "
            f"width='960' height='540'>"
            f"<defs><marker id='arrowhead' markerWidth='10' markerHeight='7' "
            f"refX='9' refY='3.5' orient='auto'>"
            f"<polygon points='0 0, 10 3.5, 0 7' fill='{color}'/></marker></defs>"
            f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' "
            f"stroke='{color}' stroke-width='2'{marker}/></svg>")

def render_shape(shape):
    etype = shape.get('type', 'text')
    x = float(shape.get('topLeftX', 0))
    y = float(shape.get('topLeftY', 0))
    w = float(shape.get('width', 0))
    h = float(shape.get('height', 0))
    fill_el = shape.find(q('fill'))
    bg = None
    if fill_el is not None:
        fc = fill_el.find(q('fillColor'))
        if fc is not None:
            bg = rgba_to_css(fc.get('color'))
    content, attrs = parse_content(shape)
    if etype == 'ellipse':
        style = f"left:{x}px;top:{y}px;width:{w}px;height:{h}px;border-radius:50%;"
        if bg:
            style += f"background:{bg};"
        return f"<div class='shape ellipse' style='{style}'></div>"
    if etype == 'rect':
        border_el = shape.find(q('border'))
        border_color = ""
        if border_el is not None:
            bc = border_el.get('color')
            if bc:
                border_color = rgba_to_css(bc)
        style = f"left:{x}px;top:{y}px;width:{w}px;height:{h}px;"
        if bg:
            style += f"background:{bg};"
        if border_color:
            style += f"border:1px solid {border_color};"
        style += "border-radius:8px;"
        return f"<div class='shape rect' style='{style}'></div>"
    if not content:
        return ""
    fs = attrs.get('fontSize')
    style = f"left:{x}px;top:{y}px;width:{w}px;height:{h}px;"
    if fs:
        style += f"font-size:{fs}px;"
    color = attrs.get('color')
    if color:
        style += f"color:{rgba_to_css(color)};"
    if attrs.get('bold') and attrs['bold'] != 'false':
        style += "font-weight:bold;"
    ta = attrs.get('textAlign')
    if ta:
        style += f"text-align:{ta};"
    style += "line-height:1.4;"
    return f"<div class='shape' style='{style}'>{content}</div>"

def parse_note(slide):
    """读取 slide 下的 <note><content><p>..."""
    note = slide.find(q('note'))
    if note is None:
        return ""
    content = note.find(q('content'))
    if content is None:
        return ""
    ps = []
    for p in content:
        if p.tag == q('p'):
            txt = "".join(render_inline(p) for _ in [p]) if False else "".join(render_inline(p) for c in [] )
            # 直接用 render_inline 读出纯文本
            txt = render_inline(p)
            # 去掉标签只留文本
            txt = re.sub(r'<[^>]+>', '', txt)
            txt = html.unescape(txt)
            ps.append(txt)
    return "\n".join(ps)

def render_slide(slide, idx, total):
    style_el = slide.find(q('style'))
    bg = parse_fill(style_el) if style_el is not None else "#ffffff"
    parts = []
    for child in slide:
        tag = child.tag
        if tag == q('style') or tag == q('note'):
            continue
        elif tag == q('data'):
            for elem in child:
                et = elem.tag
                if et == q('shape'):
                    parts.append(render_shape(elem))
                elif et == q('table'):
                    parts.append(render_table(elem))
                elif et == q('icon'):
                    parts.append(render_icon(elem))
                elif et == q('line'):
                    parts.append(render_line(elem))
    parts.append(f"<div class='pagenum'>{idx}/{total}</div>")
    return f"<div class='slide' style='background:{bg};'>{''.join(parts)}</div>"

def main():
    xml_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/ppt_content.xml'
    out_path = sys.argv[2] if len(sys.argv) > 2 else '/Users/jsongo/.ethan/out/lark-ppt/Agent_Harness.html'
    content = open(xml_path, encoding='utf-8').read()
    m = re.search(r'(<presentation.*?</presentation>)', content, re.S)
    xml_content = m.group(1)
    root = ET.fromstring(xml_content)
    slides = root.findall(q('slide'))
    title = root.find(q('title'))
    title = title.text if title is not None else "PPT"

    slides_html = []
    notes_html = []
    for i, slide in enumerate(slides, 1):
        slides_html.append(render_slide(slide, i, len(slides)))
        note = parse_note(slide)
        notes_html.append(note)

    # notes HTML 转义后放进 data-note
    escaped_notes = [html.escape(n) if n else "" for n in notes_html]

    import json
    slides_js = json.dumps(slides_html, ensure_ascii=False)
    notes_js = json.dumps(escaped_notes, ensure_ascii=False)

    html_doc = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#eef1f5; font-family:'思源黑体','PingFang SC','Microsoft YaHei',sans-serif; }}
.app {{ display:flex; height:100vh; overflow:hidden; }}

/* ===== 左侧缩略图导航 ===== */
.sidebar {{ width:280px; background:#fff; border-right:1px solid #e5e7eb; padding:12px;
  overflow-y:auto; flex-shrink:0; }}
.sidebar .deck-title {{ font-size:14px; font-weight:700; color:#1f2937; padding:6px 4px 12px;
  border-bottom:1px solid #eef0f3; margin-bottom:10px; word-break:break-all; }}
.thumb-wrap {{ display:flex; gap:10px; padding:8px; border-radius:8px; cursor:pointer;
  border:2px solid transparent; margin-bottom:6px; }}
.thumb-wrap.active {{ border-color:#2563eb; background:#f0f6ff; }}
.thumb-num {{ width:20px; font-size:12px; color:#9ca3af; text-align:center; line-height:100px; flex-shrink:0; }}
.thumb-box {{ position:relative; width:200px; height:112px; overflow:hidden; flex-shrink:0;
  box-shadow:0 2px 6px rgba(0,0,0,.1); border-radius:4px; }}
.thumb-box .slide-mini {{ width:960px; height:540px; transform:scale(0.20833); transform-origin:0 0; }}

/* ===== 右侧预览区 ===== */
.main {{ flex:1; display:flex; flex-direction:column; overflow:hidden; }}
.preview-wrap {{ flex:1; display:flex; align-items:center; justify-content:center;
  padding:24px; overflow:auto; }}
.preview {{ position:relative; width:960px; height:540px; border-radius:12px;
  box-shadow:0 12px 40px rgba(0,0,0,.18); overflow:hidden; background:#fff; }}
.notes-panel {{ padding:16px 24px; background:#fff; border-top:1px solid #e5e7eb;
  max-height:180px; overflow-y:auto; }}
.notes-panel h3 {{ font-size:13px; color:#9ca3af; font-weight:600; margin-bottom:6px; }}
.notes-panel .notes-text {{ font-size:14px; color:#374151; line-height:1.7; white-space:pre-wrap; }}

/* ===== slide 内部通用 ===== */
.slide {{ position:relative; width:960px; height:540px; }}
.slide .shape {{ position:absolute; }}
.slide .shape p {{ margin:0; }}
.slide .shape ul {{ margin:6px 0 0 0; padding-left:22px; }}
.slide .shape li {{ margin:6px 0; }}
.slide .shape.ellipse {{ display:flex; align-items:center; justify-content:center; }}
.slide table {{ position:absolute; border-collapse:collapse; }}
.slide table td {{ border:1px solid rgba(83,97,116,.25); padding:10px 12px; vertical-align:middle; }}
.slide .icon {{ position:absolute; border-radius:8px; display:flex; align-items:center; justify-content:center; }}
.slide .line {{ position:absolute; }}
.slide .pagenum {{ position:absolute; right:20px; bottom:12px; font-size:12px; color:rgba(83,97,116,.6); }}
</style>
</head>
<body>
<div class="app">
  <!-- 左侧导航 -->
  <div class="sidebar">
    <div class="deck-title">{html.escape(title)}</div>
    <div id="thumb-list">
    {' '.join(f'''<div class="thumb-wrap {'active' if i==1 else ''}" data-idx="{i}" onclick="showPage({i})">
      <div class="thumb-num">{i}</div>
      <div class="thumb-box"><div class="slide-mini">{slides_html[i-1]}</div></div>
    </div>''' for i in range(1, len(slides)+1))}
    </div>
  </div>

  <!-- 右侧预览 -->
  <div class="main">
    <div class="preview-wrap" id="preview-wrap">
      <div class="preview" id="preview">{slides_html[0]}</div>
    </div>
    <div class="notes-panel">
      <h3>演讲者备注</h3>
      <div class="notes-text" id="notes">{escaped_notes[0] or '（无备注）'}</div>
    </div>
  </div>
</div>

<script>
const slides = {slides_js};
const notes = {notes_js};
function showPage(idx) {{
  const pv = document.getElementById('preview');
  pv.innerHTML = slides[idx-1];
  document.getElementById('notes').innerHTML = notes[idx-1] || '（无备注）';
  document.querySelectorAll('.thumb-wrap').forEach(el => el.classList.remove('active'));
  const tw = document.querySelector(`.thumb-wrap[data-idx="${{idx}}"]`);
  if (tw) tw.classList.add('active');
}}
</script>
</body>
</html>"""

    import os
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    print("生成完成:", out_path)
    print("页数:", len(slides))

if __name__ == '__main__':
    main()
