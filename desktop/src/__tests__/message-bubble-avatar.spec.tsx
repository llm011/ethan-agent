import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MessageBubble } from "@/components/chat/message-bubble";
import { fetchUserIdentity } from "@/lib/api";
import { USER_IDENTITY_CACHE_KEY } from "@ethan/shared/chat/use-user-identity";
import { deleteCache, writeCache } from "@ethan/shared/lib/local-cache";
import type { Message } from "@ethan/shared/chat/types";

// 气泡层的集成断言：证明确实把头像挂进了用户气泡、且 assistant 气泡不受影响。
//
// 这里刻意不 mock useUserIdentity，而是走真实缓存路径 —— 那条路径才是「设置完
// 头像气泡要立刻变」的实际依赖（上传后 bustCache → 重新 fetch）。

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchUserIdentity: vi.fn().mockResolvedValue({
      user_id: "",
      display_name: "小明",
      avatar_url: "images/img_avatar.png",
    }),
    fetchMessageIntermediate: vi.fn().mockResolvedValue(""),
    fetchToolRaw: vi.fn().mockResolvedValue({}),
  };
});

function makeMsg(role: "user" | "assistant"): Message {
  return { id: 1, role, content: "你好" } as Message;
}

beforeEach(() => {
  deleteCache(USER_IDENTITY_CACHE_KEY);
});

describe("MessageBubble 用户头像", () => {
  it("用户气泡渲染头像，assistant 气泡渲染 Ethan logo", async () => {
    const { container } = render(
      <MessageBubble msg={makeMsg("user")} isStreaming={false} isLast />,
    );
    await waitFor(() => {
      expect(container.querySelector('[data-slot="user-avatar"]')).toBeTruthy();
    });
    // 用户侧不该出现 Ethan 的 logo
    expect(container.querySelector('img[alt="Ethan"]')).toBeNull();
  });

  it("assistant 气泡不渲染用户头像", async () => {
    const { container } = render(
      <MessageBubble msg={makeMsg("assistant")} isStreaming={false} isLast />,
    );
    await waitFor(() => {
      expect(container.querySelector('img[alt="Ethan"]')).toBeTruthy();
    });
    expect(container.querySelector('[data-slot="user-avatar"]')).toBeNull();
  });

  it("设置过显示名时，名字出现在气泡顶部", async () => {
    writeCache(USER_IDENTITY_CACHE_KEY, {
      user_id: "",
      display_name: "小明",
      avatar_url: "",
    }, 60_000);

    render(<MessageBubble msg={makeMsg("user")} isStreaming={false} isLast />);

    await waitFor(() => {
      expect(screen.getByText("小明")).toBeTruthy();
    });
  });

  it("未设置名字时不渲染名字行（老用户气泡不凭空多一行）", async () => {
    // 这一条必须让 fetcher 也返回空名字：只写缓存会被 useCachedResource 的
    // 后台 refetch 覆盖掉（SWR 会拿新值替换旧值），那样测的就不是「空名字」了。
    vi.mocked(fetchUserIdentity).mockResolvedValueOnce({
      user_id: "",
      display_name: "",
      avatar_url: "images/img_avatar.png",
    });
    deleteCache(USER_IDENTITY_CACHE_KEY);

    const { container } = render(
      <MessageBubble msg={makeMsg("user")} isStreaming={false} isLast />,
    );

    // 头像还在，但顶部没有名字文本
    await waitFor(() => {
      const img = container.querySelector('[data-slot="user-avatar"] img');
      expect(img?.getAttribute("src")).toContain("images/img_avatar.png");
    });
    expect(screen.queryByText("小明")).toBeNull();
  });

  it("缓存命中时首帧就有头像 —— 不会先渲染占位再跳变", () => {
    writeCache(USER_IDENTITY_CACHE_KEY, {
      user_id: "",
      display_name: "小明",
      avatar_url: "images/img_avatar.png",
    }, 60_000);

    const { container } = render(
      <MessageBubble msg={makeMsg("user")} isStreaming={false} isLast />,
    );

    // 同步断言：没有 await，说明第一帧就已经是真实头像
    const img = container.querySelector('[data-slot="user-avatar"] img') as HTMLImageElement;
    expect(img).toBeTruthy();
    expect(img.getAttribute("src")).toContain("images/img_avatar.png");
  });
});
