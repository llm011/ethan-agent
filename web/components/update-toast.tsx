"use client";

import { useEffect, useRef, useState } from "react";

/** 注册 Service Worker，可在 Providers 挂载时调用一次。 */
export function registerSW() {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("/sw.js").catch(() => {
    /* 注册失败静默处理，不影响主流程 */
  });
}

/** 版本更新提示条：检测到新 SW waiting 时显示，用户点击刷新激活。 */
export function UpdateToast() {
  const [waiting, setWaiting] = useState(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;

    registerSW();
    const reg = navigator.serviceWorker;

    // 启动时检查是否已有 waiting 的 SW（如页面刷新后）
    const checkWaiting = async () => {
      const r = await reg.getRegistration();
      if (r && r.waiting) setWaiting(true);
    };
    checkWaiting();

    // 新 SW 安装完成 -> 显示提示
    const onUpdateFound = async () => {
      const r = await reg.getRegistration();
      if (!r || !r.installing) return;
      r.installing.addEventListener("statechange", () => {
        if (r.installing && r.installing.state === "installed" && reg.controller) {
          setWaiting(true);
        }
      });
    };

    // 新 SW 接管后刷新页面加载新资源
    const onControllerChange = () => {
      window.location.reload();
    };

    reg.addEventListener("updatefound", onUpdateFound);
    reg.addEventListener("controllerchange", onControllerChange);

    return () => {
      reg.removeEventListener("updatefound", onUpdateFound);
      reg.removeEventListener("controllerchange", onControllerChange);
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, []);

  // 显示后 10 秒自动隐藏
  useEffect(() => {
    if (waiting) {
      hideTimer.current = setTimeout(() => setWaiting(false), 10000);
    }
    return () => {
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, [waiting]);

  const handleRefresh = () => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.getRegistration().then((r) => {
      if (r && r.waiting) {
        r.waiting.postMessage({ type: "SKIP_WAITING" });
      }
    });
  };

  if (!waiting) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        width: "100%",
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "12px",
        padding: "8px 16px",
        background: "#fef3c7",
        color: "#92400e",
        fontSize: "14px",
        boxShadow: "0 1px 4px rgba(0,0,0,0.12)",
      }}
    >
      <span>有新版本可用</span>
      <button
        type="button"
        onClick={handleRefresh}
        style={{
          background: "#92400e",
          color: "#fef3c7",
          border: "none",
          borderRadius: "4px",
          padding: "4px 12px",
          fontSize: "13px",
          cursor: "pointer",
          fontWeight: 600,
        }}
      >
        刷新
      </button>
    </div>
  );
}
