/* Ethan Agent Service Worker — 三层缓存策略
 * - App Shell (HTML/CSS/JS/static): CacheFirst，install 时预缓存
 * - /_next/static/ 内容哈希文件: CacheFirst（可长期缓存）
 * - /api/sessions GET: NetworkFirst，网络失败降级缓存（支持离线浏览）
 * - 图标/图片等静态资源: StaleWhileRevalidate
 * - 其余请求: 直接放行，不缓存
 * 更新策略：不自动激活，等 app 发 SKIP_WAITING 消息后才接管。
 */

const SHELL_CACHE = "ethan-shell-v1";
const STATIC_CACHE = "ethan-static-v1";
const API_CACHE = "ethan-api-v1";
const SHELL_ASSETS = ["/", "/manifest.json", "/icon-192.png", "/icon-512.png", "/apple-icon.png"];

// ---------- install: 预缓存 App Shell ----------
self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      // 单个失败不阻断整体安装
      await Promise.all(
        SHELL_ASSETS.map((url) =>
          cache.add(new Request(url, { cache: "reload" })).catch(() => {}),
        ),
      );
      // 安装成功后才 skipWaiting —— 但我们不自动激活，留给 app 通过 message 触发
    })(),
  );
});

// ---------- activate: 清理旧缓存 + 接管客户端 ----------
self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // 删除所有不以 ethan- 开头的旧缓存，以及过期版本缓存
      const keys = await caches.keys();
      await Promise.all(
        keys.map((k) => {
          if (!k.startsWith("ethan-")) return caches.delete(k);
          return null;
        }),
      );
      // 立即接管所有客户端（首次安装时减少刷新等待）
      await self.clients.claim();
    })(),
  );
});

// ---------- 接收 app 控制消息 ----------
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

// ---------- fetch: 按请求类型分发缓存策略 ----------
self.addEventListener("fetch", (event) => {
  const req = event.request;
  // 只处理 GET，POST/PUT/DELETE 等直接放行
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  // 跨源请求直接放行（如跨域图片、字体 CDN）
  if (url.origin !== self.location.origin) return;

  // 导航请求（HTML 页面）：NetworkFirst，失败降级到缓存的 index
  if (req.mode === "navigate") {
    event.respondWith(handleNavigation(req));
    return;
  }

  // /_next/static/ 内容哈希文件：CacheFirst，永久缓存
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(cacheFirst(req, STATIC_CACHE));
    return;
  }

  // /api/sessions GET 请求：NetworkFirst，失败降级缓存
  if (url.pathname.startsWith("/api/sessions")) {
    event.respondWith(handleSessionsApi(req));
    return;
  }

  // 图标/图片/字体等静态资源：StaleWhileRevalidate
  if (/\.(?:png|jpg|jpeg|gif|svg|ico|webp|woff2?|ttf|eot|css|js)$/i.test(url.pathname)) {
    event.respondWith(staleWhileRevalidate(req, SHELL_CACHE));
    return;
  }

  // 其余请求：直接走网络，不缓存
});

// 导航请求处理：网络优先，失败用缓存兜底
async function handleNavigation(req) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const res = await fetch(req);
    if (res && res.ok) cache.put(req, res.clone());
    return res;
  } catch {
    const cached = await cache.match(req);
    if (cached) return cached;
    const index = await cache.match("/");
    if (index) return index;
    return new Response("离线状态，且无可用缓存", { status: 503, statusText: "Offline" });
  }
}

// /api/sessions 处理：NetworkFirst，缓存成功响应，失败降级缓存并标记
async function handleSessionsApi(req) {
  const cache = await caches.open(API_CACHE);
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      cache.put(req, res.clone());
    }
    return res;
  } catch {
    // 网络失败，从缓存返回并加标记头
    const cached = await cache.match(req);
    if (cached) {
      const headers = new Headers(cached.headers);
      headers.set("X-Offline-Cache", "hit");
      return new Response(cached.body, {
        status: cached.status,
        statusText: cached.statusText,
        headers,
      });
    }
    return new Response(JSON.stringify({ error: "离线模式：无可用缓存" }), {
      status: 503,
      headers: { "Content-Type": "application/json", "X-Offline-Cache": "miss" },
    });
  }
}

// CacheFirst：先查缓存，未命中再取网络并缓存
async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) return cached;
  try {
    const res = await fetch(req);
    if (res && res.ok) cache.put(req, res.clone());
    return res;
  } catch {
    // 兜底：再查 SHELL_CACHE
    const shell = await caches.open(SHELL_CACHE);
    const fallback = await shell.match(req);
    if (fallback) return fallback;
    throw new Error("offline");
  }
}

// StaleWhileRevalidate：立即返回缓存，同时后台更新
async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  const fetchPromise = fetch(req)
    .then((res) => {
      if (res && res.ok) cache.put(req, res.clone());
      return res;
    })
    .catch(() => cached);
  return cached || fetchPromise;
}
