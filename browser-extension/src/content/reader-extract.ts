/* eslint-disable */
// 共享的正文提取核心（经典脚本，不能 import）：检测正文容器 → 清洗 → 转 Markdown。
//
// 三个消费方原先各有一份「猜正文 + 清洗 + 转 MD」的实现且互不一致：
//   - background/index.ts 的快捷键提取（executeScript func）
//   - content/reading-mode.ts 的阅读模式
//   - 服务端 browser.py 的 _MARKDOWN_SCRIPT（Python，暂不并入）
// 本文件把扩展侧两份统一为一份，挂到 window.__ethanReader，供两处复用。
//
// 注入方式：executeScript({ files: ['content/reader-extract.js'] })。幂等（重复注入直接返回）。

interface EthanReaderApi {
  detectArticle(): HTMLElement;
  cleanArticle(el: HTMLElement): HTMLElement;
  htmlToMarkdown(root: HTMLElement): string;
  extractMarkdown(): { markdown: string; length: number; title: string; url: string };
}

(function () {
  const w = window as any;
  if (w.__ethanReader) return;

  // ── 检测正文容器 ────────────────────────────────────────────

  function scoreBlock(el: HTMLElement): number {
    const text = el.innerText || '';
    const textLen = text.length;
    if (textLen < 100) return 0;
    const pCount = el.querySelectorAll('p').length;
    const linkText = Array.from(el.querySelectorAll('a')).reduce(
      (s, a) => s + (a.textContent?.length || 0),
      0,
    );
    const linkRatio = textLen > 0 ? linkText / textLen : 1;
    let score = textLen * 0.5 + pCount * 50;
    if (linkRatio > 0.5) score *= 0.2;
    if (el.tagName === 'ARTICLE' || el.tagName === 'MAIN') score *= 1.5;
    if (el === document.body) score *= 0.3;
    return score;
  }

  function detectArticle(): HTMLElement {
    const candidates: { el: HTMLElement; score: number }[] = [];
    const selectors =
      'article, main, [role="main"], .post-content, .article-content, .entry-content, .content, .post-body, .article-body';
    document.querySelectorAll(selectors).forEach(el => {
      candidates.push({ el: el as HTMLElement, score: scoreBlock(el as HTMLElement) });
    });
    document.querySelectorAll('div, section').forEach(el => {
      const h = el as HTMLElement;
      if (h.offsetHeight < 200) return;
      const text = h.innerText || '';
      if (text.length < 300) return;
      candidates.push({ el: h, score: scoreBlock(h) });
    });
    candidates.sort((a, b) => b.score - a.score);
    return candidates[0]?.el || document.body;
  }

  // ── 清洗 ────────────────────────────────────────────────────
  // 返回一个去掉噪声、剥离 style/class/id 的克隆节点。code/pre 的 class 保留，
  // 以便下游 htmlToMarkdown 能从 language-* 里读出代码语言。

  function cleanArticle(el: HTMLElement): HTMLElement {
    const clone = el.cloneNode(true) as HTMLElement;
    const rm =
      'script, style, nav, aside, footer, header, form, iframe, noscript, svg, button, ' +
      '.ad, .ads, .advertisement, [aria-hidden="true"], .sidebar, .comments, .related, ' +
      '.share, .social, [class*="ad-"], [class*="popup"], [class*="modal"], [class*="banner"]';
    clone.querySelectorAll(rm).forEach(n => n.remove());
    clone.querySelectorAll('div, section').forEach(n => {
      const h = n as HTMLElement;
      if ((h.innerText || '').length < 20 && h.querySelectorAll('a').length > 2) h.remove();
    });
    clone.querySelectorAll('*').forEach(n => {
      const h = n as HTMLElement;
      const tag = h.tagName.toLowerCase();
      // 保留 code/pre 的 class（含 language-*），其余全部剥离
      if (tag !== 'code' && tag !== 'pre') h.removeAttribute('class');
      h.removeAttribute('style');
      h.removeAttribute('id');
    });
    return clone;
  }

  // ── HTML → Markdown ─────────────────────────────────────────
  // 递归拼接。支持标题/段落/加粗斜体/行内与块级代码(含语言)/引用/链接/图片/
  // 有序无序列表/表格。mark(高亮) 透明化：只取其子节点内容。

  function convertNode(node: Node): string {
    let r = '';
    node.childNodes.forEach(c => {
      if (c.nodeType === Node.TEXT_NODE) {
        const t = (c.textContent || '').trim();
        if (t) r += t + ' ';
        return;
      }
      if (c.nodeType !== Node.ELEMENT_NODE) return;
      const el = c as HTMLElement;
      const tag = el.tagName.toLowerCase();
      const inner = () => convertNode(el).trim();
      switch (tag) {
        case 'h1': r += '\n# ' + inner() + '\n\n'; break;
        case 'h2': r += '\n## ' + inner() + '\n\n'; break;
        case 'h3': r += '\n### ' + inner() + '\n\n'; break;
        case 'h4': r += '\n#### ' + inner() + '\n\n'; break;
        case 'h5': r += '\n##### ' + inner() + '\n\n'; break;
        case 'h6': r += '\n###### ' + inner() + '\n\n'; break;
        case 'p': r += inner() + '\n\n'; break;
        case 'br': r += '\n'; break;
        case 'hr': r += '\n---\n\n'; break;
        case 'strong': case 'b': r += '**' + inner() + '**'; break;
        case 'em': case 'i': r += '*' + inner() + '*'; break;
        case 'mark': r += inner(); break;  // 高亮透明化，只留内容
        case 'div': {
          if (el.classList.contains('code-wrapper')) {
            const pre = el.querySelector('pre');
            if (pre) { r += convertNode({ childNodes: [pre] } as any); break; }
          }
          r += convertNode(el);
          break;
        }
        case 'code':
          if (el.parentElement && el.parentElement.tagName.toLowerCase() === 'pre') break;
          r += '`' + (el.innerText || '') + '`';
          break;
        case 'pre': {
          const code = el.querySelector('code');
          const lang = code ? (code.className.match(/language-(\w+)/) || [])[1] : '';
          const text = code ? code.innerText : el.innerText || '';
          r += '\n```' + (lang || '') + '\n' + text + '\n```\n\n';
          break;
        }
        case 'blockquote':
          r += '\n> ' + inner().replace(/\n/g, '\n> ') + '\n\n';
          break;
        case 'a': {
          const h = el.getAttribute('href') || '';
          const t = el.innerText || '';
          r += h && t ? '[' + t + '](' + h + ')' : t;
          break;
        }
        case 'img': {
          const s = el.getAttribute('src') || el.getAttribute('data-src') || '';
          const a = el.getAttribute('alt') || '';
          if (s) r += '![' + a + '](' + s + ')';
          break;
        }
        case 'ul': case 'ol': r += '\n' + convertList(el, tag === 'ol') + '\n\n'; break;
        case 'table': r += convertTable(el) + '\n\n'; break;
        default: r += convertNode(el);
      }
    });
    return r;
  }

  function convertList(list: HTMLElement, ordered: boolean): string {
    let r = '';
    let i = 1;
    for (const li of Array.from(list.children)) {
      if (li.tagName.toLowerCase() !== 'li') continue;
      const marker = ordered ? i++ + '. ' : '- ';
      r += marker + convertNode(li as HTMLElement).trim().replace(/\n/g, '\n  ') + '\n';
    }
    return r;
  }

  function convertTable(t: HTMLElement): string {
    const rows = t.querySelectorAll('tr');
    if (!rows.length) return '';
    let r = '';
    let first = true;
    rows.forEach(row => {
      const cells = Array.from(row.querySelectorAll('th,td')).map(
        c => ((c as HTMLElement).innerText || '').trim().replace(/\n/g, ' '),
      );
      r += '| ' + cells.join(' | ') + ' |\n';
      if (first) {
        r += '|' + cells.map(() => '---').join('|') + '|\n';
        first = false;
      }
    });
    return r;
  }

  function htmlToMarkdown(root: HTMLElement): string {
    return convertNode(root).replace(/\n{3,}/g, '\n\n').trim();
  }

  // ── 一站式：从当前文档提取正文 Markdown ─────────────────────

  function extractMarkdown(): { markdown: string; length: number; title: string; url: string } {
    const clean = cleanArticle(detectArticle());
    const md = htmlToMarkdown(clean);
    return { markdown: md, length: md.length, title: document.title, url: location.href };
  }

  const api: EthanReaderApi = { detectArticle, cleanArticle, htmlToMarkdown, extractMarkdown };
  w.__ethanReader = api;
})();
