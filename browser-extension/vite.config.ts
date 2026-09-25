import { resolve } from 'node:path';
import { copyFileSync, mkdirSync, cpSync, writeFileSync, readFileSync } from 'node:fs';

import { defineConfig } from 'vite';
import * as ts from 'typescript';
import { build as esbuildBuild } from 'esbuild';

export default defineConfig({
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      input: {
        background: resolve(__dirname, 'src/background/index.ts'),
        offscreen: resolve(__dirname, 'src/offscreen/offscreen.ts'),
        popup: resolve(__dirname, 'src/popup/popup.js'),
        options: resolve(__dirname, 'src/options/options.js'),
      },
      output: {
        entryFileNames: '[name].js',
        format: 'esm',
      },
    },
    copyPublicDir: false,
  },
  plugins: [
    {
      name: 'copy-extension-assets',
      async writeBundle() {
        mkdirSync('dist/icons', { recursive: true });
        copyFileSync('src/manifest.json', 'dist/manifest.json');
        copyFileSync('src/popup/popup.html', 'dist/popup.html');
        copyFileSync('src/options/options.html', 'dist/options.html');
        copyFileSync('src/offscreen/offscreen.html', 'dist/offscreen.html');
        copyFileSync('src/redirect.html', 'dist/redirect.html');
        cpSync('src/assets/icons', 'dist/icons', { recursive: true });

        // Build content scripts: transpile TS → JS (classic script, no ESM/CJS artifacts)
        // executeScript({ files }) 不支持 ESM，需输出为 classic script
        mkdirSync('dist/content', { recursive: true });
        const contentScripts = ['reader-extract.ts', 'overlay.ts', 'cookie-closer.ts', 'reading-mode.ts', 'result-panel.ts', 'selection-bar.ts', 'tab-palette.ts'];
        for (const name of contentScripts) {
          let src: string;
          if (name === 'reading-mode.ts') {
            // reading-mode 拆分到 reading-mode/ 目录，按显式顺序 concat 入口 + 片段后编译
            const entrySrc = readFileSync(resolve(__dirname, `src/content/${name}`), 'utf8')
              .replace(/^\s*export\s*\{\s*\}\s*;?\s*$/m, '');
            const dir = resolve(__dirname, 'src/content/reading-mode');
            const order = [
              'state.ts', 'utils.ts', 'storage.ts', 'reader-api.ts',
              'reader-overlay.ts', 'image-overlay.ts', 'code-enhance.ts', 'annotation.ts', 'selection-toolbar.ts',
              'mark-click.ts', 'progress-toast.ts', 'ai-summary.ts',
              'panel.ts', 'spy-kbd-reenter.ts', 'entry.ts',
            ];
            src = entrySrc + '\n' + order.map(f => readFileSync(resolve(dir, f), 'utf8')).join('\n');
            // 预打包 highlight.js（common：~40 种语言）为 IIFE，注入为全局 __hljs。
            // reading-mode 是经典脚本（不能 import），需在构建时内联。
            const hljsResult = await esbuildBuild({
              entryPoints: [resolve(__dirname, 'node_modules/highlight.js/lib/common.js')],
              bundle: true,
              format: 'iife',
              globalName: '__hljs',
              write: false,
              minify: true,
              target: 'es2020',
              legalComments: 'none',
            });
            src = hljsResult.outputFiles[0].text + '\n' + src;
          } else {
            src = readFileSync(resolve(__dirname, `src/content/${name}`), 'utf8')
              .replace(/^\s*export\s*\{\s*\}\s*;?\s*$/m, '');  // 移除 export {} 避免 CJS interop
          }
          // 经典脚本不能 import，但「快捷键组合的解析/匹配」这类纯逻辑必须和单测用
          // 的是同一份代码——早期把它在 content script 里手抄了一遍，于是 shared 那份
          // 成了「只有测试引用的死代码」，两边会各自漂移。这里按同样的思路内联进来：
          // 入口文件标记 `/* @inline: <module> */`，构建时把该模块源码去掉 export 后
          // 拼在前面（同一个 IIFE 作用域，所以函数名直接可见）。
          const inlineMarkers = [...src.matchAll(/\/\*\s*@inline:\s*([\w./-]+)\s*\*\//g)];
          if (inlineMarkers.length) {
            const inlined = inlineMarkers.map(m => {
              const modPath = resolve(__dirname, 'src', `${m[1]}.ts`);
              return readFileSync(modPath, 'utf8')
                .replace(/^export\s+(function|const|let|class|interface|type)\b/gm, '$1')
                .replace(/^export\s+\{[^}]*\}\s*;?\s*$/gm, '')
                .replace(/^import\s[^;]*;\s*$/gm, '');
            });
            src = inlined.join('\n') + '\n' + src;
          }
          const { outputText } = ts.transpileModule(src, {
            compilerOptions: {
              target: ts.ScriptTarget.ES2020,
              module: ts.ModuleKind.None,
              removeComments: true,
            },
          });
          writeFileSync(resolve(__dirname, `dist/content/${name.replace('.ts', '.js')}`), outputText);
        }
      },
    },
  ],
  publicDir: false,
});
