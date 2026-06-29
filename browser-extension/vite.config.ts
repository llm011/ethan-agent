import { resolve } from 'node:path';
import { copyFileSync, mkdirSync, cpSync } from 'node:fs';

import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      input: {
        background: resolve(__dirname, 'src/background/index.ts'),
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
        cpSync('src/assets/icons', 'dist/icons', { recursive: true });
      },
    },
  ],
  publicDir: false,
});
