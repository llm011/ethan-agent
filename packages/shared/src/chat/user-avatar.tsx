/* 用户头像 —— 对话气泡里显示「我」的头像，使用户消息与 assistant 消息对称。
 *
 * 为什么放在 shared 而两端各写一份：
 *   两端的气泡布局、尺寸、圆角必须逐像素一致（见根 CLAUDE.md 的双端同步规范），
 *   而两端的差异只有「相对 URL → 绝对 URL」这一步（Web 有个 NEXT_PUBLIC_BASE_PATH
 *   前缀，Desktop 走 getApiUrl()）。把差异收敛成一个 resolveUrl 回调，
 *   其余（尺寸 / 圆角 / 兜底首字母 / 错误回退）就只有一份实现。
 *
 * 兜底策略（三层，缺一层就会出现「破图」或「空白」）：
 *   1. 没设置头像（url 为空）→ 首字母（name 首个字符）；name 也空 → 通用人形图标
 *   2. 设置了但加载失败（跨域 / 文件被删 / 签名过期）→ 退回首字母/图标，
 *      而不是留一个破图占位
 *   3. 加载中 → 显示兜底内容，避免布局先塌再撑（leading-aligned 列表会跳）
 */
import * as React from "react";
import { User as UserIcon } from "lucide-react";

import { cn } from "../lib/utils";

/** 气泡里的头像尺寸。assistant 侧 logo 是 28px，用户侧必须一致，否则一左一右不等高。 */
export const BUBBLE_AVATAR_SIZE = 28;

export interface UserAvatarProps {
  /** 相对 URL（后端 avatar_url 字段）；空串 = 未设置，走兜底 */
  url?: string;
  /** 显示名，用于取首字母兜底 */
  name?: string;
  /** 把相对 URL 转成当前端的绝对 URL。空串输入必须原样返回空串。 */
  resolveUrl: (relativePath: string) => string;
  /** 覆盖尺寸（px）。默认与 assistant 侧 logo 对齐的 28。 */
  size?: number;
  className?: string;
}

/** 取显示名首字母/首字作为兜底内容。中英文都取第一个字素。 */
export function avatarInitial(name?: string): string {
  const trimmed = (name ?? "").trim();
  if (!trimmed) return "";
  // Array.from 按码点切分：直接用 name[0] 会把 emoji / 罕见汉字切成半个代理对，
  // 渲染出乱码方块。
  const [first] = Array.from(trimmed);
  return first ? first.toUpperCase() : "";
}

export function UserAvatar({ url, name, resolveUrl, size = BUBBLE_AVATAR_SIZE, className }: UserAvatarProps) {
  const src = url ? resolveUrl(url) : "";
  // 记录失败的那个 src：换头像后（src 变化）要重置失败态，否则新头像永远不显示。
  const [failedSrc, setFailedSrc] = React.useState<string | null>(null);
  const failed = failedSrc != null && failedSrc === src;

  const initial = avatarInitial(name);
  const showImage = !!src && !failed;

  return (
    <div
      data-slot="user-avatar"
      className={cn(
        "shrink-0 rounded-full overflow-hidden select-none",
        "bg-muted text-muted-foreground",
        "flex items-center justify-center",
        className,
      )}
      style={{ width: size, height: size }}
      // 头像只是装饰：名字/首字母对屏幕阅读器没有额外信息量，重复一遍反而啰嗦。
      aria-hidden="true"
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          width={size}
          height={size}
          className="h-full w-full object-cover"
          onError={() => setFailedSrc(src)}
        />
      ) : initial ? (
        <span className="text-xs font-medium leading-none" style={{ fontSize: Math.round(size * 0.42) }}>
          {initial}
        </span>
      ) : (
        <UserIcon style={{ width: Math.round(size * 0.55), height: Math.round(size * 0.55) }} />
      )}
    </div>
  );
}
