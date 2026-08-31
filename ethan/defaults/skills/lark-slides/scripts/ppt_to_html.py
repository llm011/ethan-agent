#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将飞书 Slide XML 渲染为可离线浏览的 HTML 幻灯片"""
import re
import html
import xml.etree.ElementTree as ET

NS = "https://www.larkoffice.com/sml/2.0"

def q(tag):
    return f"{{{NS}}}{tag}"

def rgba_to_css(rgba_str, default="#fff"):
    """rgba(255,255,255,1) -> #ffffff 或 rgba()"""
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
    """解析 <style><fill><fillColor color=.../></fill></style>"""
    fill = style_elem.find(q('fill'))
    if fill is None:
        return None
    fc = fill.find(q('fillColor'))
    if fc is not None:
        return rgba_to_css(fc.get('color'))
    return None

def parse_content(shape):
    """解析 <content> 下的 <p> 文本和 <ul>/<li> 列表"""
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
        elif tag == q('br'):
            parts.append("<br>")
    return "".join(parts), attrs

def render_inline(elem):
    """渲染 <p>/<span>/<strong> 等内联元素"""
    # 直接文本
    if elem.text:
        return html.escape(elem.text)
    out = []
    for c in elem:
        if c.tag == q('strong'):
            inner = render_inline(c)
            color = c.get('color')
            if color:
                inner = f'<strong style="color:{rgba_to_css(color)}">' + inner.split('</strong>')[0] if False else inner
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

def icon_emoji(icon_type):
    """根据 icon 类型返回一个合适 emoji"""
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
    """渲染 <table>，读取自身坐标"""
    # 表格自身坐标（关键：之前漏掉了，导致塌缩到 0,0）
    tx = float(table.get('topLeftX', 0))
    ty = float(table.get('topLeftY', 0))
    tw = float(table.get('width', 840))
    th = float(table.get('height', 320))
    colgroup = table.find(q('colgroup'))
    col_widths = []
    if colgroup is not None:
        for col in colgroup:
            col_widths.append(float(col.get('width', 100)))
    # 列宽占比，用于给每列定宽
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
    # 设定表格绝对定位 + 列宽
    table_style = f"position:absolute;left:{tx}px;top:{ty}px;width:{tw}px;height:{th}px;"
    return f"<table style='{table_style}'>" + "".join(html_rows) + "</table>"

def render_shape(shape, notes):
    """渲染 shape/text 元素"""
    etype = shape.get('type', 'text')
    x = float(shape.get('topLeftX', 0))
    y = float(shape.get('topLeftY', 0))
    w = float(shape.get('width', 0))
    h = float(shape.get('height', 0))
    # 先读 fill 背景色（ellipse 会用到）
    fill_el = shape.find(q('fill'))
    bg = None
    if fill_el is not None:
        fc = fill_el.find(q('fillColor'))
        if fc is not None:
            bg = rgba_to_css(fc.get('color'))
    content, attrs = parse_content(shape)
    # ellipse：画圆形背景，有独立 text 覆盖
    if etype == 'ellipse':
        style = f"left:{x}px;top:{y}px;width:{w}px;height:{h}px;border-radius:50%;"
        if bg:
            style += f"background:{bg};"
        return f"<div class='shape ellipse' style='{style}'></div>"
    # rect：背景框，可能带圆角/描边（仅填色，无文本）
    if etype == 'rect':
        border_el = shape.find(q('border'))
        border_color = ""
        border_w = ""
        if border_el is not None:
            bc = border_el.get('color')
            if bc:
                border_color = rgba_to_css(bc)
            bw = border_el.get('width')
            if bw:
                border_w = bw
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
    # 换行/间距
    style += "line-height:1.4;"
    return f"<div class='shape' style='{style}'>{content}</div>"

def render_slide(slide, idx, total):
    """渲染单个 slide"""
    # 背景
    style_el = slide.find(q('style'))
    bg = parse_fill(style_el) if style_el is not None else "#ffffff"
    parts = []
    for child in slide:
        tag = child.tag
        if tag == q('style'):
            continue
        elif tag == q('data'):
            for elem in child:
                et = elem.tag
                if et == q('shape'):
                    parts.append(render_shape(elem, None))
                elif et == q('table'):
                    parts.append(render_table(elem))
                elif et == q('icon'):
                    x = float(elem.get('topLeftX', 0)); y = float(elem.get('topLeftY', 0))
                    w = float(elem.get('width', 40)); h = float(elem.get('height', 40))
                    fill = elem.find(q('fill'))
                    fg = "rgba(37,99,235,1)"
                    if fill is not None:
                        fc = fill.find(q('fillColor'))
                        if fc is not None:
                            fg = fc.get('color')
                    emo = icon_emoji(elem.get('iconType'))
                    parts.append(
                        f"<div class='icon' style='left:{x}px;top:{y}px;width:{w}px;height:{h}px;"
                        f"background:{rgba_to_css(fg)};'>"
                        f"<span style='color:rgba(255,255,255,.92);font-size:{int(h)*0.6}px;'>{emo}</span></div>"
                    )
                elif et == q('line'):
                    x1 = float(elem.get('startX', 0)); y1 = float(elem.get('startY', 0))
                    x2 = float(elem.get('endX', 0)); y2 = float(elem.get('endY', 0))
                    border = elem.find(q('border'))
                    color = "rgba(83,97,116,.3)"
                    if border is not None:
                        bc = border.get('color')
                        if bc:
                            color = rgba_to_css(bc)
                    # 是否有箭头
                    has_arrow = elem.find(q('endArrow')) is not None
                    marker = ""
                    if has_arrow:
                        marker = ' marker-end="url(#arrowhead)"'
                    parts.append(
                        f"<svg class='line' style='position:absolute;left:0;top:0;width:960px;height:540px;pointer-events:none;' "
                        f"width='960' height='540'>"
                        f"<defs><marker id='arrowhead' markerWidth='10' markerHeight='7' "
                        f"refX='9' refY='3.5' orient='auto'>"
                        f"<polygon points='0 0, 10 3.5, 0 7' fill='{color}'/></marker></defs>"
                        f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' "
                        f"stroke='{color}' stroke-width='2'{marker}/></svg>"
                    )
    # 页脚页码
    parts.append(f"<div class='pagenum'>{idx}/{total}</div>")
    return f"<div class='slide' style='background:{bg};'>{''.join(parts)}</div>"

def main():
    content = open('/tmp/ppt_content.xml', encoding='utf-8').read()
    # 用正则切割每个 slide（避免命名空间解析问题）
    slide_blocks = re.findall(r'<slide id="([^"]+)"[^>]*>(.*?)</slide>\s*</presentation>|</slide>(?=</presentation>)', content, re.S)
    # 更简单：先取 presentation 包裹
    m = re.search(r'(<presentation.*?</presentation>)', content, re.S)
    xml_content = m.group(1)
    root = ET.fromstring(xml_content)
    slides = root.findall(q('slide'))
    title = root.find(q('title'))
    title = title.text if title is not None else "PPT"
    
    slides_html = []
    for i, slide in enumerate(slides, 1):
        slides_html.append(render_slide(slide, i, len(slides)))
    
    html_doc = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>{html.escape(title)}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#e5e7eb; font-family:'思源黑体','PingFang SC','Microsoft YaHei',sans-serif; padding:20px; }}
h1 {{ text-align:center; color:#1f2937; font-size:24px; margin-bottom:16px; }}
.deck {{ max-width:960px; margin:0 auto; }}
.slide {{ position:relative; width:960px; height:540px; margin:20px auto; border-radius:8px;
  box-shadow:0 8px 24px rgba(0,0,0,.15); overflow:hidden; }}
.shape {{ position:absolute; }}
.shape p {{ margin:0; }}
.shape ul {{ margin:6px 0 0 0; padding-left:22px; }}
.shape li {{ margin:6px 0; }}
.shape.ellipse {{ display:flex; align-items:center; justify-content:center; }}
table {{ position:absolute; border-collapse:collapse; }}
table td {{ border:1px solid rgba(83,97,116,.25); padding:10px 12px; vertical-align:middle; }}
.icon {{ position:absolute; border-radius:8px; display:flex; align-items:center; justify-content:center; }}
.line {{ position:absolute; }}
.pagenum {{ position:absolute; right:20px; bottom:12px; font-size:12px; color:rgba(83,97,116,.6); }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<div class="deck">
{''.join(slides_html)}
</div>
</body>
</html>"""
    out = '/Users/jsongo/.ethan/out/lark-ppt/Agent_Harness.html'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    print("生成完成:", out)
    print("页数:", len(slides))

if __name__ == '__main__':
    main()
