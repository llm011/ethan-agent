import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { UserAvatar, avatarInitial, BUBBLE_AVATAR_SIZE } from "@ethan/shared/chat/user-avatar";
import { useUserIdentity, USER_IDENTITY_CACHE_KEY } from "@ethan/shared/chat/use-user-identity";
import { deleteCache } from "@ethan/shared/lib/local-cache";

// 头像的三层兜底是这次改动的核心风险点：任何一层漏了，用户看到的就是破图或空白，
// 而这类问题在 jsdom/单测里最容易「看起来没问题」。所以逐层断言。
//
// resolveUrl 用真实实现（assetUrl 的语义：相对路径 → 绝对 URL），而不是 identity mock，
// 这样顺带覆盖「空串不能拼出一个悬空 URL」这条边界。

const resolveUrl = (p: string) => (p ? `http://api.test/${p}` : "");

describe("UserAvatar 兜底", () => {
  it("未设置头像时显示名字首字母", () => {
    render(<UserAvatar url="" name="小明" resolveUrl={resolveUrl} />);
    expect(screen.getByText("小")).toBeTruthy();
    // 关键：不能渲染出一个 src 为空的 img（浏览器会当成当前页面 URL 再请求一次）
    expect(document.querySelector("img")).toBeNull();
  });

  it("未设置头像且没有名字时显示人形图标", () => {
    const { container } = render(<UserAvatar url="" name="" resolveUrl={resolveUrl} />);
    expect(screen.queryByText("小")).toBeNull();
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("设置了头像时渲染 img，src 是 resolveUrl 的结果", () => {
    render(<UserAvatar url="images/img_avatar.png" name="小明" resolveUrl={resolveUrl} />);
    const img = document.querySelector("img") as HTMLImageElement;
    expect(img).toBeTruthy();
    expect(img.getAttribute("src")).toBe("http://api.test/images/img_avatar.png");
    // 有图就不该再显示首字母
    expect(screen.queryByText("小")).toBeNull();
  });

  it("图片加载失败时退回首字母，而不是留一个破图", () => {
    render(<UserAvatar url="images/img_avatar.png" name="小明" resolveUrl={resolveUrl} />);
    const img = document.querySelector("img") as HTMLImageElement;

    fireEvent.error(img);

    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("小")).toBeTruthy();
  });

  it("换头像后失败态要重置 —— 否则新头像永远不显示", () => {
    const { rerender } = render(<UserAvatar url="images/a.png" name="小明" resolveUrl={resolveUrl} />);
    fireEvent.error(document.querySelector("img") as HTMLImageElement);

    rerender(<UserAvatar url="images/b.png" name="小明" resolveUrl={resolveUrl} />);

    const img = document.querySelector("img") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("http://api.test/images/b.png");
  });

  it("尺寸与 assistant 侧 logo 对齐（28px），否则一左一右不等高", () => {
    const { container } = render(<UserAvatar url="" name="小明" resolveUrl={resolveUrl} />);
    const el = container.querySelector('[data-slot="user-avatar"]') as HTMLElement;
    expect(el.style.width).toBe(`${BUBBLE_AVATAR_SIZE}px`);
    expect(el.style.height).toBe(`${BUBBLE_AVATAR_SIZE}px`);
    expect(BUBBLE_AVATAR_SIZE).toBe(28);
  });

  it("头像是装饰性的 —— 不应该被屏幕阅读器重复读一遍", () => {
    const { container } = render(<UserAvatar url="images/a.png" name="小明" resolveUrl={resolveUrl} />);
    expect(container.querySelector('[data-slot="user-avatar"]')?.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("avatarInitial", () => {
  it("取首个字素而不是首个 UTF-16 码元", () => {
    // emoji 是代理对，用 name[0] 会切出半个字符，渲染成乱码方块
    expect(avatarInitial("😀小明")).toBe("😀");
    expect(avatarInitial("😀小明").length).toBe(2); // 代理对本身占 2 个码元
  });

  it("英文取首字母并大写", () => {
    expect(avatarInitial("alice")).toBe("A");
  });

  it("空白/未设置返回空串（调用方据此回落到图标）", () => {
    expect(avatarInitial("")).toBe("");
    expect(avatarInitial("   ")).toBe("");
    expect(avatarInitial(undefined)).toBe("");
  });
});

// useUserIdentity 的命中/未命中行为：气泡里几十个实例共享一个缓存 key，
// 只有第一个真的发请求，其余命中缓存立即渲染。
describe("useUserIdentity 缓存", () => {
  function Probe({ fetcher }: { fetcher: () => Promise<never> }) {
    const { identity } = useUserIdentity(fetcher as never);
    return <span data-testid="name">{identity.display_name || "∅"}</span>;
  }

  it("无缓存时给出空态而不是 undefined，调用方不必判空", () => {
    deleteCache(USER_IDENTITY_CACHE_KEY);
    const fetcher = vi.fn().mockResolvedValue({ user_id: "", display_name: "", avatar_url: "" });
    render(<Probe fetcher={fetcher} />);
    expect(screen.getByTestId("name").textContent).toBe("∅");
  });

  it("缓存 key 与桌面端 api-settings 的 bustCache 一致", () => {
    // 两处字符串必须逐字相同，否则设置完头像气泡不会刷新
    expect(USER_IDENTITY_CACHE_KEY).toBe("userIdentity");
  });
});
