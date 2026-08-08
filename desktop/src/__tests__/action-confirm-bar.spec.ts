import { describe, it, expect } from "vitest";
import { detectActionConfirm } from "@ethan/shared/chat/action-confirm-bar";

describe("detectActionConfirm", () => {
  describe("祈使句（应触发）", () => {
    const imperativeCases: Array<[string, string]> = [
      ["请扫码授权完成后告诉我", "授权"],
      ["扫码登录完成后告诉我下一步", "登录"],
      ["请扫码验证，完成后通知我", "默认"],
      ["授权完成后告诉我", "授权"],
      ["登录完成后告诉我", "登录"],
      ["操作完成后告诉我结果", "默认"],
      ["完成后告诉我", "默认"],
      ["操作完后说一声，我继续", "默认"],
      ["扫码授权后继续", "授权"],
    ];

    for (const [text, kind] of imperativeCases) {
      it(`命中: "${text}" → ${kind}`, () => {
        const r = detectActionConfirm(text);
        expect(r).not.toBeNull();
        expect(r!.shouldShow).toBe(true);
        if (kind === "授权") {
          expect(r!.confirmText).toContain("授权");
        } else if (kind === "登录") {
          expect(r!.confirmText).toContain("登录");
        }
      });
    }
  });

  describe("陈述句（不应触发）", () => {
    const declarativeCases = [
      "登录完成后我会告诉你下一步",
      "处理完成后我会通知你",
      "这个任务完成后我会告诉你结果",
      "授权完成后我会把结果发给你",
      "登录成功后就可以使用全部功能",
      "完成后我会通知你进展",
      "操作完后我会告诉你结果",
    ];

    for (const text of declarativeCases) {
      it(`不触发: "${text}"`, () => {
        expect(detectActionConfirm(text)).toBeNull();
      });
    }
  });

  describe("无关文本（不应触发）", () => {
    const irrelevantCases = [
      "你好，请问有什么可以帮你的？",
      "今天天气不错",
      "我已经完成了任务",
      "你先看看这个文档",
      "让我想想下一步怎么做",
    ];

    for (const text of irrelevantCases) {
      it(`不触发: "${text}"`, () => {
        expect(detectActionConfirm(text)).toBeNull();
      });
    }
  });
});
