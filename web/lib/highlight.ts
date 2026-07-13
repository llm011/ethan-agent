// 基于「渲染后纯文本」字符偏移的高亮/划线工具。
// 气泡与阅读模式共用 MarkdownContent 渲染，因此两端 DOM 文本节点序列一致，
// 同一套 offset 在两端都能精确回显标注。

export interface HighlightSpan {
  id: number;
  type: string;
  color: string | null;
  start: number;
  end: number;
  note?: string | null;
}

function annoClass(span: HighlightSpan): string {
  const colorCls = span.color ? `anno-${span.color}` : "";
  return ["anno-mark", colorCls, `anno-${span.type}`].filter(Boolean).join(" ");
}

/** 把选区换算成相对 root 纯文本的 [start, end) 字符偏移。无有效选区返回 null。 */
export function getSelectionOffsets(root: HTMLElement): { start: number; end: number } | null {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;

  const calc = (container: Node, offset: number): number => {
    let total = 0;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n: Node | null;
    while ((n = walker.nextNode())) {
      if (n === container) return total + offset;
      total += (n as Text).nodeValue?.length ?? 0;
    }
    if (container === root) return offset;
    return total;
  };

  const a = calc(range.startContainer, range.startOffset);
  const b = calc(range.endContainer, range.endOffset);
  return a <= b ? { start: a, end: b } : { start: b, end: a };
}

/** 移除所有已渲染的标注（把 <mark> 拆掉、文本合并回父节点）。 */
function unwrapMarks(root: HTMLElement) {
  root.querySelectorAll("mark[data-anno-id]").forEach((mark) => {
    const parent = mark.parentNode;
    if (!parent) return;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
    parent.normalize();
  });
}

/** 把 [start, end) 区间用 <mark> 包裹（支持跨多个文本节点）。 */
function wrapRange(root: HTMLElement, start: number, end: number, span: HighlightSpan) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const targets: { node: Text; s: number; e: number }[] = [];
  let offset = 0;
  let n: Node | null;
  while ((n = walker.nextNode())) {
    const len = (n as Text).nodeValue?.length ?? 0;
    const nodeStart = offset;
    const nodeEnd = offset + len;
    if (nodeEnd <= start) {
      offset = nodeEnd;
      continue;
    }
    if (nodeStart >= end) break;
    targets.push({ node: n as Text, s: Math.max(0, start - nodeStart), e: Math.min(len, end - nodeStart) });
    offset = nodeEnd;
  }

  for (const { node, s, e } of targets) {
    const after = node.splitText(s); // node[0,s)  after[s,len)
    after.splitText(e - s); // after[s,e) 保留；尾段 [e,len) 留在原位，无需引用
    const mark = document.createElement("mark");
    mark.dataset.annoId = String(span.id);
    mark.className = annoClass(span);
    if (span.note) mark.title = span.note;
    after.parentNode?.insertBefore(mark, after);
    mark.appendChild(after);
  }
}

/** 在 root 内应用（重绘）一组标注。faint=true 时降低透明度，用于气泡内联预览。 */
export function applyHighlights(root: HTMLElement, spans: HighlightSpan[], faint = false) {
  if (!root) return;
  unwrapMarks(root);
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  for (const span of sorted) {
    if (span.end <= span.start) continue;
    wrapRange(root, span.start, span.end, span);
  }
  root.classList.toggle("anno-faint", faint);
}
