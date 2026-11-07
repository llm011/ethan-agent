import { describe, expect, it } from "vitest";
import { splitSpeakSentences } from "@ethan/shared/lib/speak";

describe("splitSpeakSentences", () => {
  it("长句按逗号再拆，保证高亮段与朗读段一一对应", () => {
    const text =
      "首先我们来看第一个问题，这个问题其实挺关键的，因为它直接决定了后面的所有推导，所以值得仔细说清楚。第二句很短。";
    const out = splitSpeakSentences(text);
    // 回归：以前高亮那份不拆逗号，同一段只出 2 段，念到第 3 句还停在第 1 句
    expect(out.length).toBe(5);
    expect(out.join("")).toBe(text);
  });

  it("短句不拆", () => {
    expect(splitSpeakSentences("第一句。第二句。")).toEqual(["第一句。", "第二句。"]);
  });

  it("无标点时整段返回", () => {
    expect(splitSpeakSentences("没有标点的一段话")).toEqual(["没有标点的一段话"]);
  });

  it("没有次级标点的超长句硬切，不丢字", () => {
    const long = "甲".repeat(95);
    const out = splitSpeakSentences(long);
    expect(out.every((s) => s.length <= 40)).toBe(true);
    expect(out.join("")).toBe(long);
  });
});
