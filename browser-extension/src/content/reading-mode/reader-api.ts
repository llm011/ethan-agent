// @ts-nocheck
/* eslint-disable */

  // ========== Content Detection & Cleaning ==========
  // 检测正文 / 清洗 / 转 Markdown 统一走 reader-extract.js 暴露的 window.__ethanReader，
  // 注入顺序由 reading-injector.ts 保证（reader-extract 先于 reading-mode）。

  interface EthanReaderApi {
    detectArticle(): HTMLElement;
    cleanArticle(el: HTMLElement): HTMLElement;
    htmlToMarkdown(root: HTMLElement): string;
    extractMarkdown(): { markdown: string; length: number; title: string; url: string };
  }

  function ethanReader(): EthanReaderApi {
    const api = (window as any).__ethanReader as EthanReaderApi | undefined;
    if (!api) throw new Error('__ethanReader not injected');
    return api;
  }

  // ========== TOC from content ==========

  interface TocItem { level: number; text: string; el: HTMLElement; }

  function generateToc(root: HTMLElement): TocItem[] {
    const items: TocItem[] = [];
    root.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {
      const el = h as HTMLElement;
      const text = el.textContent?.trim() || '';
      if (!text || text.length > 80) return;
      items.push({ level: parseInt(el.tagName[1]), text, el });
    });
    return items;
  }
