/**
 * 「全部对话」页批量操作回归测试（桌面端）。
 *
 * 覆盖三件容易回归的事：
 * 1. 不进批量模式时，点卡片是「打开预览」；进批量模式后，点卡片是「选中」——
 *    两种语义不能串（串了会变成选着选着跳进会话）。
 * 2. 批量条上的按钮在「未选任何项」时必须是禁用的，否则会发一个空 ids 请求。
 * 3. 后端回的 deleted/missing（以及 updated/missing/skipped）要如实呈现在提示语里，
 *    不能把「列表已过期、有 N 个已不存在」静默吞掉。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

const sessionsFixture = [
  { id: "s1", title: "写周报", model: "m", created_at: 1, updated_at: 1, source: "web" },
  { id: "s2", title: "看论文", model: "m", created_at: 1, updated_at: 1, source: "web" },
];

const fetchSessionsMock = vi.fn(async () => sessionsFixture);
const deleteSessionsBatchMock = vi.fn(async () => ({ deleted: 1, missing: 1 }));
const toggleDoneSessionsBatchMock = vi.fn(async () => ({ updated: 2, missing: 0, skipped: 0 }));
const fetchSessionMock = vi.fn(async () => ({ id: "s1", title: "写周报", model: "m", messages: [] }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchSessions: (...a: unknown[]) => fetchSessionsMock(...(a as [])),
    deleteSessionsBatch: (...a: unknown[]) => deleteSessionsBatchMock(...(a as [])),
    toggleDoneSessionsBatch: (...a: unknown[]) => toggleDoneSessionsBatchMock(...(a as [])),
    fetchSession: (...a: unknown[]) => fetchSessionMock(...(a as [])),
    fetchModes: vi.fn(async () => []),
  };
});

vi.mock("@/components/chat/message-list", () => ({
  MessageList: () => <div data-testid="message-list" />,
}));

import { AllSessionsView } from "@/components/all-sessions-view";

/** 等待首屏那一页会话渲染出来。 */
async function renderView() {
  const onSelectSession = vi.fn();
  render(<AllSessionsView onSelectSession={onSelectSession} />);
  await screen.findByText("写周报");
  return { onSelectSession };
}

const enterSelectMode = () => fireEvent.click(screen.getByTitle(/进入批量操作/));

/**
 * 取批量条里的按钮。
 *
 * 不能用 `getByRole("button", { name: /标记完成/ })`——卡片上每个会话的「完成」
 * 图标按钮也有 title="标记完成（...）"，会命中多个元素。批量条在 DOM 里是
 * 「已选 N 项」那个 span 的父容器，从这里往下找才唯一。
 */
function batchBar() {
  const label = screen.getByText(/^已选 \d+ 项$/);
  const bar = label.parentElement as HTMLElement;
  return {
    button: (re: RegExp) => {
      const el = Array.from(bar.querySelectorAll("button")).find((b) =>
        re.test(b.textContent || "")
      );
      if (!el) throw new Error(`批量条里找不到按钮：${re}`);
      return el as HTMLButtonElement;
    },
  };
}

/** 点某张卡片的勾选框（用 aria-label 定位，避免依赖 DOM 层级）。 */
const checkCard = (index = 0) => {
  const boxes = screen.getAllByLabelText("选择对话");
  fireEvent.click(boxes[index]);
};

describe("全部对话页 · 批量操作", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchSessionsMock.mockResolvedValue([...sessionsFixture]);
  });

  afterEach(() => cleanup());

  it("默认不进批量模式：点卡片走预览，卡片上没有勾选框", async () => {
    const { onSelectSession } = await renderView();

    expect(screen.queryByLabelText("选择对话")).toBeNull();
    fireEvent.click(screen.getByText("写周报"));

    await waitFor(() => expect(fetchSessionMock).toHaveBeenCalledWith("s1"));
    // 预览是打开 Sheet，不该直接跳进会话
    expect(onSelectSession).not.toHaveBeenCalled();
  });

  it("进入批量模式后点卡片是选中，不再走预览", async () => {
    await renderView();
    enterSelectMode();

    expect(await screen.findByText("已选 0 项")).toBeTruthy();
    fireEvent.click(screen.getByText("写周报"));

    expect(await screen.findByText("已选 1 项")).toBeTruthy();
    expect(fetchSessionMock).not.toHaveBeenCalled();
  });

  it("未选任何项时，批量按钮禁用（不发空 ids 请求）", async () => {
    await renderView();
    enterSelectMode();

    const doneBtn = batchBar().button(/标记完成/);
    const delBtn = batchBar().button(/^删除$/);
    expect(doneBtn.disabled).toBe(true);
    expect(delBtn.disabled).toBe(true);

    fireEvent.click(delBtn);
    expect(deleteSessionsBatchMock).not.toHaveBeenCalled();
  });

  it("标记完成：把选中的 id 透传，并提示 updated 数", async () => {
    await renderView();
    enterSelectMode();
    checkCard(0);
    checkCard(1);

    fireEvent.click(batchBar().button(/标记完成/));

    await waitFor(() =>
      expect(toggleDoneSessionsBatchMock).toHaveBeenCalledWith(["s1", "s2"], true)
    );
    expect(await screen.findByText(/已标记完成 2 个/)).toBeTruthy();
  });

  it("取消完成：done=false 透传", async () => {
    await renderView();
    enterSelectMode();
    checkCard(0);

    fireEvent.click(batchBar().button(/取消完成/));

    await waitFor(() =>
      expect(toggleDoneSessionsBatchMock).toHaveBeenCalledWith(["s1"], false)
    );
  });

  it("提示语要带上 skipped（系统会话被跳过），不能只报 updated", async () => {
    toggleDoneSessionsBatchMock.mockResolvedValueOnce({ updated: 1, missing: 0, skipped: 3 });
    await renderView();
    enterSelectMode();
    checkCard(0);

    fireEvent.click(batchBar().button(/标记完成/));

    expect(await screen.findByText(/3 个系统会话已跳过/)).toBeTruthy();
  });

  it("批量删除要先确认，确认后提示 deleted 与 missing", async () => {
    await renderView();
    enterSelectMode();
    checkCard(0);

    fireEvent.click(batchBar().button(/^删除$/));
    // 未确认前不能真删
    expect(deleteSessionsBatchMock).not.toHaveBeenCalled();

    const confirm = await screen.findByRole("button", { name: /^删除$/ });
    fireEvent.click(confirm);

    await waitFor(() => expect(deleteSessionsBatchMock).toHaveBeenCalledWith(["s1"]));
    expect(await screen.findByText(/已删除 1 个，另有 1 个已不存在/)).toBeTruthy();
  });

  it("全选本页 / 取消全选", async () => {
    await renderView();
    enterSelectMode();

    fireEvent.click(batchBar().button(/全选本页/));
    expect(await screen.findByText("已选 2 项")).toBeTruthy();

    fireEvent.click(batchBar().button(/取消全选/));
    expect(await screen.findByText("已选 0 项")).toBeTruthy();
  });

  it("退出批量会清空选中态并收起勾选框", async () => {
    await renderView();
    enterSelectMode();
    checkCard(0);
    expect(await screen.findByText("已选 1 项")).toBeTruthy();

    fireEvent.click(batchBar().button(/^退出$/));

    await waitFor(() => expect(screen.queryByLabelText("选择对话")).toBeNull());
    // 再次进入应是干净的 0 项，不能残留上次的选中
    enterSelectMode();
    expect(await screen.findByText("已选 0 项")).toBeTruthy();
  });

  it("批量操作失败：提示失败而不是静默清空选中", async () => {
    deleteSessionsBatchMock.mockRejectedValueOnce(new Error("boom"));
    await renderView();
    enterSelectMode();
    checkCard(0);

    fireEvent.click(batchBar().button(/^删除$/));
    fireEvent.click(await screen.findByRole("button", { name: /^删除$/ }));

    expect(await screen.findByText(/批量删除失败/)).toBeTruthy();
  });
});
