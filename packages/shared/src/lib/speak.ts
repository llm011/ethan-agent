// 朗读切句：把正文切成朗读用的句子单元。
//
// 这个规则必须**唯一**：朗读按段合成、跟读高亮按段定位，两边只要有一点不一致，
// 高亮就会和声音错位。之前 web/desktop 各写一份（高亮那份少做了「过长再按逗号拆」），
// 同一段正文朗读切出 5 段、高亮只有 2 段，念到第 3 句还停在第 1 句上。
// 所以收敛到这里，两端都从这里 import。

/** 句末标点：遇到就断句。换行也算，正文里的换行通常就是语义停顿。 */
const SENTENCE_END = /(?<=[。！？；!?;\n])/;

/** 从句里再拆的次级标点：单句过长时用它们切短，避免一句生成太久。 */
const CLAUSE_END = /(?<=[，,、])/;

/**
 * 把正文切成朗读句。
 *
 * @param text   正文
 * @param maxLen 单句上限（字符数）。超过就按逗号/顿号再拆；仍然过长则硬切。
 */
export function splitSpeakSentences(text: string, maxLen = 40): string[] {
  const parts = text.split(SENTENCE_END).filter((s) => s.trim());
  const out: string[] = [];
  for (const part of parts) {
    if (part.length <= maxLen) {
      out.push(part);
      continue;
    }
    for (const seg of part.split(CLAUSE_END)) {
      let rest = seg;
      // 没有逗号可拆的超长句（英文长句、无标点长段）只能硬切，否则单次合成太久
      while (rest.length > maxLen) {
        out.push(rest.slice(0, maxLen));
        rest = rest.slice(maxLen);
      }
      if (rest.trim()) out.push(rest);
    }
  }
  return out.length ? out : [text];
}
