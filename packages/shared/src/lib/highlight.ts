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

/**
 * 取当前选区在 root 内的纯文本。用于「选中即复制」。
 *
 * 不用 `window.getSelection()?.toString()`，因为选区跨到 root 之外（例如把正文和
 * 右侧标注面板一起拖进来）时它会把面板文字一并带上；这里只认 root 内那段 Range，
 * 与 [getSelectionOffsets] 用同一份纯文本口径，保证复制的就是被标注/被复制的原文。
 */
export function getSelectionText(root: HTMLElement): string {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return "";
  const range = sel.getRangeAt(0);
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return "";

  // 选区可能反向拖拽（anchor 在后、focus 在前），先按文档顺序归一
  const ordered =
    range.startContainer === range.endContainer
      ? range
      : root.compareDocumentPosition(range.endContainer) & Node.DOCUMENT_POSITION_FOLLOWING ||
          range.startContainer.compareDocumentPosition(range.endContainer) & Node.DOCUMENT_POSITION_FOLLOWING
        ? range
        : null;

  const clone = (ordered ?? range).cloneRange();
  // 夹到 root 之内：选区起点若在 root 之前（理论上已被上面的 contains 挡掉，
  // 但 Range 允许部分重叠），这里再收一次边，避免把 root 外的文字算进来。
  if (!root.contains(clone.startContainer)) clone.setStart(root, 0);
  if (!root.contains(clone.endContainer)) clone.setEnd(root, root.childNodes.length);

  const fragment = clone.cloneContents();
  // 与 [getSelectionOffsets] 的 TreeWalker 口径一致：只用 textContent，
  // 不取 innerText（后者会按 CSS 可见性/display 增删文本，offset 就对不上了）。
  return textContentWithBreaks(fragment);
}

/**
 * 拼接片段的纯文本，并在块级边界补换行。
 *
 * 直接用 `fragment.textContent` 会把相邻段落粘成一行（`<p>a</p><p>b</p>` → "ab"），
 * 复制出去没法读；而 `selection.toString()` 又会插双份空行（段落间 `\n\n`）。
 * 这里以 textContent 为唯一事实（保证与字符 offset 同口径），只在块级元素之间
 * 插一个 `\n`，行内元素（strong/em/code/a）不打断句子。
 * 表头/单元格是同一行的兄弟节点，所以插空字符串（纯拼接）。
 */
function textContentWithBreaks(fragment: DocumentFragment): string {
  const BLOCK = new Set([
    "P", "DIV", "LI", "UL", "OL", "H1", "H2", "H3", "H4", "H5", "H6",
    "BLOCKQUOTE", "TR", "PRE", "SECTION", "ARTICLE", "TABLE", "DT", "DD",
  ]);
  let out = "";
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out += node.nodeValue ?? "";
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
    const el = node as Element;
    const tag = el.nodeName;
    // 行内代码/公式里的 <br> 也要保留换行，所以 br 单独处理
    if (tag === "BR") {
      out += "\n";
      return;
    }
    const isBlock = BLOCK.has(tag);
    if (isBlock && out && !out.endsWith("\n")) out += "\n";
    node.childNodes.forEach(walk);
    if (isBlock && out && !out.endsWith("\n")) out += "\n";
  };
  fragment.childNodes.forEach(walk);
  // 去掉文件末尾多余的空白，但保留段内/段间换行
  return out.replace(/\s+$/, "");
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
    if (span.note) mark.dataset.note = span.note;
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
