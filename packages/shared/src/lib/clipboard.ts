// 阅读模式「选中文字 → 复制」的共享实现。
//
// 为什么不能只用 navigator.clipboard.writeText：
//   1. Clipboard API 只在**安全上下文**（https / localhost）可用。用户常通过
//      `http://<局域网 IP>:8900` 访问 Web 端，那里 navigator.clipboard 直接是
//      undefined，「复制」会静默失败。
//   2. 权限策略（如 iframe 未带 clipboard-write、企业策略禁用剪贴板）会抛
//      NotAllowedError。
// 因此这里做两级回退：Clipboard API → 隐藏 textarea + execCommand("copy")。
// 返回布尔值让调用方决定是否提示失败，绝不静默吞掉。

/** 把 text 复制到剪贴板。成功返回 true，两条路径都失败返回 false。 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (!text) return false;

  // 路径一：异步 Clipboard API（安全上下文才有）
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // 落到 execCommand 回退：权限被拒 / 非安全上下文 / 文档未聚焦
    }
  }

  // 路径二：隐藏 textarea + execCommand，兼容 http 局域网访问与老浏览器
  if (typeof document === "undefined") return false;
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    // 保持在视口内并只占 1px，避免 iOS 上因元素不可见而复制失败、也避免页面跳动
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.left = "0";
    ta.style.width = "1px";
    ta.style.height = "1px";
    ta.style.padding = "0";
    ta.style.border = "none";
    ta.style.outline = "none";
    ta.style.boxShadow = "none";
    ta.style.background = "transparent";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    // iOS Safari 必须显式选中并设置 range，否则 execCommand 复制的不是 textarea 内容
    ta.focus({ preventScroll: true });
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
