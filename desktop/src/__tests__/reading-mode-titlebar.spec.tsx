import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReadingMode } from "@/components/chat/reading-mode";
import type { Message } from "@ethan/shared/chat/types";

// 回归：macOS 主窗口是 titleBarStyle: "Overlay"，阅读模式覆盖整个窗口时，
// 顶部条的关闭按钮不能压在系统交通灯上（截图里「退出阅读模式」和红黄绿重叠）。

const originalUA = navigator.userAgent;

const message = { id: 1, role: "assistant", content: "一段正文" } as Message;

function headerPaddingLeft(): string {
  // 「阅读模式」标题的父节点就是顶部条
  return (screen.getByText("阅读模式").parentElement as HTMLElement).style.paddingLeft;
}

afterEach(() => {
  delete (window as unknown as { isTauri?: boolean }).isTauri;
  Object.defineProperty(navigator, "userAgent", { value: originalUA, configurable: true });
});

describe("阅读模式顶部条让开 macOS 交通灯", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "userAgent", {
      value: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
      configurable: true,
    });
  });

  it("macOS 桌面端：顶部条左侧留出交通灯安全区", () => {
    (window as unknown as { isTauri?: boolean }).isTauri = true;
    render(<ReadingMode open message={message} annotations={[]} onClose={() => {}} onChange={() => {}} />);
    expect(headerPaddingLeft()).toBe("84px");
  });

  it("web/非 macOS：保持原来的 16px 内边距（由 px-4 提供）", () => {
    render(<ReadingMode open message={message} annotations={[]} onClose={() => {}} onChange={() => {}} />);
    expect(headerPaddingLeft()).toBe("");
  });
});
