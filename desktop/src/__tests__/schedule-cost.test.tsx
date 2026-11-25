import { describe, it, expect } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ScheduleCostSummary as Desktop } from "../components/schedule-cost-summary";
import { ScheduleCostSummary as Web } from "../../../web/components/schedule-cost-summary";
import type { ScheduleCost } from "../lib/api-misc";

const fixture: ScheduleCost = {
  window_days: 7, run_count: 5, input_tokens: 3100, cache_tokens: 1010,
  cache_hit_rate: 32.6, average_steps: 1.2, usage_run_count: 3,
  attribution: "message", unattributed_runs: 1,
};

for (const [name, Component] of [["Desktop", Desktop], ["Web", Web]] as const) {
  describe(`${name} schedule cost data contract`, () => {
    it("shows exact SQL totals, percentage, denominator and attribution warning", () => {
      render(<Component cost={fixture} />);
      expect(screen.getByText("近7天：运行 5 次 · 平均步数 1.2")).toBeTruthy();
      expect(screen.getByText("输入 3,100 token · 缓存 1,010")).toBeTruthy();
      expect(screen.getByText("命中率 32.6%")).toBeTruthy();
      expect(screen.getByText("有效 usage：3/5 次（缺失不估算）")).toBeTruthy();
      expect(screen.getByText("本用户另有 1 次历史运行未归因，不计入此任务")).toBeTruthy();
      cleanup();
    });
    it("does not pretend missing denominators or failed API are zero percent", () => {
      render(<Component cost={{ ...fixture, run_count: 0, average_steps: null, cache_hit_rate: null }} />);
      expect(screen.getByText("命中率 —")).toBeTruthy();
      cleanup();
      render(<Component />);
      expect(screen.getByText("近7天成本暂不可用")).toBeTruthy();
      cleanup();
    });
  });
}
