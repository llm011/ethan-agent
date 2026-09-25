import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { AudioFileCard } from "@/components/chat/file-card";
import type { FileCard } from "@ethan/shared/chat/types";

// 回归：桌面端气泡内音频卡片一直「音频加载中…」。
//
// 历史 bug 有两层，任一层单独存在都会表现为永久 loading：
//   1) Tauri CSP 缺 media-src → 资源被拦，<audio> 不触发 error，UI 停在加载态（已在 tauri.conf.json 修）；
//   2) 前端只用 onError/onPlay 驱动状态，且 signedViewUrl 失败被静默吞掉 → 无任何出口。
// 这里锁住第 2 层：无论成功、失败还是「既不成功也不失败（挂死）」，都必须离开 loading。

const AUDIO_CARD: FileCard = {
  type: "file",
  filename: "digest.mp3",
  title: "听书摘要",
  path: "/Users/test/audio/digest.mp3",
  size_kb: 2048,
  kind: "mp3",
};

const signFileUrlMock = vi.hoisted(() => vi.fn());
vi.mock("@ethan/shared/ppt/preview", () => ({ signFileUrl: signFileUrlMock }));
vi.mock("@/lib/api-base", () => ({
  getApiUrl: () => "http://127.0.0.1:8900/api",
  getAuthToken: () => "test-token",
}));
vi.mock("@/lib/external-link", () => ({ openUrl: vi.fn() }));

const signed = (path: string) => ({ [path]: { user: "u1", sig: "sig123" } });

describe("AudioFileCard 加载状态机", () => {
  beforeEach(() => {
    signFileUrlMock.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("签名成功后渲染 audio 元素，脱离加载态", async () => {
    signFileUrlMock.mockResolvedValue(signed(AUDIO_CARD.path));

    const { container } = render(<AudioFileCard card={AUDIO_CARD} sessionId="s1" />);

    await waitFor(() => {
      expect(container.querySelector("audio")).toBeTruthy();
    });
    const audio = container.querySelector("audio")!;
    // 直链必须带上签名与 session_id，否则服务端 401
    expect(audio.getAttribute("src")).toContain("sig=sig123");
    expect(audio.getAttribute("src")).toContain("session_id=s1");
  });

  it("签名接口失败时进入明确错误态，而不是无限 loading", async () => {
    // signFileUrl 真实实现吞掉异常返回 {}，这里模拟其失败语义（无签名可用）
    signFileUrlMock.mockResolvedValue({});

    render(<AudioFileCard card={AUDIO_CARD} sessionId="s1" />);

    // 关键：必须出现错误提示 + 重试入口
    await waitFor(() => {
      expect(screen.getByText("音频加载失败")).toBeTruthy();
    });
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
  });

  it("资源既无 canplay 也无 error（被 CSP 拦截/连接挂死）时，看门狗超时兜底到错误态", async () => {
    vi.useFakeTimers();
    signFileUrlMock.mockResolvedValue(signed(AUDIO_CARD.path));

    const { container } = render(<AudioFileCard card={AUDIO_CARD} sessionId="s1" />);
    await act(async () => { await Promise.resolve(); });
    expect(container.querySelector("audio")).toBeTruthy();

    // 不触发任何媒体事件，模拟被静默拦截的情形
    await act(async () => { vi.advanceTimersByTime(20_000); });

    expect(screen.getByText("音频加载失败")).toBeTruthy();
  });

  it("loadedmetadata 到达后进入 ready，看门狗不再把它翻成错误态", async () => {
    vi.useFakeTimers();
    signFileUrlMock.mockResolvedValue(signed(AUDIO_CARD.path));

    const { container } = render(<AudioFileCard card={AUDIO_CARD} sessionId="s1" />);
    await act(async () => { await Promise.resolve(); });

    const audio = container.querySelector("audio")!;
    await act(async () => {
      audio.dispatchEvent(new Event("loadedmetadata"));
    });

    // 播完之后看门狗即使到点也不能误判失败
    await act(async () => { vi.advanceTimersByTime(60_000); });

    expect(screen.queryByText("音频加载失败")).toBeNull();
    expect(container.querySelector("audio")).toBeTruthy();
  });

  it("错误态点重试会重新签名并恢复播放器", async () => {
    signFileUrlMock.mockResolvedValueOnce({});
    render(<AudioFileCard card={AUDIO_CARD} sessionId="s1" />);

    await waitFor(() => expect(screen.getByText("音频加载失败")).toBeTruthy());

    signFileUrlMock.mockResolvedValue(signed(AUDIO_CARD.path));
    await act(async () => {
      screen.getByRole("button", { name: "重试" }).click();
    });

    await waitFor(() => {
      expect(screen.queryByText("音频加载失败")).toBeNull();
    });
  });
});
