import "@testing-library/jest-dom/vitest";

// jsdom(vitest 环境)不提供 localStorage（探测：typeof localStorage === "undefined"）。
// 组件层（local-cache / server-url / api-base）在渲染路径上会碰它，缺了会把整棵
// 组件树拖崩 —— 现在组件代码已有 globalThis 防御，这里再补一个 polyfill 让
// 「缓存命中首帧渲染」这类用例能真正走到缓存读写。
if (typeof globalThis.localStorage === "undefined") {
  const store = new Map<string, string>();
  (globalThis as any).localStorage = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    get length() { return store.size; },
  };
}
