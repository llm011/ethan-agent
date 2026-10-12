"""Browser selectors implementation; browser.py keeps compatibility exports."""
from __future__ import annotations

from .browser_compat import browser as B

# ── page.markdown 正文提取脚本 ──────────────────────────────────
# 在页面上下文中执行，克隆 DOM → 移除噪音 → 找正文区 → 转 Markdown。
_MARKDOWN_SCRIPT = r"""(() => {
  const clone = document.body.cloneNode(true);
  clone.querySelectorAll('nav,header,footer,aside,script,style,iframe,noscript,svg,form,button,[role="navigation"],[role="banner"],[role="contentinfo"],.ad,.ads,.advertisement,.sidebar,.cookie,.popup,.modal,.share,.related,.comments').forEach(e => e.remove());

  let main = clone.querySelector('article') || clone.querySelector('main') || clone.querySelector('[role="main"]') || clone.querySelector('#content,.content,.post-content,.article-content,.entry-content,.post-body,.article-body');
  if (!main) {
    let best = null, bestScore = 0;
    for (const el of clone.querySelectorAll('div,section')) {
      const t = (el.innerText||''), len = t.length;
      if (len < 200) continue;
      const score = len - el.querySelectorAll('a').length * 50;
      if (score > bestScore) { bestScore = score; best = el; }
    }
    main = best || clone;
  }

  function cv(node) {
    let r = '';
    for (const c of node.childNodes) {
      if (c.nodeType === 3) { const t = c.textContent.trim(); if (t) r += t + ' '; continue; }
      if (c.nodeType !== 1) continue;
      const tag = c.tagName.toLowerCase();
      const inner = () => cv(c).trim();
      switch (tag) {
        case 'h1': r += '\n# '+inner()+'\n\n'; break;
        case 'h2': r += '\n## '+inner()+'\n\n'; break;
        case 'h3': r += '\n### '+inner()+'\n\n'; break;
        case 'h4': r += '\n#### '+inner()+'\n\n'; break;
        case 'h5': r += '\n##### '+inner()+'\n\n'; break;
        case 'h6': r += '\n###### '+inner()+'\n\n'; break;
        case 'p': r += inner()+'\n\n'; break;
        case 'br': r += '\n'; break;
        case 'hr': r += '\n---\n\n'; break;
        case 'strong': case 'b': r += '**'+inner()+'**'; break;
        case 'em': case 'i': r += '*'+inner()+'*'; break;
        case 'code':
          if (c.parentElement && c.parentElement.tagName.toLowerCase()==='pre') break;
          r += '`'+(c.innerText||'')+'`'; break;
        case 'pre': {
          const code = c.querySelector('code');
          const lang = code ? (code.className.match(/language-(\w+)/)||[])[1] : '';
          r += '\n```'+(lang||'')+'\n'+(c.innerText||'')+'\n```\n\n'; break;
        }
        case 'blockquote': r += '\n> '+inner().replace(/\n/g,'\n> ')+'\n\n'; break;
        case 'a': { const h=c.getAttribute('href')||'', t=c.innerText||''; r += h&&t ? '['+t+']('+h+')' : t; break; }
        case 'img': { const s=c.getAttribute('src')||c.getAttribute('data-src')||'', a=c.getAttribute('alt')||''; if(s) r += '!['+a+']('+s+')'; break; }
        case 'ul': case 'ol': r += '\n'+cvList(c, tag==='ol')+'\n\n'; break;
        case 'table': r += cvTable(c)+'\n\n'; break;
        default: r += cv(c);
      }
    }
    return r;
  }
  function cvList(list, ord) {
    let r = '', i = 1;
    for (const li of list.children) {
      if (li.tagName.toLowerCase() !== 'li') continue;
      r += (ord ? (i++)+'. ' : '- ') + cv(li).trim().replace(/\n/g,'\n  ') + '\n';
    }
    return r;
  }
  function cvTable(t) {
    const rows = t.querySelectorAll('tr'); if (!rows.length) return '';
    let r = '', first = true;
    for (const row of rows) {
      const cells = Array.from(row.querySelectorAll('th,td')).map(c => (c.innerText||'').trim().replace(/\n/g,' '));
      r += '| '+cells.join(' | ')+' |\n';
      if (first) { r += '|'+cells.map(()=>'---').join('|')+'|\n'; first = false; }
    }
    return r;
  }

  let md = cv(main).replace(/\n{3,}/g,'\n\n').trim();
  return JSON.stringify({markdown: md, length: md.length, title: document.title, url: location.href});
})()"""


# ── selector 操作辅助函数（Python 侧组合现有 CDP 方法，不改扩展）──


async def _eval_js(session: str, script: str):
    """执行页面 JS，返回解析后的 value。"""
    result = await B._call("page_eval", {"sessionId": session, "script": script},
                         browser_session_id=session)
    if isinstance(result, dict):
        return result.get("value")
    return result


async def _click_point(session: str, x: float, y: float):
    """在指定坐标模拟真实鼠标点击（move + down + up），绕过 eval .click() 的 React 问题。"""
    await B._call("page_mouse", {"sessionId": session, "action": "move", "x": x, "y": y},
                browser_session_id=session)
    await B._call("page_mouse", {"sessionId": session, "action": "down", "button": "left"},
                browser_session_id=session)
    await B._call("page_mouse", {"sessionId": session, "action": "up", "button": "left"},
                browser_session_id=session)


def _build_locate_script(selector: str = "", xpath: str = "", text: str = "", nth: int = 0) -> str:
    """生成定位元素的 JS，返回 {x, y, text, found} 或 {found: false}。"""
    import json as _json
    if selector:
        return f"(() => {{\n  const el = document.querySelector({_json.dumps(selector)});\n  if (!el) return JSON.stringify({{found: false}});\n  el.scrollIntoView({{block: 'center'}});\n  const r = el.getBoundingClientRect();\n  return JSON.stringify({{found: true, x: r.x + r.width/2, y: r.y + r.height/2, text: (el.innerText||'').slice(0, 80)}});\n}})()"
    if xpath:
        return f"(() => {{\n  const el = document.evaluate({_json.dumps(xpath)}, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;\n  if (!el) return JSON.stringify({{found: false}});\n  el.scrollIntoView({{block: 'center'}});\n  const r = el.getBoundingClientRect();\n  return JSON.stringify({{found: true, x: r.x + r.width/2, y: r.y + r.height/2, text: (el.innerText||'').slice(0, 80)}});\n}})()"
    if text:
        return f"(() => {{\n  const els = [...document.querySelectorAll('*')].filter(el => {{\n    const t = el.innerText || '';\n    return t.includes({_json.dumps(text)}) && el.children.length <= 5 && el.offsetParent !== null;\n  }});\n  const el = els[{nth}] || els[0];\n  if (!el) return JSON.stringify({{found: false, match_count: els.length}});\n  el.scrollIntoView({{block: 'center'}});\n  const r = el.getBoundingClientRect();\n  return JSON.stringify({{found: true, x: r.x + r.width/2, y: r.y + r.height/2, text: (el.innerText||'').slice(0, 80), match_count: els.length}});\n}})()"
    return "JSON.stringify({found: false, error: '需要 selector/xpath/text 之一'})"

