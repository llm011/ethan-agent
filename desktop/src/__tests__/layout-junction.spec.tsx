import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { HeaderFillet } from "@/components/header-fillet";
import { Sidebar } from "@/components/Sidebar";
import { SidebarContext } from "@/components/layout-shell";

// 回归：侧边栏与对话区的转角。
//
// 历史问题（截图：白色对话区左上角有圆弧、但圆弧脚下横着一条 sidebar 色小尾巴，
// 且竖向一条边线都没有）：
//   1) 融合块比圆弧盘高 1px（h-[calc(100%+13px)] vs 圆弧 h-3=12px），多出的 1px
//      横着盖在白色对话区顶上，看起来像转角没画完；
//   2) 桌面端 <aside> 没有 border-r，圆弧收尾后竖线凭空断掉 ->「竖向没有边线」。
//
// 这里守住两条几何契约：融合块必须正好止于圆弧底部；桌面端侧边栏必须有 border-r
// 接住圆弧收尾的竖线。

function renderFillet() {
  const { container } = render(
    <SidebarContext.Provider value={{ sidebarOpen: true, setSidebarOpen: () => {} }}>
      <div className="relative">
        <HeaderFillet />
      </div>
    </SidebarContext.Provider>
  );
  const [fusion, arc] = Array.from(container.querySelectorAll(":scope > div > div")) as HTMLElement[];
  return { fusion, arc };
}

describe("侧边栏 / 对话区转角", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("融合块正好止于圆弧底部，不会在圆弧脚下露出横条", () => {
    const { fusion, arc } = renderFillet();
    expect(fusion).toBeTruthy();
    expect(arc).toBeTruthy();

    // 融合块向下延伸的像素数
    const extend = fusion.className.match(/h-\[calc\(100%\+(\d+)px\)\]/);
    expect(extend, "融合块高度应为 `h-[calc(100%+Npx)]`").toBeTruthy();
    const fusionExtend = Number(extend![1]);

    // 圆弧盘高度 h-3 = 12px（圆弧从 header 底线往下弯 12px）
    expect(arc.className).toContain("rounded-tl-full");
    expect(arc.className).toContain("h-3");
    const arcHeight = 12;

    // 融合块比圆弧高 1px 就会在圆弧脚下漏一条 sidebar 色横条
    expect(fusionExtend).toBe(arcHeight);
  });

  it("圆弧盘自带底/左两条边线，收尾处交还给 sidebar 的 border-r", () => {
    const { fusion, arc } = renderFillet();
    expect(arc.className).toContain("border-l");
    expect(arc.className).toContain("border-t");
    expect(arc.className).toContain("bg-background");
    // 融合块负责盖住 header + 圆弧区段的 sidebar 竖线
    expect(fusion.className).toContain("bg-sidebar");
  });

  it("桌面端侧边栏带 border-r，接住圆弧收尾的那条竖线", async () => {
    // 圆弧画到 sidebar 右边缘就结束了，下面这条竖线只能由 aside 的 border-r 提供；
    // 缺了它，转角看上去就是「竖向没有边线」。
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: any) => {
        const url = String(input);
        const body = url.includes("/schedule")
          ? '{"jobs":[]}'
          : url.includes("/modes")
            ? '{"modes":[]}'
            : url.includes("/sessions/pinned")
              ? '{"sessions":[]}'
              : url.includes("/sessions")
                ? "[]"
                : "{}";
        return new Response(body, { status: 200, headers: { "Content-Type": "application/json" } });
      })
    );
    const { container } = render(
      <MemoryRouter>
        <SidebarContext.Provider value={{ sidebarOpen: true, setSidebarOpen: () => {} }}>
          <Sidebar />
        </SidebarContext.Provider>
      </MemoryRouter>
    );
    // 侧边栏挂载后会拉一轮数据，等状态落定，免得 act() 告警刷屏
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    const aside = container.querySelector("aside");
    expect(aside).toBeTruthy();
    expect(aside!.className).toContain("border-r");
    expect(aside!.className).toContain("border-border");
  });
});
