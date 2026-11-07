import { afterEach, describe, expect, it } from "vitest";
import { isMacTauriRuntime, overlayTitlebarLeftInset } from "@/lib/window-chrome";

const originalUA = navigator.userAgent;

function setRuntime(opts: { tauri?: boolean; ua?: string; platform?: string }) {
  if (opts.tauri) (window as unknown as { isTauri?: boolean }).isTauri = true;
  Object.defineProperty(navigator, "userAgent", {
    value: opts.ua ?? originalUA,
    configurable: true,
  });
  Object.defineProperty(navigator, "platform", {
    value: opts.platform ?? "",
    configurable: true,
  });
}

afterEach(() => {
  delete (window as unknown as { isTauri?: boolean }).isTauri;
  delete (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
  Object.defineProperty(navigator, "userAgent", { value: originalUA, configurable: true });
  Object.defineProperty(navigator, "platform", { value: "", configurable: true });
});

describe("窗口装饰安全区（window-chrome）", () => {
  it("浏览器/web 端没有系统交通灯，不需要让位", () => {
    setRuntime({ ua: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" });
    expect(isMacTauriRuntime()).toBe(false);
    expect(overlayTitlebarLeftInset()).toBe(0);
  });

  it("macOS 桌面壳给交通灯留出 84px 安全区", () => {
    setRuntime({
      tauri: true,
      ua: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
      platform: "MacIntel",
    });
    expect(isMacTauriRuntime()).toBe(true);
    expect(overlayTitlebarLeftInset()).toBe(84);
  });

  it("Windows/Linux 桌面壳有原生标题栏，内容不与窗口按钮重叠", () => {
    setRuntime({
      tauri: true,
      ua: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      platform: "Win32",
    });
    expect(isMacTauriRuntime()).toBe(false);
    expect(overlayTitlebarLeftInset()).toBe(0);
  });

  it("__TAURI_INTERNALS__ 也能识别桌面壳", () => {
    (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
    Object.defineProperty(navigator, "userAgent", {
      value: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
      configurable: true,
    });
    expect(isMacTauriRuntime()).toBe(true);
  });
});
