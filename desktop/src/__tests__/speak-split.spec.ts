import { describe, expect, it } from "vitest";
import { splitSpeakSentences } from "@/hooks/use-speaking";

describe("splitSpeakSentences", () => {
  it("长句按逗号再拆，保证高亮段与朗读段一一对应", () => {
    const text =
      "首先我们来看第一个问题，这个问题其实挺关键的，因为它直接决定了后面的所有推导，所以值得仔细说清楚。第二句很短。";
    const out = splitSpeakSentences(text);
    expect(out.length).toBe(5);
    expect(out.join("")).toBe(text);
  });

  it("短句不拆", () => {
    expect(splitSpeakSentences("第一句。第二句。")).toEqual(["第一句。", "第二句。"]);
  });

  it("无标点时整段返回", () => {
    expect(splitSpeakSentences("没有标点的一段话")).toEqual(["没有标点的一段话"]);
  });
});
