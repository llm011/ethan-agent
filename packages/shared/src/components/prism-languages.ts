// 从**子路径**导入，不要走包根入口（`from "react-syntax-highlighter"`）：
// 根入口的 barrel 同时 re-export 了 `Prism`（全量 ~300 种语言），那样瘦身就得指望
// 打包器把 `refractor/all` 摇掉——webpack 能摇，但不保证所有消费端（比如 desktop 的
// vite/rollup、vitest）行为一致。直接引子路径后「只有白名单进包」是结构上成立的。
import PrismLight from "react-syntax-highlighter/dist/esm/prism-light";

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

/**
 * 注册的白名单语言。
 *
 * key 只作可读性用途：真正决定注册名的是 grammar 自带的 `displayName` ——
 * `PrismLight.registerLanguage(name, lang)` 会把 name 参数**丢掉**
 * （实现就是 `refractor.register(lang)`，只认 `lang.displayName` 和 `lang.aliases`）。
 * 所以想加别名不能在这里加键，见下面的 `PRISM_ALIASES`。
 */
export const PRISM_LANGUAGES: Record<string, { displayName: string }> = {
  bash,
  c,
  cpp,
  css,
  diff,
  go,
  java,
  javascript,
  json,
  jsx,
  kotlin,
  markdown,
  markup,
  python,
  rust,
  sql,
  tsx,
  typescript,
  yaml,
};

/**
 * 需要**显式**注册的别名。
 *
 * 为什么只有两条：注册主语言时，grammar 自带的 `aliases` 已经跟着一起注册了 ——
 * `bash`→`sh`/`shell`、`javascript`→`js`、`kotlin`→`kt`、`markdown`→`md`、
 * `markup`→`html`/`xml`、`python`→`py`、`typescript`→`ts`、`yaml`→`yml`，
 * 这些不用管。而 ```golang / ```rs 这两个写法很常见，grammar 里却没有，
 * 只能靠 `alias()` 补上。
 *
 * 漏了的后果是**静默**降级：fence 的语言是 `markdown.tsx` 里用
 * `/language-(\w+)/` 原样抠出来的，`golang` / `rs` 找不到就退化成纯文本
 * （不报错、行号和复制按钮都还在，只有高亮没了），肉眼和 review 都看不出来。
 * 别删。
 */
const PRISM_ALIASES: Record<string, string[]> = {
  go: ["golang"],
  rust: ["rs"],
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
    for (const lang of Object.values(PRISM_LANGUAGES)) {
      // 第一个参数会被 refractor 丢掉，传 displayName 只是为了让读的人不误解。
      PrismLight.registerLanguage(lang.displayName, lang);
    }
    // 必须在上面的 register 之后：alias 只是把语言表里的引用再挂一份。
    PrismLight.alias(PRISM_ALIASES);
  }
  return PrismLight;
}
