// @ts-nocheck
/* eslint-disable */

  // ========== Annotation（高亮 / 划线 / 书签 / 批注） ==========

  type AnnoType = 'highlight' | 'underline' | 'strike' | 'bookmark' | 'comment';

  // 把 mark.className 和 dataset 设置统一封装
  function buildMark(type: AnnoType, color: string, note?: string): HTMLElement {
    const mark = document.createElement('mark');
    const cls = ['anno-' + type, 'anno-' + color];
    if (note) cls.push('anno-commented');
    mark.className = cls.filter(Boolean).join(' ');
    mark.dataset.annoType = type;
    if (note) { mark.title = note; mark.dataset.note = note; }
    return mark;
  }

  function applyAnnotation(range: Range, type: AnnoType, color: string, note?: string): boolean {
    if (!contentEl || !contentEl.contains(range.startContainer)) return false;
    // Collect text nodes in range
    const textNodes: Text[] = [];
    const walker = document.createTreeWalker(
      range.commonAncestorContainer.nodeType === Node.TEXT_NODE
        ? range.commonAncestorContainer.parentElement!
        : range.commonAncestorContainer as HTMLElement,
      NodeFilter.SHOW_TEXT
    );
    let node: Node | null;
    while ((node = walker.nextNode())) {
      if (range.intersectsNode(node) && (node as Text).nodeValue?.trim()) {
        textNodes.push(node as Text);
      }
    }
    if (!textNodes.length) return false;

    for (const tn of textNodes) {
      let target = tn;
      let startOff = 0;
      let endOff = tn.nodeValue!.length;
      if (tn === range.startContainer) startOff = range.startOffset;
      if (tn === range.endContainer) endOff = range.endOffset;
      if (startOff > 0) { target = tn.splitText(startOff); endOff -= startOff; }
      if (endOff < target.nodeValue!.length) target.splitText(endOff);

      const mark = buildMark(type, color, note);
      target.parentNode!.insertBefore(mark, target);
      mark.appendChild(target);
    }
    saveContent();
    scheduleRefresh();
    return true;
  }

  function applyHighlightColor(color: string) {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !contentEl) return;
    const range = sel.getRangeAt(0);
    if (applyAnnotation(range, 'highlight', color)) {
      sel.removeAllRanges();
    }
  }

  function removeHighlightFromSelection() {
    const sel = window.getSelection();
    if (!sel || !contentEl) return;
    // If cursor is inside a mark, unwrap it
    const node = sel.anchorNode;
    const mark = node?.parentElement?.closest('mark') || (node as HTMLElement)?.closest?.('mark');
    if (mark && contentEl.contains(mark)) {
      const parent = mark.parentNode;
      if (parent) {
        while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
        parent.removeChild(mark);
        parent.normalize();
      }
      saveContent();
      refreshAnnotations();
    }
  }
