# Web / Desktop 图片认证恢复

Web 与 Desktop 的 `AuthProvider` 在启动时读取已保存的 token 并调用 `/auth` 验证。仅当验证成功且 token 非空时，才调用现有 `setAuthToken`，在放行受保护页面之前同步内存、localStorage 与 URL 编码的 `ethan_token` Cookie（现有 30 天、`path=/` 策略）。

这会修复 localStorage 仍有有效 token、但 Cookie 已过期、缺失或仍是旧 token 时，JSON 请求使用 Bearer 成功而同源图片请求失败的问题。验证失败不写 Cookie；无认证模式的空 token 验证成功也不生成 Cookie。恢复期间若用户已注销或登录了不同 token，旧验证结果不再更新 Cookie 或认证状态。注销仍清空内存、localStorage 与 Cookie。

此次修复不改变 `assetUrl`、跨域 query token、后端鉴权或资源访问范围，不增加 URL 中的明文 token。Desktop 保留现有的 URL 编码 query token 行为。

## 回归验证

复用 Desktop 的 Vitest / React Testing Library，通过共享参数化用例加载两端 `AuthProvider` 与各自真实 `api-base`；仅 mock 浏览器 `fetch`，不启动服务或使用真实凭证。

```bash
NODE_ENV=test pnpm --filter ethan-desktop exec vitest run tests/auth-provider.test.tsx
```

覆盖缺失、过期和旧 Cookie、验证完成前不写 Cookie、受保护图片渲染时 Cookie 已修复、失败验证、空 token、注销、恢复期间注销以及不同 token 登录的竞争。Web 同源图片 URL 不含 token query；Desktop 维持已有 URL 编码语义。jsdom 验证 Cookie 与渲染时序，不声称验证真实图片像素或生产浏览器。
