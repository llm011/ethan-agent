import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { registerPrismLanguages } from "@ethan/shared/components/prism-languages";

/*
 * 钉住「白名单里声明的语言真的能高亮」。
 *
 * 为什么值得为它写单测：PrismLight.registerLanguage(name, lang) 会把 name 参数丢掉
 * （内部只有 `refractor.register(lang)`，只认 grammar 自带的 displayName / aliases），
 * 所以「手写一个别名键」是不生效的。而漏掉的失败方式**完全静默** —— markdown.tsx 用
 * `/language-(\w+)/` 原样抠出 fence 的语言，找不到就退化成纯文本：不报错、不抛异常、
 * 行号和复制按钮都还在，review 只看 diff 也看不出来。
 *
 * 判据用「渲染结果里有没有 token span」：未注册的语言走 react-syntax-highlighter 的
 * `defaultCodeValue` 兜底分支，只会输出纯文本，一个 span 都没有。
 *
 * 放在 desktop 下是因为仓库里只有 desktop 配了 vitest（web 只有 playwright e2e，
 * packages/shared 没有测试基建），被测对象是共享模块。
 */

const SyntaxHighlighter = registerPrismLanguages();

/** 每种语言配一段保证能出 token 的最小代码（实测 token 数均 ≥ 2）。 */
const SAMPLES: Record<string, string> = {
  bash: "echo $HOME",
  c: "int main(void) { return 0; }",
  cpp: "int main() { return 0; }",
  css: "a { color: red; }",
  diff: "+added\n-removed",
  go: "package main\nfunc main() {}",
  java: "class A { int x = 1; }",
  javascript: "const a = 1;",
  json: '{"a": 1}',
  jsx: 'const a = <div className="x" />;',
  kotlin: "fun main() { val x = 1 }",
  markdown: "# Title\n\n**bold**",
  markup: '<div class="x">hi</div>',
  python: "def f():\n    return 1",
  rust: "fn main() { let x = 1; }",
  sql: "SELECT * FROM t WHERE a = 1;",
  tsx: "const a: number = 1;",
  typescript: "const a: number = 1;",
  yaml: "key: value",
};

/**
 * fence 里常见、但需要单独验证的别名 → 其主语言。
 *
 * 前两条是 `PRISM_ALIASES` 显式注册的（grammar 没带，曾经就是漏的）；
 * 其余是 grammar 自带的 aliases，列出来免得以后有人「清理」掉注册逻辑时只保住主名。
 */
const ALIASES: Record<string, string> = {
  golang: "go",
  rs: "rust",
  sh: "bash",
  shell: "bash",
  js: "javascript",
  kt: "kotlin",
  md: "markdown",
  html: "markup",
  xml: "markup",
  py: "python",
  ts: "typescript",
  yml: "yaml",
};

function tokenCount(language: string, code: string) {
  const { container } = render(
    <SyntaxHighlighter language={language} useInlineStyles={false}>
      {code}
    </SyntaxHighlighter>
  );
  return container.querySelectorAll("span.token").length;
}

const cases: Array<[string, string]> = [
  ...Object.entries(SAMPLES),
  ...Object.entries(ALIASES).map(
    ([alias, canonical]) => [alias, SAMPLES[canonical]] as [string, string]
  ),
];

describe("prism 语言白名单", () => {
  it.each(cases)("`%s` 能高亮（没注册会静默退化成纯文本）", (language, code) => {
    expect(tokenCount(language, code)).toBeGreaterThan(0);
  });

  it("未注册的语言退化成纯文本，但组件不崩（负向对照）", () => {
    // 评审里确认过：走 defaultCodeValue 兜底，不抛异常、只丢高亮。
    expect(tokenCount("zig", "const a = 1;")).toBe(0);
  });

  it.each(["text", ""])("`%s` 不高亮也不报错", (language) => {
    expect(tokenCount(language, "const a = 1;")).toBe(0);
  });
});
