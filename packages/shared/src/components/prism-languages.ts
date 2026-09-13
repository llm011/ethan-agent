import { PrismLight } from "react-syntax-highlighter";

// 代码高亮的语言白名单 —— 全仓库**只在这里**注册一次。
//
// 背景：`react-syntax-highlighter` 的 `Prism`（非 Light）导出会把 prism 的
// **全部约 300 种语言**静态打进来，而绝大多数用户只会碰到下面这十几种。
// 换成 `PrismLight` 后只有注册过的语言进包。
//
// 验证方式：构建后 grep 产物 chunk，白名单外的语言（zig / cmake / erlang /
// brainfuck / applescript / elixir / haskell / lua / perl / r …）均 0 命中，
// 白名单内的（python / rust / kotlin / go / typescript …）有命中。
//
// 为什么单独抽一个模块：`code-block.tsx`（web / desktop / shared 三份独立副本）
// 和 `tool-timeline.tsx` 都要用同一个高亮器实例。如果各自 import 各自的 `PrismLight`
// 再各自注册，只要**任何一处**漏了，那 300 种语言就会顺着那一处的 import 图重新
// 进包——瘦身直接失效。注册集中在 `registerPrismLanguages()`，各消费方调一次即可
// （重复调用是幂等的，语言注册就是往 map 里塞，覆盖同名键）。
//
// 需要新语言时在这里加一行 import + 一行白名单即可。
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import c from "react-syntax-highlighter/dist/esm/languages/prism/c";
import cpp from "react-syntax-highlighter/dist/esm/languages/prism/cpp";
import css from "react-syntax-highlighter/dist/esm/languages/prism/css";
import diff from "react-syntax-highlighter/dist/esm/languages/prism/diff";
import go from "react-syntax-highlighter/dist/esm/languages/prism/go";
import java from "react-syntax-highlighter/dist/esm/languages/prism/java";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx";
import kotlin from "react-syntax-highlighter/dist/esm/languages/prism/kotlin";
import markdown from "react-syntax-highlighter/dist/esm/languages/prism/markdown";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import rust from "react-syntax-highlighter/dist/esm/languages/prism/rust";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";

/** 注册的白名单语言（含常见别名，如 ```sh / ```py / ```yml / ```html）。 */
export const PRISM_LANGUAGES: Record<string, unknown> = {
  bash,
  sh: bash,
  shell: bash,
  c,
  cpp,
  "c++": cpp,
  css,
  diff,
  go,
  golang: go,
  java,
  javascript,
  js: javascript,
  json,
  jsx,
  kotlin,
  kt: kotlin,
  markdown,
  md: markdown,
  markup,
  html: markup,
  xml: markup,
  python,
  py: python,
  rust,
  rs: rust,
  sql,
  tsx,
  typescript,
  ts: typescript,
  yaml,
  yml: yaml,
};

let registered = false;

/**
 * 注册白名单语言并返回高亮器组件。幂等。
 *
 * 注意：未注册的语言**不会报错**，会按纯文本渲染（只是没有高亮）。这是
 * 「体积换极少数场景高亮」的有意取舍。
 */
export function registerPrismLanguages() {
  if (!registered) {
    registered = true;
    for (const [name, lang] of Object.entries(PRISM_LANGUAGES)) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      PrismLight.registerLanguage(name, lang as any);
    }
  }
  return PrismLight;
}
