import { resolve } from 'node:path';
import { copyFileSync, mkdirSync } from 'node:fs';

import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      input: {
        background: resolve(__dirname, 'src/background/index.ts'),
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
      writeBundle() {
        mkdirSync('dist', { recursive: true });
        copyFileSync('src/manifest.json', 'dist/manifest.json');
        copyFileSync('src/options/options.html', 'dist/options.html');
      },
    },
  ],
  publicDir: false,
});
