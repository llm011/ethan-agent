/* 气泡身份（当前用户的头像 + 显示名）的共享读取 hook。
 *
 * 与 useCachedResource 的分工：那一层负责「缓存 + 后台刷新 + bust 失效」，
 * 这一层负责「把两端的 fetcher 注入进来 + 给出稳定的空态」。
 *
 * 为什么走缓存而不是每次挂载都 fetch：
 *   消息列表在切换会话时会整体重挂，头像/名字是准静态数据，每次重挂都打一次
 *   接口纯属浪费；而且缓存让气泡首帧就能渲染出正确头像，不会先显示占位再跳成
 *   真实头像。桌面端 uploadAvatar/updateDisplayName 会 bustCache("userIdentity")，
 *   所以设置完立刻能反映到气泡上。
 */
import type { UserIdentity } from "./user-identity";
import { useCachedResource } from "../lib/use-cached-resource";

/** 缓存 key，两端与 api-settings 的 bustCache 调用必须一致。 */
export const USER_IDENTITY_CACHE_KEY = "userIdentity";

const EMPTY_IDENTITY: UserIdentity = { user_id: "", display_name: "", avatar_url: "" };

export interface UseUserIdentityResult {
  identity: UserIdentity;
  /** 是否已拿到（缓存命中或请求已回来）。未拿到时 identity 是全空对象，不必等。 */
  ready: boolean;
}

export function useUserIdentity(fetcher: () => Promise<UserIdentity>): UseUserIdentityResult {
  // ttlMs 给足：头像/名字只在用户主动改的时候变，那个路径会 bustCache，
  // 不依赖 TTL 过期。这里 5 分钟只是为了兜住「另一端改了」这种少见的场景。
  const { data } = useCachedResource<UserIdentity>(USER_IDENTITY_CACHE_KEY, fetcher, { ttlMs: 300_000 });
  return { identity: data ?? EMPTY_IDENTITY, ready: data != null };
}
