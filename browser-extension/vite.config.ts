import { resolve } from 'node:path';
import { copyFileSync, mkdirSync, cpSync, writeFileSync, readFileSync } from 'node:fs';

import { defineConfig } from 'vite';
import * as ts from 'typescript';

export default defineConfig({
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      input: {
        background: resolve(__dirname, 'src/background/index.ts'),
        offscreen: resolve(__dirname, 'src/offscreen/offscreen.ts'),
        popup: resolve(__dirname, 'src/popup/popup.js'),
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
      writeBundle() {
        mkdirSync('dist/icons', { recursive: true });
        copyFileSync('src/manifest.json', 'dist/manifest.json');
        copyFileSync('src/popup/popup.html', 'dist/popup.html');
        copyFileSync('src/offscreen/offscreen.html', 'dist/offscreen.html');
        copyFileSync('src/redirect.html', 'dist/redirect.html');
        cpSync('src/assets/icons', 'dist/icons', { recursive: true });

        // Build content scripts: transpile TS → JS (classic script, no ESM/CJS artifacts)
        // executeScript({ files }) 不支持 ESM，需输出为 classic script
        mkdirSync('dist/content', { recursive: true });
        const contentScripts = ['reader-extract.ts', 'overlay.ts', 'cookie-closer.ts', 'reading-mode.ts', 'result-panel.ts'];
        for (const name of contentScripts) {
          const src = readFileSync(resolve(__dirname, `src/content/${name}`), 'utf8')
            .replace(/^\s*export\s*\{\s*\}\s*;?\s*$/m, '');  // 移除 export {} 避免 CJS interop
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
